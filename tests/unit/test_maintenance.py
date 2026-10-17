import json

import pytest

from tests import maintenance


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("dependency", ["postgres", "redis"])
def test_dependency_is_restored_after_test_assertion_fails(monkeypatch, dependency):
    monkeypatch.setenv("E2E_ALLOW_EXISTING_OUTAGE", "1")
    name = maintenance.DEPENDENCIES[dependency]
    running = {"llm-gateway": True, name: True}
    calls = []

    def docker(*args):
        calls.append(args)
        if args[0] == "inspect":
            target = args[-1]
            return json.dumps({"Id": "existing-" + target, "State": {"Running": running[target]}})
        if args[0] == "stop":
            running[name] = False
        elif args[0] == "start":
            running[name] = True
        elif args[0] == "exec":
            return "accepting connections" if dependency == "postgres" else "PONG"
        return ""

    monkeypatch.setattr(maintenance, "docker", docker)
    with pytest.raises(AssertionError, match="intentional unit assertion"):
        with maintenance.stopped_dependency(dependency, "http://localhost:4000"):
            assert running[name] is False
            raise AssertionError("intentional unit assertion")
    assert running[name] is True
    assert sum(call[0] == "stop" for call in calls) == 1
    assert sum(call[0] == "start" for call in calls) == 1


@pytest.mark.parametrize("base_url,enabled", [
    ("http://localhost:4000", False),
    ("https://external.invalid:4000", True),
    ("http://localhost:4001", True),
])
def test_maintenance_refuses_unapproved_or_remote_target(monkeypatch, base_url, enabled):
    monkeypatch.setenv("E2E_ALLOW_EXISTING_OUTAGE", "1" if enabled else "0")
    calls = []
    monkeypatch.setattr(maintenance, "docker", lambda *args: calls.append(args))
    with pytest.raises(RuntimeError):
        with maintenance.stopped_dependency("postgres", base_url):
            pytest.fail("Unsafe maintenance target was accepted")
    assert calls == []
