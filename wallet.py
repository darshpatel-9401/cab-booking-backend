import uuid
from datetime import datetime, timezone
from money import min_charge_for

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from models import WALLET_RIDE_PAYMENT, WALLET_TOPUP, Wallet, WalletTransaction

MIN_TOPUP = 1000
MAX_TOPUP = 500000

def min_topup_for(currency: str) -> int:
    return max(MIN_TOPUP, min_charge_for(currency))

class WalletError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class InsufficientFunds(WalletError):
    def __init__(self):
        super().__init__(409, "Not enough wallet balance")


def check_sign(kind: str, amount: int) -> None:
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValueError("amount must be a whole number")
    if kind == WALLET_TOPUP and amount > 0:
        return
    if kind == WALLET_RIDE_PAYMENT and amount < 0:
        return
    raise ValueError("amount does not match the transaction kind")


def get_locked_wallet(db: Session, user_id: uuid.UUID, currency: str) -> Wallet:
    query = select(Wallet).where(Wallet.user_id == user_id).with_for_update()
    wallet = db.exec(query).first()

    if wallet is None:
        db.connection().execute(
            pg_insert(Wallet.__table__)
            .values(
                user_id=user_id,
                currency=currency,
                balance=0,
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        wallet = db.exec(query).first()

    if wallet is None:
        raise RuntimeError("Could not create the wallet")
    return wallet


def apply_wallet_change(
    db: Session,
    user_id: uuid.UUID,
    currency: str,
    kind: str,
    amount: int,
    idempotency_key: str,
):
    """The only function that changes a wallet balance.

    Returns (ledger_row, created). Does NOT commit: the caller decides.
    """
    check_sign(kind, amount)

    wallet = get_locked_wallet(db, user_id, currency)
    if wallet.currency != currency:
        raise WalletError(409, "Wallet currency mismatch")

    existing = db.exec(
        select(WalletTransaction).where(
            WalletTransaction.idempotency_key == idempotency_key
        )
    ).first()
    if existing is not None:
        same = (
            existing.user_id == user_id
            and existing.currency == currency
            and existing.kind == kind
            and existing.amount == amount
        )
        if not same:
            raise WalletError(409, "This wallet operation was already recorded differently")
        return existing, False

    new_balance = wallet.balance + amount
    if new_balance < 0:
        raise InsufficientFunds()

    transaction = WalletTransaction(
        user_id=user_id,
        currency=currency,
        kind=kind,
        amount=amount,
        balance_after=new_balance,
        idempotency_key=idempotency_key,
    )
    wallet.balance = new_balance
    wallet.updated_at = datetime.now(timezone.utc)
    db.add(transaction)
    db.add(wallet)
    db.flush()
    return transaction, True