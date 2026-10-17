import pytest
import time

from tests.client import LiteLLMClient
from datetime import datetime, timedelta, timezone


@pytest.mark.live
def test_multiple_user_keys_work_before_offboarding(
    admin_client: LiteLLMClient,
    multi_key_identity: dict,
    multi_key_clients: dict[str, LiteLLMClient],
    fast_model: str,
):
    keys = multi_key_identity["keys"]

    assert set(keys) == {
        "developer-laptop",
        "developer-ci",
    }
    assert set(multi_key_clients) == set(keys)

    distinct_keys = (
        keys["developer-laptop"]["virtual_key"]
        != keys["developer-ci"]["virtual_key"]
    )

    assert distinct_keys, "Expected two distinct virtual keys"

    for usage, client in multi_key_clients.items():
        key_alias = keys[usage]["key_alias"]

        response = admin_client.get(
            "/key/info",
            params={
                "key": keys[usage]["virtual_key"],
            },
        )

        assert response.status_code == 200, (
            f"Cannot read key info for {key_alias}: "
            f"HTTP {response.status_code}"
        )

        info = response.json()["info"]

        same_user = (
            info.get("user_id")
            == multi_key_identity["user_id"]
        )
        same_team = (
            info.get("team_id")
            == multi_key_identity["team_id"]
        )

        assert same_user, f"Unexpected user for {key_alias}"
        assert same_team, f"Unexpected team for {key_alias}"

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": fast_model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with exactly: ok",
                    },
                ],
                "max_tokens": 8,
            },
        )

        print(
            f"{key_alias}: HTTP {response.status_code}"
        )

        assert response.status_code == 200, (
            f"Key should work before offboarding: {key_alias}, "
            f"HTTP {response.status_code}"
        )

        content = (
            response.json()["choices"][0]
            ["message"]["content"]
        )

        assert isinstance(content, str) and content.strip(), (
            f"Expected non-empty inference content for {key_alias}"
        )


