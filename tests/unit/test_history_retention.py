from copy import deepcopy
from unittest.mock import Mock

import pytest

from tests.test_lifecycle import (
    test_user_offboarding_blocks_all_keys as assert_lifecycle,
)


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("mutation", "message"), [
    (None, None),
    ("missing-request", "Historical requests disappeared"),
    ("api_key", "Historical key/user/team attribution changed"),
    ("user", "Historical key/user/team attribution changed"),
    ("team_id", "Historical key/user/team attribution changed"),
    ("spend", "Historical request spend changed"),
], ids=["intact", "missing-request", "changed-key", "changed-user",
        "changed-team", "changed-spend"])
def test_lifecycle_assertions_detect_history_regression(
    offline_client, json_response, mutation, message,
):
    identity = {
        "user_id": "unit-user", "team_id": "unit-team",
        "keys": {
            usage: {"key_alias": usage}
            for usage in ("developer-laptop", "developer-ci")
        },
    }
    keys = [
        {
            "token": f"unit-token-{index}", "key_alias": usage,
            "user_id": identity["user_id"], "team_id": identity["team_id"],
            "spend": 0.01, "blocked": False,
        }
        for index, usage in enumerate(identity["keys"])
    ]
    blocked = [{**key, "blocked": True} for key in keys]
    before = [
        {
            "request_id": f"request-{index}", "api_key": key["token"],
            "user": identity["user_id"], "team_id": identity["team_id"],
            "spend": 0.01,
        }
        for index, key in enumerate(keys)
    ]
    after = deepcopy(before)
    if mutation == "missing-request":
        after.pop()
    elif mutation:
        after[0][mutation] = 0.005 if mutation == "spend" else "changed"

    admin = offline_client
    # Initial discovery, spend baseline, helper discovery, status, retention.
    admin.list_user_keys = Mock(side_effect=[keys, keys, keys, blocked, blocked])
    admin.post.side_effect = [json_response(key) for key in blocked]
    admin.get.side_effect = [
        json_response({"user_info": {"user_id": identity["user_id"], "spend": 0.02}})
        for _ in range(2)
    ]
    admin.list_user_spend_logs_page = Mock(side_effect=[
        {"data": before, "total": len(before), "total_is_capped": False},
        {"data": after, "total": len(after), "total_is_capped": False},
    ])
    clients = {}
    for usage in identity["keys"]:
        client = Mock()
        client.post.side_effect = [
            json_response({"choices": [{"message": {"content": "ok"}}]}),
            json_response({}, 401),
        ]
        clients[usage] = client

    # Exercise the actual H9D assertions; do not duplicate their logic here.
    if message:
        with pytest.raises(AssertionError, match=message):
            assert_lifecycle(admin, identity, clients, "company-fast")
    else:
        assert_lifecycle(admin, identity, clients, "company-fast")

    assert admin.post.call_count == 2
    assert all(client.post.call_count == 2 for client in clients.values())
