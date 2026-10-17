from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import yaml

import pytest

from tests.client import LiteLLMClient, RedactedKey
from tests.opencode import cli_environment, prepare_project
from tests.maintenance import stopped_dependency


@pytest.fixture()
def dependency_outage(base_url):
    """Mechanical stop/recovery is paired even when a request assertion fails."""
    return lambda dependency: stopped_dependency(dependency, base_url)


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
def identity_cleanup(admin_client):
    """Register immediately after team creation; teardown also covers failed setup."""
    registered = []
    yield lambda team_id, user_id: registered.append((team_id, user_id))
    errors = []
    for team_id, user_id in registered:
        try:
            admin_client.offboard_user_keys(user_id=user_id)
            if any(item.get("blocked") is not True for item in admin_client.list_user_keys(user_id=user_id)):
                errors.append("unblocked fixture key remains")
        except Exception as error:
            errors.append("key cleanup: " + type(error).__name__)
        try:
            admin_client.expect_json(admin_client.post(
                "/team/update", json={"team_id": team_id, "blocked": True}))
            if admin_client.team_info(team_id)["team_info"].get("blocked") is not True:
                errors.append("team cleanup not confirmed")
        except Exception as error:
            errors.append("team cleanup: " + type(error).__name__)
    if errors:
        pytest.fail("Fixture cleanup failed: " + "; ".join(errors), pytrace=False)


@pytest.fixture()
def e2e_identity(
    admin_client: LiteLLMClient,
    fast_model: str,
    coding_model: str,
    identity_cleanup,
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
    identity_cleanup(team_id, user_id)

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

    virtual_key = RedactedKey(key_data["key"])

    context = {
        "user_id": user_id,
        "team_id": team_id,
        "team_alias": team_alias,
        "key_alias": key_alias,
        "virtual_key": virtual_key,
    }

    yield context


@pytest.fixture()
def user_client(
    base_url: str,
    e2e_identity: dict,
) -> LiteLLMClient:
    return LiteLLMClient(
        base_url=base_url,
        api_key=e2e_identity["virtual_key"],
    )


@pytest.fixture()
def rpm_limited_identity(
    admin_client: LiteLLMClient,
    fast_model: str,
    identity_cleanup,
):
    suffix = uuid.uuid4().hex[:8]

    user_id = f"e2e-rpm-user-{suffix}"
    team_alias = f"e2e-rpm-team-{suffix}"
    key_alias = f"e2e-rpm-key-{suffix}"

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
    # 2. RPM-limited Team
    #

    team_data = admin_client.create_team(
        team_alias=team_alias,
        models=[
            fast_model,
        ],
        rpm_limit=2,
        tpm_limit=50000,
    )

    team_id = team_data["team_id"]
    identity_cleanup(team_id, user_id)

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
    # Penting:
    # jangan set rpm_limit/tpm_limit pada key.
    # Kita ingin membuktikan TEAM limit yang bekerja.
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
                "purpose": "rpm-enforcement-test",
            },
        },
    )

    key_data = admin_client.expect_json(response)

    virtual_key = RedactedKey(key_data["key"])

    context = {
        "user_id": user_id,
        "team_id": team_id,
        "team_alias": team_alias,
        "key_alias": key_alias,
        "virtual_key": virtual_key,
        "rpm_limit": 2,
        "tpm_limit": 50000,
    }

    #
    # Test berjalan di sini.
    #

    yield context


@pytest.fixture()
def rpm_user_client(
    base_url: str,
    rpm_limited_identity: dict,
) -> LiteLLMClient:
    return LiteLLMClient(
        base_url=base_url,
        api_key=rpm_limited_identity["virtual_key"],
    )


