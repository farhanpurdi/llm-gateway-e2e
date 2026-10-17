import hashlib
import json
import subprocess
import sys
import time

import pytest

from tests.accounting import PRICES
from tests.opencode import PROMPT, VERIFIER, assert_agent_workflow, parse_events, run_cli


def test_opencode_onboarding_uses_developer_key(admin_client, opencode_developer, pilot_policy):
    ctx = opencode_developer
    key = admin_client.key_info(ctx["virtual_key"])
    assert key["user_id"] == ctx["user_id"]
    assert key["team_id"] == ctx["team_id"]
    assert key["models"] == ["all-team-models"]
    team = admin_client.team_info(ctx["team_id"])["team_info"]
    assert set(team["models"]) == set(pilot_policy["models"])
    for field, policy_name in (("max_budget", "monthly_budget_usd"),
                               ("rpm_limit", "rpm"), ("tpm_limit", "tpm")):
        assert team[field] == pilot_policy["limits"]["team"][policy_name]
    budget = admin_client.member_info(ctx["team_id"], ctx["user_id"])["litellm_budget_table"]
    assert budget["max_budget"] == pilot_policy["limits"]["member"]["monthly_budget_usd"]
    assert budget["budget_duration"] == "30d" and budget["budget_reset_at"]
    models = ctx["client"].expect_json(ctx["client"].get("/v1/models"))["data"]
    assert {row["id"] for row in models} == set(pilot_policy["models"])
    user = admin_client.expect_json(admin_client.get("/user/info", params={"user_id": ctx["user_id"]}))["user_info"]
    assert user["user_role"] == "internal_user"
    print("P1_ONBOARDING " + json.dumps({"user_id": ctx["user_id"], "team_id": ctx["team_id"],
          "models": sorted(team["models"]), "policy": "pilot", "operator_script": True}))


@pytest.mark.live
@pytest.mark.parametrize("alias", ["company-fast", "company-coding"])
def test_opencode_agent_reads_edits_runs_and_uses_tool_result(
        admin_client, opencode_developer, opencode_project, alias):
    project = opencode_project["path"]
    output = run_cli(
        [opencode_project["executable"], "run", "--standalone", "--format", "json",
         "--agent", "build", "--model", "company-ai/" + alias, PROMPT],
        cwd=project, env=opencode_project["env"],
    )
    events = parse_events(output)
    print("P1_OPENCODE_TRACE " + json.dumps({"alias": alias, "events": [
        {"type": event.get("type"), "tool": event.get("part", {}).get("tool"),
         "status": event.get("part", {}).get("state", {}).get("status")}
        for event in events]}))
    receipt_path = project / "receipt.json"
    assert receipt_path.exists(), "The real verifier did not run"
    assert (project / "verify.py").read_text() == VERIFIER, "Agent modified the verifier"
    summary = assert_agent_workflow(events, json.loads(receipt_path.read_text()))
    # Independently execute the unchanged verifier against the resulting code.
    check = subprocess.run([sys.executable, "verify.py"], cwd=project,
                           capture_output=True, text=True, timeout=10, check=False)
    assert check.returncode == 0, "Resulting code failed independent verification"
    ctx = opencode_developer
    expected_requests = sum(event.get("type") == "step_start" for event in events)
    assert 1 <= expected_requests <= 8, "Agent exceeded the bounded scenario"
    keys = admin_client.list_user_keys(user_id=ctx["user_id"])
    assert len(keys) == 1, "Expected one developer credential"
    rows = []
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        history = admin_client.list_user_spend_logs_page(
            user_id=ctx["user_id"], start_date="2026-01-01 00:00:00", end_date="2099-01-01 00:00:00")
        assert not history.get("total_is_capped", False)
        assert history["total"] == len(history["data"]), "Unexpected history truncation"
        rows = [row for row in history["data"] if row.get("model_group") == alias]
        if len(rows) == expected_requests and sum(row.get("completion_tokens", 0) for row in rows) > 0:
            break
        time.sleep(1)
    assert len(rows) == expected_requests, "OpenCode request history is incomplete or unexpected"
    for row in rows:
        assert row["user"] == ctx["user_id"] and row["team_id"] == ctx["team_id"]
        assert row["api_key"] == keys[0]["token"], "Spend belongs to a different credential"
        assert row["model"] in {PRICES[alias]["upstream"], PRICES[alias]["upstream"].removeprefix("openai/")}
        assert 0 <= row["completion_tokens"] <= 768, "Output exceeded fixture token bound"
    summary.update(alias=alias, user_id=ctx["user_id"], team_id=ctx["team_id"],
                   persisted_requests=len(rows),
                   prompt_tokens=sum(row["prompt_tokens"] for row in rows),
                   completion_tokens=sum(row["completion_tokens"] for row in rows),
                   native_spend_usd=sum(row["spend"] for row in rows),
                   code=(project / "calculator.py").read_text(),
                   code_sha256=hashlib.sha256((project / "calculator.py").read_bytes()).hexdigest())
    print("P1_OPENCODE_AGENT " + json.dumps(summary))
