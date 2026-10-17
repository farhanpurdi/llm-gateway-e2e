"""Explicit maintenance gate: negative auth/ACL/budget and retained accounting."""
import json
import time

import pytest

from tests.client import LiteLLMClient


def chat(client, alias="company-fast"):
    return client.post("/v1/chat/completions", json={"model": alias,
        "messages": [{"role": "user", "content": "Reply exactly: ok"}],
        "max_tokens": 16, "reasoning_effort": "none"})


@pytest.mark.live
@pytest.mark.outage
@pytest.mark.parametrize("dependency", ["postgres", "redis"])
def test_dependency_outage_preserves_denials_and_recovers(
        admin_client, base_url, pilot_identity_factory, dependency_outage, dependency):
    valid = pilot_identity_factory(prefix="e2e-outage-", purpose="P1-13-outage")
    denied = pilot_identity_factory(prefix="e2e-outage-", purpose="P1-13-outage")
    budget = pilot_identity_factory(prefix="e2e-outage-", purpose="P1-13-outage", first_key_budget=0.000001)
    active = valid["keys"][0]["client"]
    cold = valid["keys"][1]["client"]
    blocked = valid["keys"][2]
    denied_client = denied["keys"][0]["client"]
    exhausted = budget["keys"][0]
    assert chat(exhausted["client"]).status_code == 200
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if (admin_client.key_info(exhausted["virtual_key"]).get("spend") or 0) > 0.000001:
            break
        time.sleep(1)
    assert chat(exhausted["client"]).status_code == 422
    admin_client.expect_json(admin_client.post("/key/block", json={"key": blocked["virtual_key"]}))
    admin_client.expect_json(admin_client.post("/team/update", json={
        "team_id": denied["team_id"], "models": ["company-fast"]}))
    # Expire the cold token's native60s cache, then warm only the intended grants.
    time.sleep(65)
    assert active.get("/v1/models").status_code == 200
    assert chat(blocked["client"]).status_code in {401, 403}
    assert chat(denied_client, "company-coding").status_code == 403
    assert chat(exhausted["client"]).status_code == 422
    invalid = LiteLLMClient(base_url, "sk-invalid-outage-fixture", timeout=20)
    expected_ids = []
    statuses = {}
    for item in (active, cold, blocked["client"], denied_client, exhausted["client"]):
        item.timeout = 20
    with dependency_outage(dependency):
        for label, client, alias in (
            ("cold", cold, "company-fast"), ("invalid", invalid, "company-fast"),
            ("blocked", blocked["client"], "company-fast"),
            ("denied", denied_client, "company-coding"),
            ("exhausted", exhausted["client"], "company-fast"),
        ):
            response = chat(client, alias)
            statuses[label] = response.status_code
            if label == "cold" and dependency == "redis":
                assert response.status_code == 200
                expected_ids.append(response.json()["id"])
            else:
                allowed = ({401, 403, 422, 503} if dependency == "postgres" else
                           ({403} if label == "denied" else {422} if label == "exhausted" else {401, 403}))
                assert response.status_code in allowed, "Negative/cold access was unexpectedly accepted or returned the wrong error"
                assert "error" in response.json()
        # Pinned existing configuration denies warm grants when PostgreSQL is down.
        # Redis is not configured as native cache here, so it must not affect inference.
        warm = chat(active)
        statuses["warm"] = warm.status_code
        assert warm.status_code == (503 if dependency == "postgres" else 200)
        if warm.status_code == 200:
            expected_ids.append(warm.json()["id"])
    deadline = time.monotonic() + 90
    ready = False
    while time.monotonic() < deadline:
        try:
            ready = admin_client.get("/health/readiness").status_code == 200
        except Exception:
            ready = False
        if ready:
            break
        time.sleep(1)
    assert ready, "Gateway did not recover readiness"
    assert chat(blocked["client"]).status_code in {401, 403}, "Blocked key changed after recovery"
    assert chat(denied_client, "company-coding").status_code == 403, "ACL changed after recovery"
    assert chat(exhausted["client"]).status_code == 422, "Exhausted budget changed after recovery"
    for alias in ("company-fast", "company-coding"):
        response = chat(active, alias)
        assert response.status_code == 200, "Real provider recovery failed"
        expected_ids.append(response.json()["id"])
    deadline = time.monotonic() + 45
    persisted = set()
    while time.monotonic() < deadline:
        page = admin_client.list_user_spend_logs_page(user_id=valid["users"][0],
            start_date="2026-01-01 00:00:00", end_date="2099-01-01 00:00:00")
        persisted = {row["request_id"] for row in page["data"] if row.get("spend", 0) > 0}
        if set(expected_ids) <= persisted:
            break
        time.sleep(1)
    assert set(expected_ids) <= persisted, "An accepted outage/recovery request lost its spend record"
    print("P1_DEPENDENCY_OUTAGE " + json.dumps({"dependency": dependency, "statuses": statuses,
          "recovered_aliases": ["company-fast", "company-coding"], "accepted_requests_persisted": True}))
