import json
from unittest.mock import Mock

import pytest
import requests

from tests.client import LiteLLMClient


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Unit tests must not send HTTP requests")

    monkeypatch.setattr(requests.sessions.Session, "request", reject)


@pytest.fixture()
def json_response():
    def make(data, status=200):
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(data).encode("utf-8")
        return response

    return make


@pytest.fixture()
def offline_client():
    client = LiteLLMClient("http://unused.invalid", "unit-placeholder")
    client.get = Mock(side_effect=AssertionError("Unexpected GET"))
    client.post = Mock(side_effect=AssertionError("Unexpected POST"))
    return client
