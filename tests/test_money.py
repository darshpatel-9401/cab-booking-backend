import pytest

from money import min_charge_for
from promos import calculate_discount
from wallet import min_topup_for


@pytest.mark.parametrize(
    "currency, expected",
    [("inr", 6000), ("INR", 6000), ("usd", 50), ("eur", 10000)],
)
def test_min_charge_for(currency, expected):
    assert min_charge_for(currency) == expected


@pytest.mark.parametrize(
    "fare, expected_discount",
    [(12620, 6620), (8000, 2000), (6000, 0), (5000, 0)],
)
def test_discount_respects_the_currency_minimum(fare, expected_discount):
    assert calculate_discount("percent", 100, None, fare, 6000) == expected_discount


@pytest.mark.parametrize(
    "currency, expected",
    [("inr", 6000), ("usd", 1000), ("eur", 10000)],
)
def test_min_topup_for(currency, expected):
    assert min_topup_for(currency) == expected