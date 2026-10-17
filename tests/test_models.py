def test_user_can_see_expected_models(
    user_client,
    fast_model,
    coding_model,
):
    response = user_client.get(
        "/v1/models"
    )

    assert response.status_code == 200

    data = response.json()

    model_ids = {
        model["id"]
        for model in data["data"]
    }

    assert model_ids == {fast_model, coding_model}
    assert len(data["data"]) == len(model_ids), "Duplicate logical models exposed"
