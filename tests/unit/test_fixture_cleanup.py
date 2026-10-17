from unittest.mock import Mock

import pytest

from tests.conftest import identity_cleanup


pytestmark = pytest.mark.unit


def configured_client(offline_client, json_response):
    offline_client.offboard_user_keys = Mock(return_value={"blocked_count": 1})
    offline_client.list_user_keys = Mock(return_value=[{"blocked": True}])
    offline_client.post.side_effect = None
    offline_client.post.return_value = json_response({"ok": True})
    offline_client.team_info = Mock(return_value={"team_info": {"blocked": True}})
    return offline_client


def test_cleanup_runs_for_identity_registered_before_setup_failure(offline_client, json_response):
    client = configured_client(offline_client, json_response)
    teardown = identity_cleanup.__wrapped__(client)
    register = next(teardown)
    register("fixture-team", "fixture-user")
    # Owner fixture may fail after registration and before yielding a virtual key.
    with pytest.raises(StopIteration):
        next(teardown)
    client.offboard_user_keys.assert_called_once_with(user_id="fixture-user")
    client.post.assert_called_once_with("/team/update", json={"team_id": "fixture-team", "blocked": True})


@pytest.mark.parametrize("fault", ["offboard-error", "key-not-blocked", "team-not-blocked", "team-http-error"])
def test_cleanup_failure_is_visible_and_preserves_team_attempt(offline_client, json_response, fault):
    client = configured_client(offline_client, json_response)
    if fault == "offboard-error":
        client.offboard_user_keys.side_effect = RuntimeError("private-unit-placeholder")
    elif fault == "key-not-blocked":
        client.list_user_keys.return_value = [{"blocked": False}]
    elif fault == "team-not-blocked":
        client.team_info.return_value = {"team_info": {"blocked": False}}
    else:
        client.post.return_value = json_response({"detail": "private-unit-placeholder"}, status=500)
    teardown = identity_cleanup.__wrapped__(client)
    next(teardown)("fixture-team", "fixture-user")
    with pytest.raises(pytest.fail.Exception) as error:
        next(teardown)
    assert "private-unit-placeholder" not in str(error.value)
    assert client.post.call_count == 1
