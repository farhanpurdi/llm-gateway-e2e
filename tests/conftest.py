from __future__ import annotations

import os
import uuid

import pytest

from tests.client import LiteLLMClient


def required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Required environment variable is missing: {name}"
        )

    return value


@pytest.fixture(scope="session")
def base_url() -> str:
    return required_env("LITELLM_BASE_URL")


@pytest.fixture(scope="session")
def master_key() -> str:
    return required_env("LITELLM_MASTER_KEY")


@pytest.fixture(scope="session")
def fast_model() -> str:
    return os.getenv(
        "E2E_FAST_MODEL",
        "company-fast",
    )


@pytest.fixture(scope="session")
def coding_model() -> str:
    return os.getenv(
        "E2E_CODING_MODEL",
        "company-coding",
    )


@pytest.fixture(scope="session")
def admin_client(
    base_url: str,
    master_key: str,
) -> LiteLLMClient:
    return LiteLLMClient(
        base_url=base_url,
        api_key=master_key,
    )


@pytest.fixture()
def e2e_identity(
    admin_client: LiteLLMClient,
    fast_model: str,
    coding_model: str,
):
    suffix = uuid.uuid4().hex[:8]

    user_id = f"e2e-user-{suffix}"
    team_alias = f"e2e-team-{suffix}"
    key_alias = f"e2e-key-{suffix}"

    #
    # 1. User
    #

    response = admin_client.post(
        "/user/new",
        json={
            "user_id": user_id,
            "user_role": "internal_user",
            "auto_create_key": False,
        },
    )

    admin_client.expect_json(response)

    #
    # 2. Team
    #

    response = admin_client.post(
        "/team/new",
        json={
            "team_alias": team_alias,
            "models": [
                fast_model,
                coding_model,
            ],
            "max_budget": 1,
            "budget_duration": "30d",
            "rpm_limit": 30,
            "tpm_limit": 50000,
            "metadata": {
                "environment": "e2e",
                "managed_by": "pytest",
            },
        },
    )

    team_data = admin_client.expect_json(response)

    team_id = team_data["team_id"]

    #
    # 3. Membership
    #

    response = admin_client.post(
        "/team/member_add",
        json={
            "team_id": team_id,
            "max_budget_in_team": 0.50,
            "member": {
                "role": "user",
                "user_id": user_id,
            },
        },
    )

    admin_client.expect_json(response)

    #
    # 4. Virtual Key
    #

    response = admin_client.post(
        "/key/generate",
        json={
            "user_id": user_id,
            "team_id": team_id,
            "key_alias": key_alias,
            "models": [
                "all-team-models",
            ],
            "metadata": {
                "environment": "e2e",
                "purpose": "automated-test",
            },
        },
    )

    key_data = admin_client.expect_json(response)

    virtual_key = key_data["key"]

    context = {
        "user_id": user_id,
        "team_id": team_id,
        "team_alias": team_alias,
        "key_alias": key_alias,
        "virtual_key": virtual_key,
    }

    yield context

    #
    # Cleanup
    #
    # Jangan print key.
    #

    try:
        admin_client.post(
            "/key/block",
            json={
                "key": virtual_key,
            },
        )
    finally:
        #
        # Buat team hasil test inert.
        #
        admin_client.post(
            "/team/update",
            json={
                "team_id": team_id,
                "blocked": True,
            },
        )


@pytest.fixture()
def user_client(
    base_url: str,
    e2e_identity: dict,
) -> LiteLLMClient:
    return LiteLLMClient(
        base_url=base_url,
        api_key=e2e_identity["virtual_key"],
    )