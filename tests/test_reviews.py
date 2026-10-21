import uuid
from decimal import Decimal

from ratings import average_rating, distribution_from_rows, can_review_ride

import pytest
from pydantic import ValidationError

from routers.rides import ReviewCreate


def test_comment_is_trimmed():
    assert ReviewCreate(rating=5, comment="  great ride  ").comment == "great ride"


def test_blank_comment_becomes_none():
    assert ReviewCreate(rating=5, comment="   \n  ").comment is None


def test_missing_comment_is_allowed():
    assert ReviewCreate(rating=4).comment is None


def test_control_characters_are_removed():
    assert ReviewCreate(rating=5, comment="ok\x00bye\x07").comment == "okbye"


def test_newlines_and_tabs_are_kept():
    assert ReviewCreate(rating=5, comment="line one\n\tline two").comment == "line one\n\tline two"


@pytest.mark.parametrize("rating", [0, 6, "5", True, 4.5, None])
def test_invalid_ratings_are_rejected(rating):
    with pytest.raises(ValidationError):
        ReviewCreate(rating=rating)

class FakeResult:
    def __init__(self, value):
        self.value = value

    def one(self):
        return self.value


class FakeDb:
    def __init__(self, value):
        self.value = value

    def exec(self, statement):
        return FakeResult(self.value)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (Decimal("5.0000000000000000"), 5.0),
        (Decimal("3.6666666667"), 3.67),
        (Decimal("2.5"), 2.5),
        (None, 0.0),
    ],
)
def test_average_rating_rounds_to_two_decimals(raw, expected):
    assert average_rating(FakeDb(raw), uuid.uuid4()) == expected

def test_distribution_with_no_reviews_has_all_five_keys_at_zero():
    assert distribution_from_rows([]) == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


def test_distribution_fills_in_the_counts():
    rows = [(5, 3), (2, 1)]
    assert distribution_from_rows(rows) == {"1": 0, "2": 1, "3": 0, "4": 0, "5": 3}

@pytest.mark.parametrize(
    "status, has_other_party, reviewed, expected",
    [
        ("completed", True, False, True),
        ("completed", True, True, False),
        ("completed", False, False, False),
        ("cancelled", True, False, False),
        ("requested", True, False, False),
        ("accepted", True, False, False),
        ("in_progress", True, False, False),
    ],
)
def test_can_review_ride_rules(status, has_other_party, reviewed, expected):
    assert can_review_ride(status, has_other_party, reviewed) is expected