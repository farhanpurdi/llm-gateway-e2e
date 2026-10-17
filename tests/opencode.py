"""CLI adapter and pure evidence checks; gateway HTTP remains in client.py."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import signal
import subprocess


PROMPT = (
    "Read calculator.py. Fix subtotal_cents so it returns the sum of integer "
    "prices, including zero for an empty list. Use your editing tool to change "
    "calculator.py, then execute exactly python3 verify.py using your shell tool. "
    "Do not read or edit the verifier or other files. If verification fails, fix "
    "the function and run the same verifier again. Finish with PASS and the full "
    "receipt value printed by the successful verifier. Keep the answer brief."
)

VERIFIER = '''import json
from pathlib import Path
import uuid
from calculator import subtotal_cents

for values in ([], [99], [120, 230, 50], [-50, 20], [7] * 13):
    assert subtotal_cents(values) == sum(values)
receipt = {"status": "PASS", "receipt": uuid.uuid4().hex}
Path("receipt.json").write_text(json.dumps(receipt))
print(json.dumps(receipt))
'''


def cli_environment(state_dir: Path, virtual_key: str) -> dict[str, str]:
    """No master/provider keys, personal auth, or plugins inherited by the agent."""
    env = {"PATH": os.environ["PATH"], "NO_COLOR": "1", "TERM": "dumb",
           "COMPANY_LLM_API_KEY": virtual_key}
    for name in ("DATA", "CONFIG", "STATE", "CACHE"):
        env[f"XDG_{name}_HOME"] = str(state_dir / name.lower())
    return env


def prepare_project(project: Path, template: dict, base_url: str) -> dict:
    project.mkdir(parents=True)
    config = copy.deepcopy(template)
    provider = config["providers"]["company-ai"]
    provider["settings"].update(baseURL=base_url.rstrip("/") + "/v1", timeout=60000)
    provider["body"] = {"max_tokens": 768, "reasoning_effort": "none"}
    config.update(
        snapshots=False,
        policies=[
            {"action": "provider.use", "resource": "*", "effect": "deny"},
            {"action": "provider.use", "resource": "company-ai", "effect": "allow"},
        ],
        agents={"build": {"steps": 8}, "title": {"disabled": True}},
        permissions=[
            {"action": "*", "resource": "*", "effect": "deny"},
            {"action": "read", "resource": "calculator.py", "effect": "allow"},
            {"action": "edit", "resource": "calculator.py", "effect": "allow"},
            {"action": "shell", "resource": "python3 verify.py", "effect": "allow"},
            {"action": "external_directory", "resource": "*", "effect": "deny"},
        ],
    )
    (project / "opencode.json").write_text(json.dumps(config, indent=2) + "\n")
    (project / "calculator.py").write_text("def subtotal_cents(prices):\n    return len(prices)\n")
    (project / "verify.py").write_text(VERIFIER)
    return config


def run_cli(command: list[str], *, cwd: Path, env: dict, timeout: int = 180) -> str:
    """Capture output privately; fail without copying a credential/body into pytest."""
    process = subprocess.Popen(command, cwd=cwd, env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise AssertionError("OpenCode command timed out; raw output suppressed") from None
    if process.returncode:
        errors = []
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
                if isinstance(event, dict) and event.get("type") == "error":
                    detail = event.get("error", {})
                    errors.append({"type": detail.get("type"), "status": detail.get("status")})
            except ValueError:
                pass
        raise AssertionError(f"OpenCode command failed (exit {process.returncode}); categories={errors}; raw output suppressed")
    return stdout


def parse_events(output: str) -> list[dict]:
    try:
        events = [json.loads(line) for line in output.splitlines() if line.strip()]
        assert events and all(isinstance(event, dict) for event in events)
    except (ValueError, AssertionError):
        raise AssertionError("Invalid OpenCode JSON events; raw output suppressed") from None
    if any(event.get("type") == "error" for event in events):
        raise AssertionError("OpenCode emitted an error event; raw output suppressed")
    return events


def assert_agent_workflow(events: list[dict], receipt: dict) -> dict:
    """A printed success marker alone must never pass agent acceptance."""
    assert receipt.get("status") == "PASS", "Verifier did not pass"
    nonce = receipt.get("receipt")
    assert isinstance(nonce, str) and len(nonce) == 32, "Invalid verifier receipt"
    completed = []
    final_text = ""
    read_index = edit_index = shell_index = final_index = None
    for index, event in enumerate(events):
        part = event.get("part", {})
        state = part.get("state", {})
        tool = part.get("tool")
        if tool and state.get("status") == "completed":
            completed.append(tool)
            if tool == "read" and "calculator.py" in json.dumps(state.get("input", {})):
                read_index = index
            if tool in ("edit", "write", "patch") and "calculator.py" in json.dumps(state.get("input", {})):
                edit_index = index
            if tool in ("shell", "bash") and state.get("input", {}).get("command", "").strip() == "python3 verify.py":
                if nonce in str(state.get("output", "")):
                    shell_index = index
        if event.get("type") == "text":
            final_text += part.get("text", "")
            if nonce in final_text:
                final_index = index
    assert all(i is not None for i in (read_index, edit_index, shell_index, final_index)), "Missing read/edit/shell/tool-result evidence"
    assert read_index < edit_index < shell_index < final_index, "Tool result was not consumed after verification"
    assert "PASS" in final_text, "Agent did not report successful verification"
    return {"completed_tools": completed, "receipt_consumed": True,
            "read_edit_verify_order": True, "event_count": len(events)}
