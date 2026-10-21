import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from auth import get_current_user
from database import get_session
from emailer import send_receipt_for_ride
from events import publish_event_sync
from models import (
    PAYMENT_FAILED,
    PAYMENT_SUCCEEDED,
    REDEMPTION_REDEEMED,
    RIDE_COMPLETED,
    WALLET_RIDE_PAYMENT,
    Payment,
    PromoRedemption,
    Ride,
)
from promos import PromoError, evaluate_promo
from stripe_client import CURRENCY, stripe
from wallet import WalletError, apply_wallet_change

router = APIRouter(prefix="/api/payments", tags=["payments"])

# Statuses where Stripe still lets us change the amount
OPEN_INTENT_STATUSES = {"requires_payment_method", "requires_confirmation"}
# Statuses where we can cancel a card payment before it is charged
CANCELLABLE_INTENT_STATUSES = {
    "requires_payment_method",
    "requires_confirmation",
    "requires_action",
}


class IntentRequest(BaseModel):
    promo_code: Optional[str] = Field(default=None, max_length=64)


def clean_promo_code(body: Optional[IntentRequest]) -> Optional[str]:
    if body is not None and body.promo_code and body.promo_code.strip():
        return body.promo_code
    return None


def resolve_discount(
    db: Session, ride_id: uuid.UUID, user_id: uuid.UUID, promo_code: Optional[str]
):
    """Returns (discount, redemption). Adds the reservation to the session but
    does not commit it. Raises HTTPException for an invalid code."""
    redemption = db.exec(
        select(PromoRedemption).where(PromoRedemption.ride_id == ride_id)
    ).first()

    if promo_code is None:
        return (redemption.discount_amount if redemption else 0), redemption

    try:
        result = evaluate_promo(db, ride_id, user_id, promo_code, CURRENCY, lock=True)
    except PromoError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    discount = result["discount"]
    if redemption is None:
        redemption = PromoRedemption(
            promo_id=result["promo"].id,
            user_id=user_id,
            ride_id=ride_id,
            discount_amount=discount,
        )
    else:
        redemption.discount_amount = discount
    db.add(redemption)
    return discount, redemption


@router.post("/rides/{ride_id}/intent")
def create_payment_intent(
    ride_id: uuid.UUID,
    body: Optional[IntentRequest] = None,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    # Lock the ride row so two requests can't create two payments at once
    ride = db.exec(select(Ride).where(Ride.id == ride_id).with_for_update()).first()
    if ride is None or ride.rider_id != user_id:
        raise HTTPException(status_code=404, detail="Ride not found")

    if ride.status != RIDE_COMPLETED or not ride.fare_actual:
        raise HTTPException(
            status_code=409, detail="Only a completed ride can be paid"
        )

    fare = ride.fare_actual

    existing = db.exec(
        select(Payment)
        .where(Payment.ride_id == ride_id)
        .order_by(col(Payment.created_at).desc())
    ).first()
    if existing is not None and existing.status == PAYMENT_SUCCEEDED:
        raise HTTPException(status_code=409, detail="This ride is already paid")

    discount, _ = resolve_discount(db, ride_id, user_id, clean_promo_code(body))
    amount = fare - discount

    if existing is not None:
        try:
            intent = stripe.PaymentIntent.retrieve(existing.stripe_payment_intent_id)
        except Exception as e:
            print("Stripe error:", e)
            raise HTTPException(
                status_code=502, detail="Could not reach the payment service"
            )

        if intent.status == "succeeded":
            raise HTTPException(status_code=409, detail="This ride is already paid")
        if intent.status == "canceled":
            raise HTTPException(
                status_code=409, detail="This payment was cancelled. Contact support"
            )

        if intent.amount != amount:
            if intent.status not in OPEN_INTENT_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail="A payment is in progress, so the amount can't change now",
                )
            try:
                intent = stripe.PaymentIntent.modify(intent.id, amount=amount)
            except Exception as e:
                print("Stripe error:", e)
                raise HTTPException(
                    status_code=502, detail="Could not update the payment right now"
                )

        payment_id = str(existing.id)
        if existing.amount != amount:
            existing.amount = amount
            db.add(existing)
        db.commit()

        return {
            "payment_id": payment_id,
            "client_secret": intent.client_secret,
            "amount": amount,
            "currency": intent.currency,
            "original_amount": fare,
            "discount_amount": discount,
            "reused": True,
        }

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=CURRENCY,
            metadata={"ride_id": str(ride_id), "rider_id": str(user_id)},
            idempotency_key=f"ride-{ride_id}-{CURRENCY}-{amount}",
        )
    except Exception as e:
        print("Stripe error:", e)
        raise HTTPException(
            status_code=502, detail="Could not create the payment right now"
        )

    payment = Payment(
        ride_id=ride_id,
        stripe_payment_intent_id=intent.id,
        amount=amount,
        currency=intent.currency,
    )
    payment_id = payment.id
    db.add(payment)
    db.commit()

    return {
        "payment_id": str(payment_id),
        "client_secret": intent.client_secret,
        "amount": amount,
        "currency": CURRENCY,
        "original_amount": fare,
        "discount_amount": discount,
        "reused": False,
    }


