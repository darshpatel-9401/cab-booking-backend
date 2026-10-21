# Stripe needs every charge to be worth at least the equivalent of $0.50 US.
# These floors are in the smallest currency unit, with a margin for exchange-rate
# changes. Check Stripe's documentation before adding another currency.
MIN_CHARGE_BY_CURRENCY = {"usd": 50, "inr": 6000}
FALLBACK_MIN_CHARGE = 10000


def min_charge_for(currency: str) -> int:
    return MIN_CHARGE_BY_CURRENCY.get(currency.lower(), FALLBACK_MIN_CHARGE)