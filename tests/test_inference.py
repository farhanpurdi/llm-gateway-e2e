import json

import pytest


@pytest.mark.live
def test_company_fast_inference(
    user_client,
    fast_model,
):
    response = user_client.post(
        "/v1/chat/completions",
        json={
            "model": fast_model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Reply exactly with "
                        "E2E_FAST_OK"
                    ),
                }
            ],
        },
    )

    assert response.status_code == 200

    data = response.json()

    content = (
        data["choices"][0]
        ["message"]
        ["content"]
    )

    assert "E2E_FAST_OK" in content


@pytest.mark.live
def test_company_coding_inference(
    user_client,
    coding_model,
):
    response = user_client.post(
        "/v1/chat/completions",
        json={
            "model": coding_model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Reply exactly with "
                        "E2E_CODING_OK"
                    ),
                }
            ],
        },
    )

    assert response.status_code == 200

    data = response.json()

    content = (
        data["choices"][0]
        ["message"]
        ["content"]
    )

    assert "E2E_CODING_OK" in content


@pytest.mark.live
@pytest.mark.parametrize("model_fixture", ["fast_model", "coding_model"])
def test_streaming(
    user_client,
    request,
    model_fixture,
):
    response = user_client.post(
        "/v1/chat/completions",
        stream=True,
        json={
            "model": request.getfixturevalue(model_fixture),
            "stream": True,
            "max_tokens": 32,
            "reasoning_effort": "none",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Reply exactly with "
                        "E2E_STREAM_OK"
                    ),
                }
            ],
        },
    )

    assert response.status_code == 200

    chunks = []
    done_received = False

    for raw_line in response.iter_lines(
        decode_unicode=True
    ):
        if not raw_line:
            continue

        if not raw_line.startswith("data: "):
            continue

        payload = raw_line[6:]

        if payload == "[DONE]":
            done_received = True
            break

        data = json.loads(payload)

        delta = (
            data
            .get("choices", [{}])[0]
            .get("delta", {})
            .get("content")
        )

        if delta:
            chunks.append(delta)

    content = "".join(chunks)

    assert done_received
    assert "E2E_STREAM_OK" in content

@pytest.mark.live
@pytest.mark.parametrize("model_fixture", ["fast_model", "coding_model"])
def test_tool_calling(user_client, request, model_fixture):
    """Both aliases must preserve structured tool calls needed by coding clients."""
    response = user_client.post(
        "/v1/chat/completions",
        json={
            "model": request.getfixturevalue(model_fixture),
            "messages": [{"role": "user", "content": "Look up the status of ticket TICKET-123."}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "lookup_ticket",
                    "description": "Return the status of a ticket.",
                    "parameters": {
                        "type": "object",
                        "properties": {"ticket_id": {"type": "string"}},
                        "required": ["ticket_id"],
                        "additionalProperties": False,
                    },
                },
            }],
            "tool_choice": {"type": "function", "function": {"name": "lookup_ticket"}},
        },
    )
    assert response.status_code == 200
    calls = response.json()["choices"][0]["message"]["tool_calls"]
    assert len(calls) == 1
    assert calls[0]["id"]
    assert calls[0]["type"] == "function"
    assert calls[0]["function"]["name"] == "lookup_ticket"
    assert json.loads(calls[0]["function"]["arguments"]) == {"ticket_id": "TICKET-123"}
