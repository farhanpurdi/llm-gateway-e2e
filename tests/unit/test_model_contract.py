"""Offline checks of the same assertion used by the live /v1/models test."""
from types import SimpleNamespace

import pytest

from tests.test_models import test_user_can_see_expected_models as check_exposed_models


@pytest.mark.unit
@pytest.mark.parametrize("ids", [
    ["company-fast", "company-coding"],
    ["company-coding", "company-fast"],
])
def test_exact_model_exposure_accepts_both_approved_aliases(ids):
    response = SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": name} for name in ids]})
    client = SimpleNamespace(get=lambda _path: response)
    check_exposed_models(client, "company-fast", "company-coding")


@pytest.mark.unit
@pytest.mark.parametrize("ids", [
    ["company-fast"],
    ["company-fast", "company-coding", "extra"],
    ["company-fast", "company-coding", "company-fast"],
    ["company-fast", "openai/gpt-5.6-sol"],
    [],
])
def test_exact_model_exposure_rejects_incomplete_or_extra_aliases(ids):
    response = SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": name} for name in ids]})
    client = SimpleNamespace(get=lambda _path: response)
    with pytest.raises(AssertionError):
        check_exposed_models(client, "company-fast", "company-coding")