@router.post("/rides/{ride_id}/pay-with-wallet")
def pay_with_wallet(
    ride_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    body: Optional[IntentRequest] = None,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    # Lock the ride first, then (inside the helpers) the promo and the wallet
    ride = db.exec(select(Ride).where(Ride.id == ride_id).with_for_update()).first()
    if ride is None or ride.rider_id != user_id:
        raise HTTPException(status_code=404, detail="Ride not found")

    if ride.status != RIDE_COMPLETED or not ride.fare_actual:
        raise HTTPException(
            status_code=409, detail="Only a completed ride can be paid"
        )

    fare = ride.fare_actual

    existing = db.exec(
        select(Payment)
        .where(Payment.ride_id == ride_id)
        .order_by(col(Payment.created_at).desc())
    ).first()
    if existing is not None and existing.status == PAYMENT_SUCCEEDED:
        raise HTTPException(status_code=409, detail="This ride is already paid")

    discount, redemption = resolve_discount(
        db, ride_id, user_id, clean_promo_code(body)
    )
    amount = fare - discount

    # Look at any card payment already started for this ride (nothing is changed yet)
    old_intent = None
    if existing is not None:
        try:
            old_intent = stripe.PaymentIntent.retrieve(
                existing.stripe_payment_intent_id
            )
        except Exception as e:
            print("Stripe error:", e)
            raise HTTPException(
                status_code=502, detail="Could not reach the payment service"
            )

        if old_intent.status == "succeeded":
            raise HTTPException(status_code=409, detail="This ride is already paid")
        if (
            old_intent.status not in CANCELLABLE_INTENT_STATUSES
            and old_intent.status != "canceled"
        ):
            raise HTTPException(
                status_code=409,
                detail="A card payment is in progress. Try again in a moment",
            )

    # The debit, written to the session but not committed yet
    try:
        transaction, _created = apply_wallet_change(
            db, user_id, CURRENCY, WALLET_RIDE_PAYMENT, -amount, f"ride:{ride_id}"
        )
    except WalletError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    balance_after = transaction.balance_after

    # Cancel the earlier card payment, so the ride can't be paid twice
    if old_intent is not None and old_intent.status in CANCELLABLE_INTENT_STATUSES:
        try:
            stripe.PaymentIntent.cancel(old_intent.id)
        except Exception as e:
            print("Stripe error:", e)
            raise HTTPException(
                status_code=502,
                detail="Could not cancel the earlier card payment. Nothing was charged",
            )
    if existing is not None:
        existing.status = PAYMENT_FAILED
        db.add(existing)

    payment = Payment(
        ride_id=ride_id,
        stripe_payment_intent_id=f"wallet:{ride_id}",
        amount=amount,
        currency=CURRENCY,
        status=PAYMENT_SUCCEEDED,
    )
    payment_id = payment.id
    db.add(payment)

    if redemption is not None:
        redemption.status = REDEMPTION_REDEEMED
        db.add(redemption)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This ride is already paid")

    publish_event_sync(
        user_id,
        "payment_status",
        {"ride_id": str(ride_id), "status": PAYMENT_SUCCEEDED, "amount": amount},
    )
    publish_event_sync(
        user_id,
        "wallet_updated",
        {"balance": balance_after, "currency": CURRENCY, "amount": -amount},
    )
    background_tasks.add_task(send_receipt_for_ride, ride_id, user_id)

    return {
        "payment_id": str(payment_id),
        "status": PAYMENT_SUCCEEDED,
        "amount": amount,
        "original_amount": fare,
        "discount_amount": discount,
        "currency": CURRENCY,
        "balance_after": balance_after,
    }


@router.get("/rides/{ride_id}")
def ride_payment_status(
    ride_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    ride = db.get(Ride, ride_id)
    if ride is None or ride.rider_id != user_id:
        raise HTTPException(status_code=404, detail="Ride not found")

    payment = db.exec(
        select(Payment)
        .where(Payment.ride_id == ride_id)
        .order_by(col(Payment.created_at).desc())
    ).first()

    if payment is None:
        return {"ride_id": str(ride_id), "payment": None}

    return {
        "ride_id": str(ride_id),
        "payment": {
            "payment_id": str(payment.id),
            "status": payment.status,
            "amount": payment.amount,
        },
    }