@pytest.fixture()
def budget_limited_identity(
    admin_client: LiteLLMClient,
    fast_model: str,
    identity_cleanup,
):
    suffix = uuid.uuid4().hex[:8]

    user_id = f"e2e-budget-user-{suffix}"
    team_alias = f"e2e-budget-team-{suffix}"
    key_alias = f"e2e-budget-key-{suffix}"

    key_max_budget = 0.000001

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
    # Team budget intentionally much larger
    # than the key budget.
    #

    team_data = admin_client.create_team(
        team_alias=team_alias,
        models=[
            fast_model,
        ],
        max_budget=1,
        budget_duration="30d",
    )

    team_id = team_data["team_id"]
    identity_cleanup(team_id, user_id)

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
    # Only this key has the tiny budget.
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
            "max_budget": key_max_budget,
            "budget_duration": "1h",
            "metadata": {
                "environment": "e2e",
                "purpose": "budget-enforcement-test",
            },
        },
    )

    key_data = admin_client.expect_json(response)

    virtual_key = RedactedKey(key_data["key"])

    context = {
        "user_id": user_id,
        "team_id": team_id,
        "team_alias": team_alias,
        "key_alias": key_alias,
        "virtual_key": virtual_key,
        "max_budget": key_max_budget,
    }

    yield context


@pytest.fixture()
def budget_user_client(
    base_url: str,
    budget_limited_identity: dict,
) -> LiteLLMClient:
    return LiteLLMClient(
        base_url=base_url,
        api_key=budget_limited_identity["virtual_key"],
    )


@pytest.fixture()
def multi_key_identity(
    admin_client: LiteLLMClient,
    fast_model: str,
    coding_model: str,
):
    suffix = uuid.uuid4().hex[:8]

    user_id = f"e2e-lifecycle-user-{suffix}"
    team_alias = f"e2e-lifecycle-team-{suffix}"

    team_id = None
    keys = {}

    try:
        # 1. Buat user tanpa otomatis membuat key.
        response = admin_client.post(
            "/user/new",
            json={
                "user_id": user_id,
                "user_role": "internal_user",
                "auto_create_key": False,
            },
        )

        admin_client.expect_json(response)

        # 2. Buat team khusus untuk pengujian ini.
        team_data = admin_client.create_team(
            team_alias=team_alias,
            models=[fast_model, coding_model],
            max_budget=1,
            budget_duration="30d",
            rpm_limit=30,
            tpm_limit=50000,
        )

        team_id = team_data["team_id"]

        # 3. Hubungkan user ke team.
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

        # 4. Buat key untuk masing-masing penggunaan.
        for usage in ("developer-laptop", "developer-ci"):
            key_alias = f"e2e-{usage}-{suffix}"

            response = admin_client.post(
                "/key/generate",
                json={
                    "user_id": user_id,
                    "team_id": team_id,
                    "key_alias": key_alias,
                    "models": ["all-team-models"],
                    "metadata": {
                        "environment": "e2e",
                        "purpose": "lifecycle-test",
                        "usage": usage,
                    },
                },
            )

            if response.status_code != 200:
                raise AssertionError(
                    f"Key provisioning failed for {key_alias}: "
                    f"HTTP {response.status_code}"
                )

            virtual_key = response.json().get("key")

            if not isinstance(virtual_key, str) or not virtual_key:
                raise AssertionError(
                    f"No virtual key returned for {key_alias}"
                )

            keys[usage] = {
                "key_alias": key_alias,
                "virtual_key": virtual_key,
            }

        yield {
            "user_id": user_id,
            "team_id": team_id,
            "team_alias": team_alias,
            "keys": keys,
        }

    finally:
        cleanup_errors = []

        for key_data in keys.values():
            key_alias = key_data["key_alias"]

            try:
                response = admin_client.post(
                    "/key/block",
                    json={
                        "key": key_data["virtual_key"],
                    },
                )

                if response.status_code != 200:
                    cleanup_errors.append(
                        f"Block {key_alias}: HTTP {response.status_code}"
                    )

            except Exception as exc:
                cleanup_errors.append(
                    f"Block {key_alias}: {type(exc).__name__}"
                )

        if team_id is not None:
            try:
                response = admin_client.post(
                    "/team/update",
                    json={
                        "team_id": team_id,
                        "blocked": True,
                    },
                )

                if response.status_code != 200:
                    cleanup_errors.append(
                        f"Block team: HTTP {response.status_code}"
                    )

            except Exception as exc:
                cleanup_errors.append(
                    f"Block team: {type(exc).__name__}"
                )

        if cleanup_errors:
            pytest.fail(
                "Lifecycle cleanup failed: "
                + "; ".join(cleanup_errors),
                pytrace=False,
            )


