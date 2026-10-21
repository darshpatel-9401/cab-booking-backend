import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, col, select

from auth import get_current_user
from database import get_session
from models import User, Wallet, WalletTransaction
from redis_client import redis_sync
from stripe_client import CURRENCY, stripe
from wallet import MAX_TOPUP, MIN_TOPUP, min_topup_for

router = APIRouter(prefix="/api/wallet", tags=["wallet"])


class TopupRequest(BaseModel):
    amount: int = Field(ge=MIN_TOPUP, le=MAX_TOPUP, strict=True)


@router.get("")
def get_wallet(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])
    wallet = db.get(Wallet, user_id)

    limits = {"min_topup": min_topup_for(CURRENCY), "max_topup": MAX_TOPUP}
    if wallet is None:
        return {"balance": 0, "currency": CURRENCY, **limits}
    return {"balance": wallet.balance, "currency": wallet.currency, **limits}


@router.get("/transactions")
def wallet_transactions(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    total = db.exec(
        select(func.count(WalletTransaction.id)).where(
            WalletTransaction.user_id == user_id
        )
    ).one()

    rows = db.exec(
        select(
            WalletTransaction.id,
            WalletTransaction.kind,
            WalletTransaction.amount,
            WalletTransaction.balance_after,
            WalletTransaction.currency,
            WalletTransaction.created_at,
        )
        .where(WalletTransaction.user_id == user_id)
        .order_by(col(WalletTransaction.created_at).desc(), col(WalletTransaction.id))
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "transactions": [
            {
                "id": str(row.id),
                "kind": row.kind,
                "amount": row.amount,
                "balance_after": row.balance_after,
                "currency": row.currency,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.post("/topup", status_code=201)
def create_topup(
    body: TopupRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    minimum = min_topup_for(CURRENCY)
    if body.amount < minimum:
        raise HTTPException(
            status_code=422,
            detail=f"The minimum top-up is {minimum // 100}.{minimum % 100:02d} {CURRENCY.upper()}",
        )
    
    user_id = uuid.UUID(user["id"])

    if db.get(User, user_id) is None:
        raise HTTPException(
            status_code=400,
            detail="Profile not found. Call POST /api/auth/session first",
        )

    try:
        allowed = redis_sync.set(f"wallet-topup:{user_id}", "1", nx=True, ex=3)
    except Exception as e:
        print("Redis error (cooldown skipped):", e)
        allowed = True

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Please wait a few seconds before starting another top-up",
        )

    try:
        intent = stripe.PaymentIntent.create(
            amount=body.amount,
            currency=CURRENCY,
            metadata={"type": "wallet_topup", "user_id": str(user_id)},
        )
    except Exception as e:
        print("Stripe error:", e)
        raise HTTPException(
            status_code=502, detail="Could not start the top-up right now"
        )

    return {
        "client_secret": intent.client_secret,
        "amount": body.amount,
        "currency": CURRENCY,
    }