@pytest.mark.live
@pytest.mark.spend
def test_user_offboarding_blocks_all_keys(
    admin_client: LiteLLMClient,
    multi_key_identity: dict,
    multi_key_clients: dict[str, LiteLLMClient],
    fast_model: str,
):
    user_id = multi_key_identity["user_id"]

    history_start = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).strftime("%Y-%m-%d %H:%M:%S")

    # 1. Temukan key melalui gateway.
    before = admin_client.list_user_keys(
        user_id=user_id,
        page_size=1,
    )

    expected_aliases = {
        item["key_alias"]
        for item in multi_key_identity["keys"].values()
    }

    actual_aliases = {
        item["key_alias"]
        for item in before
    }

    assert len(before) == 2
    assert actual_aliases == expected_aliases

    # 2. Buktikan kedua credential bisa digunakan.
    for usage, client in multi_key_clients.items():
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": fast_model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with exactly: ok",
                    },
                ],
                "max_tokens": 8,
            },
        )

        print(
            f"before offboarding: {usage}, "
            f"HTTP {response.status_code}"
        )

        assert response.status_code == 200, (
            f"{usage} should work before offboarding"
        )

        content = (
            response.json()["choices"][0]
            ["message"]["content"]
        )

        assert isinstance(content, str) and content.strip()

    # Tunggu spend kedua key dan user tercatat.
    deadline = time.monotonic() + 20

    key_spend_before = {}
    user_spend_before = 0.0
    spend_ready = False

    while time.monotonic() < deadline:
        snapshot = admin_client.list_user_keys(
            user_id=user_id,
            page_size=1,
        )

        same_keys = (
            {item["token"] for item in snapshot}
            == {item["token"] for item in before}
        )

        assert same_keys, (
            "Key records changed while waiting for spend"
        )

        key_spend_before = {
            item["token"]: float(item.get("spend") or 0)
            for item in snapshot
        }

        response = admin_client.get(
            "/user/info",
            params={
                "user_id": user_id,
            },
        )

        assert response.status_code == 200, (
            "Cannot read user spend: "
            f"HTTP {response.status_code}"
        )

        user_info = response.json().get("user_info", {})

        user_spend_before = float(
            user_info.get("spend") or 0
        )

        spend_ready = (
            len(key_spend_before) == 2
            and all(
                spend > 0
                for spend in key_spend_before.values()
            )
            and user_spend_before > 0
        )

        if spend_ready:
            break

        time.sleep(1)

    assert spend_ready, (
        "Spend was not recorded for both keys and user "
        "within the polling window"
    )

    print(
        "before offboarding: "
        f"keys_with_spend={len(key_spend_before)}, "
        f"user_spend={user_spend_before:.8f}"
    )

    history_end = (
        datetime.now(timezone.utc) + timedelta(minutes=1)
    ).strftime("%Y-%m-%d %H:%M:%S")

    expected_tokens = set(key_spend_before)
    history_before = {}
    deadline = time.monotonic() + 20

    while time.monotonic() < deadline:
        history_page = admin_client.list_user_spend_logs_page(
            user_id=user_id,
            start_date=history_start,
            end_date=history_end,
        )

        rows = history_page["data"]

        # Fixture ini hanya menghasilkan sedikit request.
        # Jangan diam-diam mengabaikan halaman tambahan.
        assert not history_page.get("total_is_capped", False)
        assert history_page["total"] == len(rows), (
            "History exceeds one page; pagination is required"
        )

        history_before = {}

        for row in rows:
            spend = float(row.get("spend") or 0)

            if spend <= 0:
                continue

            request_id = row.get("request_id")
            assert isinstance(request_id, str) and request_id, (
                "Paid history record has no request identifier"
            )

            known_key = row.get("api_key") in expected_tokens
            same_user = row.get("user") == user_id
            same_team = (
                row.get("team_id")
                == multi_key_identity["team_id"]
            )

            assert known_key, "Unexpected key in paid history"
            assert same_user, "Unexpected user in paid history"
            assert same_team, "Unexpected team in paid history"
            assert request_id not in history_before, (
                "Duplicate request identifier in paid history"
            )

            history_before[request_id] = {
                "api_key": row["api_key"],
                "user": row["user"],
                "team_id": row["team_id"],
                "spend": spend,
            }

        covered_tokens = {
            row["api_key"]
            for row in history_before.values()
        }

        if covered_tokens == expected_tokens:
            break

        time.sleep(1)

    all_keys_covered = (
        {
            row["api_key"]
            for row in history_before.values()
        }
        == expected_tokens
    )

    assert all_keys_covered, (
        "Paid history was not recorded for both keys "
        "within the polling window"
    )

    print(
        "history before offboarding: "
        f"paid_records={len(history_before)}, "
        f"keys_covered={len(expected_tokens)}"
    )

    # 3. Offboard berdasarkan user_id saja.
    result = admin_client.offboard_user_keys(
        user_id=user_id,
        page_size=1,
    )

    assert result["discovered_count"] == 2
    assert result["blocked_count"] == 2

    # 4. Baca ulang status yang tersimpan.
    after = admin_client.list_user_keys(
        user_id=user_id,
        page_size=1,
    )

    assert len(after) == 2

    same_keys = (
        {item["token"] for item in before}
        == {item["token"] for item in after}
    )

    assert same_keys, "Key records changed during offboarding"

    for item in after:
        key_alias = item["key_alias"]
        blocked = item.get("blocked")

        print(
            f"after offboarding: {key_alias}, "
            f"blocked={blocked}"
        )

        assert blocked is True, (
            f"Key is not blocked: {key_alias}"
        )

    # 5. Credential lama harus ditolak setelah offboarding.
    rejected_statuses = {}

    for usage, client in multi_key_clients.items():
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": fast_model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with exactly: ok",
                    },
                ],
                "max_tokens": 8,
            },
        )

        rejected_statuses[usage] = response.status_code

        print(
            f"after offboarding: {usage}, "
            f"HTTP {response.status_code}"
        )

    assert len(rejected_statuses) == 2

    for usage, status in rejected_statuses.items():
        assert status in {401, 403}, (
            f"Old key should be rejected: {usage}, "
            f"HTTP {status}"
        )

    # 6. Periksa retensi spend dan atribusi setelah offboarding.
    retained_keys = admin_client.list_user_keys(
        user_id=user_id,
        page_size=1,
    )

    same_keys = (
        {item["token"] for item in retained_keys}
        == set(key_spend_before)
    )

    assert same_keys, (
        "Key records were lost or replaced after offboarding"
    )

    for item in retained_keys:
        key_alias = item["key_alias"]

        same_user = item.get("user_id") == user_id
        same_team = (
            item.get("team_id")
            == multi_key_identity["team_id"]
        )

        assert same_user, f"User attribution changed: {key_alias}"
        assert same_team, f"Team attribution changed: {key_alias}"

        spend_before = key_spend_before[item["token"]]
        spend_after = float(item.get("spend") or 0)

        assert spend_after >= spend_before, (
            f"Key spend decreased after offboarding: {key_alias}, "
            f"before={spend_before}, after={spend_after}"
        )

        print(
            f"retained: {key_alias}, "
            f"spend_before={spend_before:.8f}, "
            f"spend_after={spend_after:.8f}"
        )

    response = admin_client.get(
        "/user/info",
        params={
            "user_id": user_id,
        },
    )

    assert response.status_code == 200, (
        "User record is unavailable after offboarding: "
        f"HTTP {response.status_code}"
    )

    user_info_after = response.json().get("user_info", {})

    same_user_record = (
        user_info_after.get("user_id") == user_id
    )

    assert same_user_record, "Unexpected user record after offboarding"

    user_spend_after = float(
        user_info_after.get("spend") or 0
    )

    assert user_spend_after >= user_spend_before, (
        "User spend decreased after offboarding: "
        f"before={user_spend_before}, after={user_spend_after}"
    )

    print(
        "retained user spend: "
        f"before={user_spend_before:.8f}, "
        f"after={user_spend_after:.8f}"
    )

        # 7. Histori request sebelum offboarding harus tetap utuh.
    history_page_after = admin_client.list_user_spend_logs_page(
        user_id=user_id,
        start_date=history_start,
        end_date=history_end,
    )

    rows_after = history_page_after["data"]

    assert not history_page_after.get("total_is_capped", False)
    assert history_page_after["total"] == len(rows_after), (
        "History exceeds one page; pagination is required"
    )

    history_after = {}

    for row in rows_after:
        request_id = row.get("request_id")

        # Hanya bandingkan request yang sudah ada pada baseline.
        if request_id not in history_before:
            continue

        assert request_id not in history_after, (
            "Duplicate baseline request in retained history"
        )

        history_after[request_id] = row

    all_requests_retained = (
        set(history_after) == set(history_before)
    )

    assert all_requests_retained, (
        "Historical requests disappeared after offboarding: "
        f"expected={len(history_before)}, "
        f"found={len(history_after)}"
    )

    for request_id, original in history_before.items():
        retained = history_after[request_id]

        same_attribution = all(
            retained.get(field) == original[field]
            for field in ("api_key", "user", "team_id")
        )

        assert same_attribution, (
            "Historical key/user/team attribution changed "
            "after offboarding"
        )

        spend_after = float(retained.get("spend") or 0)

        assert spend_after == original["spend"], (
            "Historical request spend changed after offboarding: "
            f"before={original['spend']}, "
            f"after={spend_after}"
        )

    print(
        "history retained: "
        f"requests={len(history_after)}, "
        "attribution_unchanged=True, "
        "spend_unchanged=True"
    )