@pytest.fixture()
def multi_key_clients(
    base_url: str,
    multi_key_identity: dict,
) -> dict[str, LiteLLMClient]:
    clients = {}

    for usage, key_data in multi_key_identity["keys"].items():
        clients[usage] = LiteLLMClient(
            base_url=base_url,
            api_key=key_data["virtual_key"],
        )

    return clients


@pytest.fixture(scope='session')
def pilot_policy():
    path = Path(__file__).resolve().parents[2] / 'llm-gateway-config/policies/teams/pilot.yaml'
    policy = yaml.safe_load(path.read_text())
    assert policy['name'] == 'pilot'
    assert policy['models'] == ['company-fast', 'company-coding']
    return policy


@pytest.fixture()
def pilot_identity_factory(admin_client, base_url, pilot_policy):
    """Only disposable identities; the approved policy file and existing teams stay intact."""
    created = []

    def create(*, team_limits=None, member_budget='policy', member_duration='30d',
               first_key_budget=None, prefix='e2e-p109-', purpose='P1-09-P1-10'):
        limits = {**pilot_policy['limits']['team'], **(team_limits or {})}
        budget = (pilot_policy['limits']['member']['monthly_budget_usd']
                  if member_budget == 'policy' else member_budget)
        suffix = uuid.uuid4().hex[:8]
        team = admin_client.expect_json(admin_client.post('/team/new', json={
            'team_alias': prefix+suffix, 'models': pilot_policy['models'],
            'max_budget': limits['monthly_budget_usd'], 'budget_duration': '30d',
            'rpm_limit': limits['rpm'], 'tpm_limit': limits['tpm'],
            'metadata': {'environment': 'e2e', 'purpose': purpose, 'policy': 'pilot'},
        }))
        ctx = {'team_id': team['team_id'], 'users': [], 'keys': []}
        created.append(ctx)  # Register immediately so partial provisioning is cleaned up.
        for user_number in range(2):
            uid = f'{prefix}{suffix}-{user_number}'
            admin_client.expect_json(admin_client.post('/user/new', json={
                'user_id': uid, 'user_role': 'internal_user', 'auto_create_key': False,
            }))
            member = {'team_id': ctx['team_id'], 'member': {'role': 'user', 'user_id': uid}}
            if budget is not None:
                member.update(max_budget_in_team=budget, budget_duration=member_duration)
            admin_client.expect_json(admin_client.post('/team/member_add', json=member))
            ctx['users'].append(uid)
            for key_number in range(2):
                payload = {'team_id': ctx['team_id'], 'user_id': uid,
                           'key_alias': f'{prefix}{suffix}-{user_number}-{key_number}',
                           'models': ['all-team-models'],
                           'metadata': {'environment': 'e2e', 'purpose': purpose}}
                if first_key_budget is not None and user_number == key_number == 0:
                    payload.update(max_budget=first_key_budget, budget_duration='30d')
                data = admin_client.expect_json(admin_client.post('/key/generate', json=payload))
                ctx['keys'].append({'virtual_key': RedactedKey(data['key']), 'user_id': uid,
                                    'client': LiteLLMClient(base_url, data['key'])})
        return ctx

    try:
        yield create
    finally:
        errors = []
        for ctx in created:
            for key in ctx['keys']:
                try:
                    data = admin_client.expect_json(admin_client.post(
                        '/key/block', json={'key': key['virtual_key']}))
                    if data.get('blocked') is not True:
                        errors.append('key block not confirmed')
                except Exception as exc:
                    errors.append('key cleanup: '+type(exc).__name__)
            try:
                data = admin_client.expect_json(admin_client.post('/team/update', json={
                    'team_id': ctx['team_id'], 'blocked': True}))
                if admin_client.team_info(ctx['team_id'])['team_info'].get('blocked') is not True:
                    errors.append('team block not confirmed')
            except Exception as exc:
                errors.append('team cleanup: '+type(exc).__name__)
        if errors:
            pytest.fail('Pilot fixture cleanup failed: '+'; '.join(errors), pytrace=False)


