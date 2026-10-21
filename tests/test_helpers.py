import json

import pytest

from auth import TokenError, verify_token
from events import build_payload, channel_for
from maps import get_route


def test_channel_name_uses_user_id():
    assert channel_for("abc-123") == "user:abc-123"


def test_build_payload_wraps_type_and_data():
    payload = json.loads(build_payload("ping", {"message": "hi"}))
    assert payload == {"type": "ping", "data": {"message": "hi"}}


def test_build_payload_defaults_to_empty_data():
    payload = json.loads(build_payload("ping", None))
    assert payload == {"type": "ping", "data": {}}


@pytest.mark.parametrize(
    "args, word",
    [
        ((91, 0, 0, 0), "latitude"),
        ((0, 0, -91, 0), "latitude"),
        ((0, 181, 0, 0), "longitude"),
        ((0, 0, 0, -181), "longitude"),
    ],
)
def test_get_route_rejects_impossible_coordinates(args, word):
    with pytest.raises(ValueError, match=word):
        get_route(*args)


def test_verify_token_rejects_garbage():
    with pytest.raises(TokenError):
        verify_token("this-is-not-a-jwt")