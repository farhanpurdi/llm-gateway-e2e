from unittest.mock import Mock, call

import pytest


pytestmark = pytest.mark.unit

USER = "unit-user"
KEYS = [
    {"token": "unit-token-a", "user_id": USER},
    {"token": "unit-token-b", "user_id": USER},
]


def page(number, keys, total=2, pages=2):
    return {
        "current_page": number,
        "keys": keys,
        "total_count": total,
        "total_pages": pages,
    }


def test_offboarding_discovers_every_page_before_blocking(
    offline_client, json_response,
):
    client = offline_client
    client.get.side_effect = [
        json_response(page(1, [KEYS[0]])),
        json_response(page(2, [KEYS[1]])),
    ]

    def block(path, *, json):
        assert client.get.call_count == 2
        assert path == "/key/block"
        return json_response({
            "token": json["key"], "user_id": USER, "blocked": True,
        })

    client.post.side_effect = block
    result = client.offboard_user_keys(user_id=USER, page_size=1)

    assert result == {
        "user_id": USER, "discovered_count": 2, "blocked_count": 2,
    }
    assert client.post.call_args_list == [
        call("/key/block", json={"key": key["token"]}) for key in KEYS
    ]
    for number, request in enumerate(client.get.call_args_list, start=1):
        assert request == call("/key/list", params={
            "user_id": USER, "page": number, "size": 1,
            "return_full_object": "true",
            "include_team_keys": "false",
            "include_created_by_keys": "false",
        })


@pytest.mark.parametrize(("pages", "message"), [
    ([page(1, [KEYS[0]]), page(2, [{**KEYS[1], "user_id": "other"}])],
     "another user's key"),
    ([page(1, [KEYS[0]]), page(2, [KEYS[0]])], "Duplicate key"),
    ([page(1, [KEYS[0]]), page(2, [KEYS[1]], total=3)], "Key count changed"),
    ([page(1, [KEYS[0]], pages=1)], "Incomplete key discovery"),
    ([page(2, [KEYS[0]])], "Unexpected key-list page"),
    ([page(1, [])], "Empty page"),
    ([page(1, [{**KEYS[0], "token": ""}])], "no token identifier"),
], ids=["other-user", "duplicate", "changed-count", "incomplete",
        "wrong-page", "empty-page", "missing-token"])
def test_invalid_discovery_never_blocks_any_key(
    offline_client, json_response, pages, message,
):
    offline_client.get.side_effect = [json_response(p) for p in pages]

    with pytest.raises(AssertionError, match=message):
        offline_client.offboard_user_keys(user_id=USER, page_size=1)

    offline_client.post.assert_not_called()


@pytest.mark.parametrize("failure", [
    "http", "exception", "wrong-token", "wrong-user", "not-blocked",
])
def test_partial_block_failure_continues_and_reports_failure(
    offline_client, json_response, failure,
):
    client = offline_client
    client.list_user_keys = Mock(return_value=KEYS)
    first = {**KEYS[0], "blocked": True}
    status = 200
    if failure == "http":
        status = 500
    elif failure == "wrong-token":
        first["token"] = "different-token"
    elif failure == "wrong-user":
        first["user_id"] = "other-user"
    elif failure == "not-blocked":
        first["blocked"] = False

    first_response = (
        RuntimeError("private-response-placeholder") if failure == "exception"
        else json_response(first, status)
    )
    client.post.side_effect = [
        first_response,
        json_response({**KEYS[1], "blocked": True}),
    ]

    with pytest.raises(AssertionError, match="Offboarding incomplete") as error:
        client.offboard_user_keys(user_id=USER)

    assert client.post.call_args_list == [
        call("/key/block", json={"key": key["token"]}) for key in KEYS
    ]
    assert "confirmed=1/2" in str(error.value)
    assert "private-response-placeholder" not in str(error.value)
    assert all(key["token"] not in str(error.value) for key in KEYS)
