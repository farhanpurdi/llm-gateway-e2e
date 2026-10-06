import pytest
import time

from tests.client import LiteLLMClient


@pytest.mark.live
@pytest.mark.limits
def test_team_rpm_limit_is_enforced(
    rpm_user_client: LiteLLMClient,
    rpm_limited_identity: dict,
    fast_model: str,
):
    assert rpm_limited_identity["rpm_limit"] == 2

    payload = {
        "model": fast_model,
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly: ok",
            }
        ],
        "max_tokens": 8,
    }

    responses = []

    for request_number in range(1, 4):
        response = rpm_user_client.post(
            "/v1/chat/completions",
            json=payload,
        )

        print(
            f"request #{request_number}: "
            f"{response.status_code}"
        )

        responses.append(response)

    statuses = [
        response.status_code
        for response in responses
    ]

    assert statuses[0] == 200, (
        "First request should be allowed. "
        f"statuses={statuses}"
    )

    assert statuses[1] == 200, (
        "Second request should be allowed. "
        f"statuses={statuses}"
    )

    assert statuses[2] == 429, (
        "Third request should be rate limited. "
        f"statuses={statuses}. "
        f"response={responses[2].text}"
    )


@pytest.mark.live
@pytest.mark.limits
def test_key_budget_is_enforced(
    admin_client: LiteLLMClient,
    budget_user_client: LiteLLMClient,
    budget_limited_identity: dict,
    fast_model: str,
):
    virtual_key = budget_limited_identity["virtual_key"]
    max_budget = budget_limited_identity["max_budget"]

    payload = {
        "model": fast_model,
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly: ok",
            }
        ],
        "max_tokens": 8,
    }

    #
    # First request should be accepted because
    # key spend starts at zero.
    #

    first = budget_user_client.post(
        "/v1/chat/completions",
        json=payload,
    )

    assert first.status_code == 200, (
        "First request should be allowed. "
        f"status={first.status_code}, "
        f"response={first.text}"
    )

    #
    # Spend persistence is asynchronous.
    #
    # Poll /key/info until recorded spend has
    # crossed the tiny key budget.
    #

    deadline = time.time() + 20
    current_spend = 0.0

    while time.time() < deadline:
        response = admin_client.get(
            "/key/info",
            params={
                "key": virtual_key,
            },
        )

        info_data = admin_client.expect_json(response)

        info = info_data.get(
            "info",
            {},
        )

        current_spend = float(
            info.get("spend") or 0
        )

        if current_spend >= max_budget:
            break

        time.sleep(1)

    assert current_spend >= max_budget, (
        "Spend was not persisted before timeout. "
        f"current_spend={current_spend}, "
        f"max_budget={max_budget}"
    )

    #
    # Key has now exceeded its budget.
    # v1.104.0 default behavior = HTTP 422.
    #

    second = budget_user_client.post(
        "/v1/chat/completions",
        json=payload,
    )

    assert second.status_code == 422, (
        "Expected exhausted key budget to be rejected "
        "with HTTP 422. "
        f"status={second.status_code}, "
        f"response={second.text}"
    )


@pytest.mark.live
@pytest.mark.limits
def test_blocked_key_is_rejected(
    admin_client: LiteLLMClient,
    user_client: LiteLLMClient,
    e2e_identity: dict,
    fast_model: str,
):
    payload = {
        "model": fast_model,
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly: ok",
            }
        ],
        "max_tokens": 8,
    }

    #
    # 1. Key harus aktif sebelum diblok.
    #

    before = user_client.post(
        "/v1/chat/completions",
        json=payload,
    )

    assert before.status_code == 200, (
        "Virtual key should work before blocking. "
        f"status={before.status_code}, "
        f"response={before.text}"
    )

    #
    # 2. Block key yang sama.
    #

    response = admin_client.post(
        "/key/block",
        json={
            "key": e2e_identity["virtual_key"],
        },
    )

    admin_client.expect_json(response)

    #
    # 3. Key yang sama sekarang harus ditolak.
    #

    after = user_client.post(
        "/v1/chat/completions",
        json=payload,
    )

    assert after.status_code in {
        401,
        403,
    }, (
        "Blocked virtual key was still accepted. "
        f"status={after.status_code}, "
        f"response={after.text}"
    )