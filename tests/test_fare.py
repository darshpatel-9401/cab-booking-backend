import pytest

from fare import MINIMUM_FARE, calculate_fare


@pytest.mark.parametrize(
    "distance_meters, duration_secs, expected",
    [
        (5000, 900, 13250),
        (12000, 1800, 23900),
        (4742, 772, 12620),
        (30000, 3600, 50000),
        (500, 120, 8000),
        (0, 0, 8000),
    ],
)
def test_fare_amounts(distance_meters, duration_secs, expected):
    assert calculate_fare(distance_meters, duration_secs) == expected


def test_short_trips_never_go_below_minimum():
    for distance, duration in [(0, 0), (100, 30), (500, 120), (800, 200)]:
        assert calculate_fare(distance, duration) >= MINIMUM_FARE


@pytest.mark.parametrize("distance, duration", [(-1, 60), (1000, -1), (-5, -5)])
def test_negative_input_is_rejected(distance, duration):
    with pytest.raises(ValueError):
        calculate_fare(distance, duration)


def test_fare_is_a_whole_number():
    assert isinstance(calculate_fare(5000, 900), int)


def test_longer_trip_costs_more():
    assert calculate_fare(20000, 1800) > calculate_fare(10000, 1800)