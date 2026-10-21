from models import Wallet, WalletTransaction


def constraint_names(model):
    return {c.name for c in model.__table__.constraints if c.name}


def test_wallet_rules_are_declared():
    assert {
        "ck_wallets_balance_not_negative",
        "uq_wallets_user_currency",
    } <= constraint_names(Wallet)


def test_wallet_transaction_rules_are_declared():
    assert {
        "ck_wallet_tx_amount_not_zero",
        "ck_wallet_tx_kind_and_sign",
        "ck_wallet_tx_balance_after_not_negative",
        "fk_wallet_tx_wallet",
    } <= constraint_names(WalletTransaction)


def test_wallet_transaction_key_is_unique():
    assert WalletTransaction.__table__.c.idempotency_key.unique is True