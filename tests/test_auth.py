from tests.client import LiteLLMClient


def test_invalid_key_is_rejected(
    base_url,
    fast_model,
):
    client = LiteLLMClient(
        base_url=base_url,
        api_key="sk-invalid-e2e-key",
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": fast_model,
            "messages": [
                {
                    "role": "user",
                    "content": "This request must not reach the provider.",
                }
            ],
        },
    )

    assert response.status_code in {
        401,
        403,
    }