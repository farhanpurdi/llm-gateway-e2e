import requests


def test_litellm_is_alive(
    base_url: str,
):
    response = requests.get(
        f"{base_url}/health/liveliness",
        timeout=10,
    )

    assert response.status_code == 200