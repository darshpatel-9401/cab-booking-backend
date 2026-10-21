import pytest

import routers.webhooks as webhooks_module
from stripe_client import CURRENCY

USER_ID = "11111111-1111-1111-1111-111111111111"


def good_intent(**overrides):
    intent = {
        "id": "pi_topup",
        "amount": 5000,
        "currency": CURRENCY,
        "metadata": {"type": "wallet_topup", "user_id": USER_ID},
    }
    intent.update(overrides)
    return intent


@pytest.fixture
def no_database(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the database must not be used")

    monkeypatch.setattr(webhooks_module, "Session", boom)


@pytest.mark.parametrize(
    "overrides",
    [
        {"metadata": {"type": "wallet_topup", "user_id": "not-a-uuid"}},
        {"metadata": {"type": "wallet_topup"}},
        {"amount": 5},
        {"amount": 99999999},
        {"currency": "xyz"},
    ],
)
def test_bad_topup_data_never_touches_the_database(no_database, overrides):
    webhooks_module.apply_topup_event("payment_intent.succeeded", good_intent(**overrides))


def test_failed_topup_payment_is_ignored(no_database):
    webhooks_module.apply_topup_event("payment_intent.payment_failed", good_intent())


def test_topup_intents_are_routed_to_the_wallet_handler(no_database, monkeypatch):
    calls = []
    monkeypatch.setattr(
        webhooks_module, "apply_topup_event", lambda *args: calls.append(args)
    )
    intent = good_intent()

    result = webhooks_module.apply_payment_event("payment_intent.succeeded", intent)

    assert result is None
    assert calls == [("payment_intent.succeeded", intent)]