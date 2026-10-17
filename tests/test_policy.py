import pytest


@pytest.mark.live
@pytest.mark.policy
def test_team_policy_changes_without_key_rotation(
    admin_client,
    user_client,
    e2e_identity,
    fast_model,
    coding_model,
):
    team_id = e2e_identity["team_id"]

    #
    # Sanity check:
    # company-fast allowed
    #

    response = user_client.post(
        "/v1/chat/completions",
        json={
            "model": fast_model,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with POLICY_FAST_OK",
                }
            ],
        },
    )

    assert response.status_code == 200

    try:
        #
        # Remove coding permission
        #

        response = admin_client.post(
            "/team/update",
            json={
                "team_id": team_id,
                "models": [
                    fast_model,
                ],
            },
        )

        assert response.status_code == 200

        #
        # SAME virtual key.
        #
        # Coding must now fail.
        #

        response = user_client.post(
            "/v1/chat/completions",
            json={
                "model": coding_model,
                "messages": [
                    {
                        "role": "user",
                        "content": "THIS MUST NOT RUN",
                    }
                ],
            },
        )

        assert response.status_code == 403

    finally:
        #
        # Always restore team policy,
        # even if an assertion fails.
        #

        admin_client.post(
            "/team/update",
            json={
                "team_id": team_id,
                "models": [
                    fast_model,
                    coding_model,
                ],
            },
        )

    #
    # Same key should work again.
    #

    response = user_client.post(
        "/v1/chat/completions",
        json={
            "model": coding_model,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with POLICY_RESTORED_OK",
                }
            ],
        },
    )

    assert response.status_code == 200