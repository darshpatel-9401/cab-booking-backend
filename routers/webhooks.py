import asyncio
import json
import os
import uuid

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from database import engine
from emailer import send_receipt_for_ride
from events import publish_event_sync
from models import (
    PAYMENT_FAILED,
    PAYMENT_SUCCEEDED,
    REDEMPTION_REDEEMED,
    WALLET_TOPUP,
    Payment,
    PromoRedemption,
    Ride,
    User,
)
from stripe_client import CURRENCY, stripe
from wallet import MAX_TOPUP, MIN_TOPUP, WalletError, apply_wallet_change

load_dotenv()

WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
if not WEBHOOK_SECRET.startswith("whsec_"):
    raise RuntimeError("STRIPE_WEBHOOK_SECRET in backend/.env must start with whsec_")

router = APIRouter(tags=["webhooks"])

HANDLED_EVENTS = {"payment_intent.succeeded", "payment_intent.payment_failed"}


def apply_topup_event(event_type: str, intent: dict) -> None:
    if event_type != "payment_intent.succeeded":
        return

    intent_id = intent.get("id")
    metadata = intent.get("metadata") or {}

    try:
        user_id = uuid.UUID(str(metadata.get("user_id", "")))
    except ValueError:
        print("Top-up webhook with an invalid user id:", intent_id)
        return

    amount = intent.get("amount")
    currency = (intent.get("currency") or "").lower()
    valid_amount = (
        isinstance(amount, int)
        and not isinstance(amount, bool)
        and MIN_TOPUP <= amount <= MAX_TOPUP
    )
    if not intent_id or not valid_amount or currency != CURRENCY:
        print("Top-up webhook rejected:", intent_id, amount, currency)
        return

    notify = None
    with Session(engine) as db:
        if db.get(User, user_id) is None:
            print("Top-up webhook for an unknown user:", intent_id)
            return

        try:
            transaction, created = apply_wallet_change(
                db, user_id, currency, WALLET_TOPUP, amount, f"topup:{intent_id}"
            )
            balance_after = transaction.balance_after
            db.commit()
        except (WalletError, IntegrityError) as e:
            db.rollback()
            print("Top-up could not be applied:", intent_id, repr(e))
            return

        if created:
            print("Wallet top-up credited:", intent_id)
            notify = (
                user_id,
                {"balance": balance_after, "currency": currency, "amount": amount},
            )
        else:
            print("Wallet top-up already recorded:", intent_id)

    if notify is not None:
        publish_event_sync(notify[0], "wallet_updated", notify[1])


def apply_payment_event(event_type: str, intent: dict):
    """Returns (ride_id, rider_id) when a ride payment newly succeeded, otherwise None."""
    metadata = intent.get("metadata") or {}
    if metadata.get("type") == "wallet_topup":
        apply_topup_event(event_type, intent)
        return None

    intent_id = intent.get("id")
    notify = None
    email_job = None

    with Session(engine) as db:
        payment = db.exec(
            select(Payment)
            .where(Payment.stripe_payment_intent_id == intent_id)
            .with_for_update()
        ).first()

        if payment is None:
            print("Webhook for unknown payment intent:", intent_id)
            return None

        if intent.get("amount") != payment.amount:
            print(
                "Webhook amount mismatch, not updating:",
                intent_id,
                intent.get("amount"),
                payment.amount,
            )
            return None

        if (intent.get("currency") or "").lower() != payment.currency:
            print(
                "Webhook currency mismatch, not updating:",
                intent_id,
                intent.get("currency"),
                payment.currency,
            )
            return None

        if event_type == "payment_intent.succeeded":
            new_status = PAYMENT_SUCCEEDED
        else:
            new_status = PAYMENT_FAILED

        if payment.status == PAYMENT_SUCCEEDED:
            return None  # already paid, ignore repeats and late "failed" events

        if payment.status != new_status:
            # Collect everything we need before the commit
            ride = db.get(Ride, payment.ride_id)
            if ride is not None:
                notify = (
                    ride.rider_id,
                    {
                        "ride_id": str(payment.ride_id),
                        "status": new_status,
                        "amount": payment.amount,
                    },
                )
                if new_status == PAYMENT_SUCCEEDED:
                    email_job = (payment.ride_id, ride.rider_id)

            if new_status == PAYMENT_SUCCEEDED:
                redemption = db.exec(
                    select(PromoRedemption).where(
                        PromoRedemption.ride_id == payment.ride_id
                    )
                ).first()
                if redemption is not None:
                    redemption.status = REDEMPTION_REDEEMED
                    db.add(redemption)

            payment.status = new_status
            db.add(payment)
            db.commit()
            print("Payment", intent_id, "is now", new_status)

    # After the database work is saved and the session is closed
    if notify is not None:
        publish_event_sync(notify[0], "payment_status", notify[1])

    return email_job


@router.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        stripe.Webhook.construct_event(payload, signature, WEBHOOK_SECRET)
    except Exception as e:
        print("Webhook rejected:", repr(e))
        raise HTTPException(status_code=400, detail="Invalid webhook")

    event = json.loads(payload)
    event_type = event.get("type", "")

    if event_type in HANDLED_EVENTS:
        intent = event["data"]["object"]
        email_job = await asyncio.to_thread(apply_payment_event, event_type, intent)
        if email_job is not None:
            background_tasks.add_task(send_receipt_for_ride, *email_job)

    return {"received": True}