@pytest.fixture(scope="module")
def opencode_developer(admin_client, base_url, pilot_policy):
    """Exercise the real operator onboarding script, including partial-failure cleanup."""
    workspace = Path(__file__).resolve().parents[2]
    suffix = uuid.uuid4().hex[:8]
    user_id = f"e2e-p1112-{suffix}"
    team_id = None
    try:
        limits = pilot_policy["limits"]["team"]
        team_id = admin_client.create_team(
            team_alias=user_id, models=pilot_policy["models"],
            rpm_limit=limits["rpm"], tpm_limit=limits["tpm"],
            max_budget=limits["monthly_budget_usd"], budget_duration="30d",
        )["team_id"]
        env = dict(os.environ)
        env["LLM_GATEWAY_ENV_FILE"] = os.getenv(
            "E2E_ENV_FILE", str(workspace / "llm-gateway-infra/.env"))
        result = subprocess.run(
            ["bash", str(workspace / "llm-gateway-infra/scripts/onboard-developer.sh"),
             user_id, team_id, "pilot"],
            env=env, capture_output=True, text=True, timeout=200, check=False,
        )
        if result.returncode:
            pytest.fail(f"Operator onboarding failed (exit {result.returncode}); output suppressed", pytrace=False)
        candidates = re.findall(r"^sk-[A-Za-z0-9_-]+$", result.stdout, re.MULTILINE)
        if len(candidates) != 1:
            pytest.fail("Onboarding did not return exactly one virtual key; output suppressed", pytrace=False)
        key = RedactedKey(candidates[0])
        yield {"team_id": team_id, "user_id": user_id, "virtual_key": key,
               "client": LiteLLMClient(base_url, key)}
    finally:
        if team_id:
            errors = []
            try:
                summary = admin_client.offboard_user_keys(user_id=user_id)
                # Re-discovery confirms no unblocked key was left by a partial CLI run.
                keys = admin_client.list_user_keys(user_id=user_id)
                if any(item.get("blocked") is not True for item in keys):
                    errors.append("unblocked developer key remains")
                print("P1_OPENCODE_CLEANUP " + json.dumps(summary))
            except Exception as exc:
                errors.append("developer key cleanup: " + type(exc).__name__)
            try:
                admin_client.expect_json(admin_client.post(
                    "/team/update", json={"team_id": team_id, "blocked": True}))
                if admin_client.team_info(team_id)["team_info"].get("blocked") is not True:
                    errors.append("team block not confirmed")
            except Exception as exc:
                errors.append("team cleanup: " + type(exc).__name__)
            if errors:
                pytest.fail("OpenCode fixture cleanup failed: " + "; ".join(errors), pytrace=False)


@pytest.fixture()
def opencode_project(tmp_path, opencode_developer, base_url):
    executable = shutil.which("opencode")
    if not executable:
        pytest.fail("Existing OpenCode CLI is required for agent acceptance", pytrace=False)
    template_path = Path(__file__).resolve().parents[2] / "llm-gateway-config/clients/opencode/opencode.jsonc"
    template = json.loads(template_path.read_text())
    project = tmp_path / "project"
    prepare_project(project, template, base_url)
    return {"path": project, "executable": executable,
            "env": cli_environment(tmp_path / "cli-state", opencode_developer["virtual_key"])}
