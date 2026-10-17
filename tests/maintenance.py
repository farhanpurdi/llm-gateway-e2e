"""Bounded maintenance of existing dependencies; never creates a container."""
from contextlib import contextmanager
import json
import os
import subprocess
import time
from urllib.parse import urlsplit


DEPENDENCIES = {"postgres": "llm-gateway-postgres", "redis": "llm-gateway-redis"}


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Existing-container operation failed; raw output suppressed")
    return result.stdout.strip()


def inspect(name):
    data = json.loads(docker("inspect", "--format", "{{json .}}", name))
    return {"id": data["Id"], "running": data["State"]["Running"]}


@contextmanager
def stopped_dependency(dependency, base_url):
    url = urlsplit(base_url)
    if os.getenv("E2E_ALLOW_EXISTING_OUTAGE") != "1":
        raise RuntimeError("Use the explicit existing-maintenance runner for outage tests")
    if url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.port != 4000:
        raise RuntimeError("Maintenance is restricted to the existing local gateway4000")
    if dependency not in DEPENDENCIES:
        raise RuntimeError("Unsupported dependency")
    name = DEPENDENCIES[dependency]
    gateway = inspect("llm-gateway")
    before = inspect(name)
    if not gateway["running"] or not before["running"]:
        raise RuntimeError("Gateway and dependency must already be running")
    started = time.monotonic()
    try:
        docker("stop", "--time", "5", name)
        assert inspect(name)["running"] is False, "Dependency did not stop"
        yield
    finally:
        docker("start", name)
        deadline = time.monotonic() + 60
        recovered = False
        while time.monotonic() < deadline:
            state = inspect(name)
            try:
                if dependency == "postgres":
                    ready = docker("exec", name, "pg_isready")
                    recovered = "accepting connections" in ready
                else:
                    recovered = docker("exec", name, "redis-cli", "ping") == "PONG"
            except RuntimeError:
                recovered = False
            if recovered:
                break
            time.sleep(1)
        assert recovered, "Dependency did not recover"
        assert state["id"] == before["id"], "Dependency identity changed"
        assert inspect("llm-gateway") == gateway, "Gateway identity/state changed"
        print("P1_OUTAGE_RECOVERY " + json.dumps({"dependency": dependency, "recovered": True,
              "same_container_ids": True, "seconds": round(time.monotonic() - started, 2)}))
