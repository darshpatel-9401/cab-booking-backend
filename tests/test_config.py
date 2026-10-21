import pytest

from config import parse_origins


def test_origins_are_split_and_cleaned():
    assert parse_origins("http://a.com, http://b.com/ ,") == [
        "http://a.com",
        "http://b.com",
    ]


def test_blank_origins_give_an_empty_list():
    assert parse_origins("  ") == []


def test_a_wildcard_origin_is_refused():
    with pytest.raises(RuntimeError):
        parse_origins("http://a.com,*")