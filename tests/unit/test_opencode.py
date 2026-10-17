import copy
import json
from pathlib import Path
import sys

import pytest

from tests.opencode import (
    assert_agent_workflow, cli_environment, parse_events, prepare_project, run_cli,
)


pytestmark = pytest.mark.unit
RECEIPT = {"status": "PASS", "receipt": "a" * 32}


def workflow():
    def tool(name, data, output="done"):
        return {"type": "tool_use", "part": {"tool": name, "state": {
            "status": "completed", "input": data, "output": output}}}
    return [tool("read", {"filePath": "calculator.py"}),
            tool("edit", {"filePath": "calculator.py"}),
            tool("shell", {"command": "python3 verify.py"}, json.dumps(RECEIPT)),
            {"type": "text", "part": {"text": "PASS " + RECEIPT["receipt"]}}]


def test_actual_tool_sequence_is_accepted():
    assert assert_agent_workflow(workflow(), RECEIPT)["receipt_consumed"] is True


@pytest.mark.parametrize("fault", [
    "text-only", "missing-read", "missing-edit", "shell-not-completed",
    "wrong-command", "wrong-tool-result", "wrong-final-receipt", "wrong-order",
])
def test_success_text_cannot_replace_actual_tool_result(fault):
    events = workflow()
    if fault == "text-only":
        events = events[-1:]
    elif fault == "missing-read":
        events = events[1:]
    elif fault == "missing-edit":
        events.pop(1)
    elif fault == "shell-not-completed":
        events[2]["part"]["state"]["status"] = "error"
    elif fault == "wrong-command":
        events[2]["part"]["state"]["input"]["command"] = "echo PASS"
    elif fault == "wrong-tool-result":
        events[2]["part"]["state"]["output"] = "PASS"
    elif fault == "wrong-final-receipt":
        events[-1]["part"]["text"] = "PASS " + "b" * 32
    elif fault == "wrong-order":
        events[-1], events[-2] = events[-2], events[-1]
    with pytest.raises(AssertionError):
        assert_agent_workflow(events, RECEIPT)


@pytest.mark.parametrize("output", ["not-json unit-credential", "[]", "", '{"type":"error","error":"unit-credential"}'])
def test_invalid_cli_events_fail_without_raw_output(output):
    with pytest.raises(AssertionError) as error:
        parse_events(output)
    assert "unit-credential" not in str(error.value)


def test_cli_failure_suppresses_stdout_and_stderr(tmp_path):
    with pytest.raises(AssertionError) as error:
        run_cli([sys.executable, "-c", "print('unit-credential'); raise SystemExit(4)"],
                cwd=tmp_path, env={"PATH": "/usr/bin:/bin"})
    assert "exit 4" in str(error.value)
    assert "unit-credential" not in str(error.value)


def test_cli_environment_does_not_inherit_admin_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "unit-admin-only")
    monkeypatch.setenv("OPENAI_API_KEY", "unit-provider-only")
    monkeypatch.setenv("OPENCODE_CONFIG", "/personal/settings.json")
    env = cli_environment(tmp_path, "unit-developer-only")
    assert not {"LITELLM_MASTER_KEY", "OPENAI_API_KEY", "OPENCODE_CONFIG"} & env.keys()
    assert env["COMPANY_LLM_API_KEY"] == "unit-developer-only"
    assert all(str(tmp_path) in env[f"XDG_{name}_HOME"] for name in ("DATA", "CONFIG", "STATE", "CACHE"))


def test_fixture_uses_real_template_without_mutating_it(tmp_path):
    # Unit CI checks out only E2E. Live acceptance loads the actual config sibling;
    # this unit checks transformation/permissions using the same public contract.
    template = {"model": "company-ai/company-coding", "providers": {"company-ai": {
        "env": ["COMPANY_LLM_API_KEY"], "settings": {"baseURL": "http://localhost:4000/v1"},
        "package": "@opencode/ai/providers/openai-compatible",
        "models": {"company-fast": {}, "company-coding": {}},
    }}}
    before = copy.deepcopy(template)
    config = prepare_project(tmp_path / "project", template, "http://localhost:4000")
    assert template == before
    assert set(config["providers"]) == {"company-ai"}
    assert set(config["providers"]["company-ai"]["models"]) == {"company-fast", "company-coding"}
    assert config["agents"]["build"]["steps"] == 8
    assert config["providers"]["company-ai"]["body"]["max_tokens"] == 768
    assert {"action": "external_directory", "resource": "*", "effect": "deny"} in config["permissions"]
