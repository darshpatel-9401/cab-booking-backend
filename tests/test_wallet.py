import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models import User, Wallet, WalletTransaction
from wallet import (
    MAX_TOPUP,
    MIN_TOPUP,
    InsufficientFunds,
    WalletError,
    apply_wallet_change,
)

USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Wallet.__table__, WalletTransaction.__table__],
    )
    with Session(engine) as session:
        session.add(User(id=USER_ID, email="a@example.com"))
        session.add(Wallet(user_id=USER_ID, currency="inr", balance=0))
        session.commit()
        yield session


def all_transactions(db):
    return db.exec(select(WalletTransaction)).all()


def test_topup_increases_balance_and_records_balance_after(db):
    transaction, created = apply_wallet_change(
        db, USER_ID, "inr", "topup", 5000, "topup:pi_1"
    )
    db.commit()

    assert created is True
    assert transaction.balance_after == 5000
    assert db.get(Wallet, USER_ID).balance == 5000


def test_ride_payment_decreases_balance(db):
    apply_wallet_change(db, USER_ID, "inr", "topup", 5000, "topup:pi_1")
    db.commit()
    transaction, created = apply_wallet_change(
        db, USER_ID, "inr", "ride_payment", -1200, "ride:r1"
    )
    db.commit()

    assert created is True
    assert transaction.balance_after == 3800
    assert db.get(Wallet, USER_ID).balance == 3800


def test_debit_beyond_balance_is_refused_and_changes_nothing(db):
    apply_wallet_change(db, USER_ID, "inr", "topup", 1000, "topup:pi_1")
    db.commit()

    with pytest.raises(InsufficientFunds):
        apply_wallet_change(db, USER_ID, "inr", "ride_payment", -1001, "ride:r1")
    db.rollback()

    assert db.get(Wallet, USER_ID).balance == 1000
    assert len(all_transactions(db)) == 1


def test_same_key_replay_does_not_change_the_balance(db):
    first, created_first = apply_wallet_change(
        db, USER_ID, "inr", "topup", 5000, "topup:pi_1"
    )
    db.commit()
    second, created_second = apply_wallet_change(
        db, USER_ID, "inr", "topup", 5000, "topup:pi_1"
    )
    db.commit()

    assert (created_first, created_second) == (True, False)
    assert second.id == first.id
    assert db.get(Wallet, USER_ID).balance == 5000
    assert len(all_transactions(db)) == 1


def test_same_key_with_a_different_amount_is_refused(db):
    apply_wallet_change(db, USER_ID, "inr", "topup", 5000, "topup:pi_1")
    db.commit()

    with pytest.raises(WalletError) as error:
        apply_wallet_change(db, USER_ID, "inr", "topup", 9000, "topup:pi_1")
    db.rollback()

    assert error.value.status_code == 409
    assert db.get(Wallet, USER_ID).balance == 5000


def test_wrong_currency_is_refused(db):
    with pytest.raises(WalletError) as error:
        apply_wallet_change(db, USER_ID, "usd", "topup", 5000, "topup:pi_1")
    db.rollback()

    assert error.value.status_code == 409
    assert db.get(Wallet, USER_ID).balance == 0
    assert all_transactions(db) == []


@pytest.mark.parametrize(
    "kind, amount",
    [
        ("topup", -100),
        ("topup", 0),
        ("ride_payment", 100),
        ("ride_payment", 0),
        ("bogus", 100),
    ],
)
def test_amount_sign_must_match_the_kind(db, kind, amount):
    with pytest.raises(ValueError):
        apply_wallet_change(db, USER_ID, "inr", kind, amount, "key:1")


def test_balance_equals_the_sum_of_the_ledger(db):
    steps = [
        ("topup", 5000, "topup:1"),
        ("ride_payment", -1200, "ride:1"),
        ("topup", 700, "topup:2"),
        ("ride_payment", -300, "ride:2"),
    ]
    for kind, amount, key in steps:
        apply_wallet_change(db, USER_ID, "inr", kind, amount, key)
        db.commit()

    rows = all_transactions(db)
    assert sum(row.amount for row in rows) == db.get(Wallet, USER_ID).balance == 4200
    assert {row.balance_after for row in rows} == {5000, 3800, 4500, 4200}


def test_topup_limits_are_sane():
    assert 50 <= MIN_TOPUP < MAX_TOPUP