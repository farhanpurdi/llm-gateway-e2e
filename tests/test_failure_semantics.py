"""Gateway rejects dangerous simulation parameters; the same key still works."""
import json
import time

import pytest


FAULTS = {
    "rate_limit": ({"mock_testing_rate_limit_error": True}, 400),
    "server_error": ({"mock_testing_fallbacks": True}, 400),
    "timeout": ({"mock_timeout": True, "mock_response": "unused",
                 "timeout": 0.05, "request_timeout": 0.05}, 400),
}


@pytest.mark.live
@pytest.mark.parametrize("alias", ["company-fast", "company-coding"])
@pytest.mark.parametrize("fault", list(FAULTS))
def test_fault_injection_parameters_are_rejected(pilot_identity_factory, alias, fault):
    ctx = pilot_identity_factory(prefix="e2e-p113-", purpose="P1-13-native-fault")
    client = ctx["keys"][0]["client"]
    injection, expected_status = FAULTS[fault]
    started = time.monotonic()
    response = client.post("/v1/chat/completions", json={
        "model": alias, "messages": [{"role": "user", "content": "Controlled fault test."}],
        "max_tokens": 8, "num_retries": 0, "disable_fallbacks": True, **injection,
    })
    elapsed = time.monotonic() - started
    assert response.status_code == expected_status, f"Dangerous {fault} parameter was not rejected: HTTP {response.status_code}"
    error = response.json().get("error")
    assert isinstance(error, dict), "Expected OpenAI-compatible error object"
    assert isinstance(error.get("message"), str) and error["message"], "Missing error message"
    assert "mock" in error["message"].lower(), "Request was rejected for an unrelated reason"
    assert isinstance(error.get("type"), str) and error["type"], "Missing error type"
    assert "choices" not in response.json(), "A failed request must not look successful"
    assert elapsed < 30, "Fault request exceeded the bounded scenario"
    # Removing request-local injection must restore real inference on the same credential.
    recovery = client.post("/v1/chat/completions", json={
        "model": alias, "messages": [{"role": "user", "content": "Reply exactly: ok"}],
        "max_tokens": 16, "reasoning_effort": "none",
    })
    assert recovery.status_code == 200, f"Recovery failed: HTTP {recovery.status_code}"
    body = recovery.json()
    assert "ok" in body["choices"][0]["message"]["content"].lower()
    assert body["usage"]["completion_tokens"] > 0
    print("P1_NATIVE_FAULT " + json.dumps({
        "alias": alias, "fault": fault, "status": response.status_code,
        "elapsed_seconds": round(elapsed, 3), "recovery_status": recovery.status_code,
        "error_type": error["type"], "simulation": "rejected-by-runtime-security-guard",
    }))
