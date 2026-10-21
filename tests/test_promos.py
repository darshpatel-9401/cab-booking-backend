from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from promos import (
    MIN_CHARGE_AMOUNT,
    PromoError,
    calculate_discount,
    normalize_code,
    validate_promo_static,
)

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


def make_promo(**overrides):
    values = {
        "active": True,
        "expires_at": None,
        "discount_type": "percent",
        "currency": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "discount_type, value, cap, fare, expected",
    [
        ("percent", 10, None, 12620, 1262),
        ("percent", 10, 5000, 12620, 1262),
        ("percent", 50, 5000, 12620, 5000),
        ("percent", 100, None, 12620, 12620 - MIN_CHARGE_AMOUNT),
        ("percent", 10, None, 100, 10),
        ("fixed", 2000, None, 12620, 2000),
        ("fixed", 99999, None, 12620, 12620 - MIN_CHARGE_AMOUNT),
        ("percent", 10, None, 50, 0),
        ("fixed", 2000, None, 40, 0),
    ],
)
def test_calculate_discount(discount_type, value, cap, fare, expected):
    assert calculate_discount(discount_type, value, cap, fare) == expected


def test_final_amount_never_drops_below_the_minimum_charge():
    for fare in (51, 100, 8000, 12620):
        discount = calculate_discount("percent", 100, None, fare)
        assert fare - discount >= MIN_CHARGE_AMOUNT


@pytest.mark.parametrize(
    "raw, expected",
    [("welcome10", "WELCOME10"), ("  flat20  ", "FLAT20"), ("Promo_1-A", "PROMO_1-A")],
)
def test_normalize_code_accepts_valid_codes(raw, expected):
    assert normalize_code(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["AB", "WEL\x00COME", "WEL COME", "A" * 33, "", "ſALE10"],
)
def test_normalize_code_rejects_bad_codes(raw):
    assert normalize_code(raw) is None


def test_valid_promo_passes():
    validate_promo_static(make_promo(), NOW, "inr")


def test_missing_promo_is_not_valid():
    with pytest.raises(PromoError) as error:
        validate_promo_static(None, NOW, "inr")
    assert error.value.status_code == 404


def test_inactive_promo_is_not_valid():
    with pytest.raises(PromoError) as error:
        validate_promo_static(make_promo(active=False), NOW, "inr")
    assert error.value.status_code == 404


def test_expired_promo_is_not_valid():
    promo = make_promo(expires_at=NOW - timedelta(days=1))
    with pytest.raises(PromoError) as error:
        validate_promo_static(promo, NOW, "inr")
    assert error.value.status_code == 404


def test_fixed_promo_needs_a_matching_currency():
    promo = make_promo(discount_type="fixed", currency="usd")
    with pytest.raises(PromoError) as error:
        validate_promo_static(promo, NOW, "inr")
    assert error.value.status_code == 409


def test_percent_promo_ignores_currency():
    validate_promo_static(make_promo(discount_type="percent", currency=None), NOW, "usd")
