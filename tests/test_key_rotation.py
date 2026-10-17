"""Rotate disposable virtual keys without deleting native identity or spend history."""
import json
import time
import uuid

import pytest

from tests.client import LiteLLMClient, RedactedKey


def infer(client, alias):
    return client.post("/v1/chat/completions", json={
        "model": alias, "messages": [{"role": "user", "content": "Reply exactly: ok"}],
        "max_tokens": 16, "reasoning_effort": "none",
    })


@pytest.mark.live
@pytest.mark.parametrize("alias", ["company-fast", "company-coding"])
def test_virtual_key_rotation_preserves_scope_and_audit(
        admin_client, base_url, pilot_identity_factory, alias):
    identity = pilot_identity_factory(prefix="e2e-rotate-", purpose="P1-16-rotation",
                                      first_key_budget=0.01)
    old = identity["keys"][0]
    before = infer(old["client"], alias)
    assert before.status_code == 200, "Original key did not work"
    request_ids = [before.json()["id"]]
    original = admin_client.key_info(old["virtual_key"])
    fields = ("user_id", "team_id", "models", "max_budget", "budget_duration",
              "rpm_limit", "tpm_limit")
    payload = {field: original[field] for field in fields if original.get(field) is not None}
    payload.update(key_alias="e2e-rotate-replacement-" + uuid.uuid4().hex[:8],
                   metadata={"environment": "e2e", "purpose": "P1-16-rotation"})
    replacement = admin_client.expect_json(admin_client.post("/key/generate", json=payload))
    new = {"virtual_key": RedactedKey(replacement["key"]), "user_id": old["user_id"],
           "client": LiteLLMClient(base_url, replacement["key"])}
    identity["keys"].append(new)  # Register before verification, including partial failure.
    assert new["virtual_key"] != old["virtual_key"], "Rotation returned the old credential"
    replacement_info = admin_client.key_info(new["virtual_key"])
    for field in fields:
        assert replacement_info.get(field) == original.get(field), "Replacement scope changed: " + field
    assert new["client"].get("/v1/models").status_code == 200
    accepted = infer(new["client"], alias)
    assert accepted.status_code == 200, "Replacement failed before cutover"
    request_ids.append(accepted.json()["id"])
    admin_client.expect_json(admin_client.post("/key/block", json={"key": old["virtual_key"]}))
    assert admin_client.key_info(old["virtual_key"])["blocked"] is True
    assert infer(old["client"], alias).status_code in {401, 403}, "Old key remained valid"
    accepted = infer(new["client"], alias)
    assert accepted.status_code == 200, "Replacement failed after cutover"
    request_ids.append(accepted.json()["id"])
    deadline = time.monotonic() + 45
    persisted = set()
    old_spend = new_spend = team_spend = 0
    while time.monotonic() < deadline:
        page = admin_client.list_user_spend_logs_page(user_id=old["user_id"],
            start_date="2026-01-01 00:00:00", end_date="2099-01-01 00:00:00")
        persisted = {row["request_id"] for row in page["data"] if row.get("spend", 0) > 0}
        # Native spend rows and aggregate counters flush asynchronously, separately.
        old_spend = admin_client.key_info(old["virtual_key"])["spend"]
        new_spend = admin_client.key_info(new["virtual_key"])["spend"]
        team_spend = admin_client.team_info(identity["team_id"])["team_info"]["spend"]
        if set(request_ids) <= persisted and min(old_spend, new_spend, team_spend) > 0:
            break
        time.sleep(1)
    assert set(request_ids) <= persisted, "Rotation lost an accepted request's spend history"
    assert len(admin_client.list_user_keys(user_id=old["user_id"])) == 3, "Key history was deleted"
    assert old_spend > 0, "Old key spend was lost"
    assert new_spend > 0, "New key spend was lost"
    assert team_spend > 0, "Team spend was lost"
    print("P1_KEY_ROTATION " + json.dumps({"alias": alias, "old_denied": True,
          "new_accepted": True, "same_scope": True, "records_and_spend_retained": True}))
