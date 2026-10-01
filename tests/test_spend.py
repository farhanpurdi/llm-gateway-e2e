import time

import pytest


@pytest.mark.live
@pytest.mark.spend
def test_spend_is_attributed_to_user(
    admin_client,
    user_client,
    e2e_identity,
    fast_model,
):
    user_id = e2e_identity["user_id"]

    #
    # Generate some spend
    #

    response = user_client.post(
        "/v1/chat/completions",
        json={
            "model": fast_model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Reply exactly with "
                        "SPEND_TEST_OK"
                    ),
                }
            ],
        },
    )

    assert response.status_code == 200

    #
    # LiteLLM spend logging can be asynchronous.
    #

    deadline = time.time() + 20

    spend = 0.0

    while time.time() < deadline:
        response = admin_client.get(
            "/user/info",
            params={
                "user_id": user_id,
            },
        )

        assert response.status_code == 200

        data = response.json()

        spend = (
            data
            .get("user_info", {})
            .get("spend", 0)
            or 0
        )

        if spend > 0:
            break

        time.sleep(1)

    assert spend > 0