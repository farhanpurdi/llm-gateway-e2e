import pytest
import requests

from tests.client import GatewayTransportError, LiteLLMClient


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("exception", [requests.Timeout, requests.ConnectionError])
def test_transport_errors_suppress_credential_urls_and_bodies(monkeypatch, method, exception):
    value = "private-unit-credential-not-issued"

    def fail(*args, **kwargs):
        raise exception(f"http://gateway/key/info?key={value}; response body={value}")

    monkeypatch.setattr(requests, method, fail)
    client = LiteLLMClient("http://unused.invalid", value)
    with pytest.raises(GatewayTransportError) as error:
        getattr(client, method)("/key/info")
    assert value not in str(error.value)
    assert exception.__name__ in str(error.value)
    assert error.value.__suppress_context__ is True


def test_header_repr_hides_key_without_changing_http_value():
    value = "private-unit-credential-not-issued"
    client = LiteLLMClient("http://unused.invalid", value)
    assert client.headers["Authorization"] == "Bearer " + value
    assert value not in repr(client.headers)
