import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from money import min_charge_for

from sqlalchemy import func
from sqlmodel import Session, select

from models import (
    DISCOUNT_FIXED,
    DISCOUNT_PERCENT,
    PAYMENT_SUCCEEDED,
    RIDE_COMPLETED,
    Payment,
    PromoCode,
    PromoRedemption,
    Ride,
)

# Default floor for the pure function below. The real floor depends on the
# currency, see money.py.
MIN_CHARGE_AMOUNT = 50

CODE_PATTERN = re.compile(r"[A-Z0-9_-]{3,32}")


class PromoError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def normalize_code(raw: str) -> Optional[str]:
    code = raw.strip()
    if not code.isascii():
        return None
    code = code.upper()
    if CODE_PATTERN.fullmatch(code):
        return code
    return None


def calculate_discount(
    discount_type: str,
    discount_value: int,
    max_discount: Optional[int],
    fare: int,
    min_charge: int = MIN_CHARGE_AMOUNT,
) -> int:
    if fare <= min_charge:
        return 0

    if discount_type == DISCOUNT_PERCENT:
        discount = fare * discount_value // 100
        if max_discount is not None:
            discount = min(discount, max_discount)
    else:
        discount = discount_value

    discount = min(discount, fare - min_charge)
    return max(discount, 0)


def validate_promo_static(promo, now: datetime, currency: str) -> None:
    if promo is None or not promo.active:
        raise PromoError(404, "Promo code not valid")
    if promo.expires_at is not None and promo.expires_at <= now:
        raise PromoError(404, "Promo code not valid")
    if promo.discount_type == DISCOUNT_FIXED and promo.currency != currency:
        raise PromoError(409, "This promo code is not valid for this currency")


def evaluate_promo(
    db: Session,
    ride_id: uuid.UUID,
    user_id: uuid.UUID,
    raw_code: str,
    currency: str,
    lock: bool = False,
) -> dict:
    ride = db.get(Ride, ride_id)
    if ride is None or ride.rider_id != user_id:
        raise PromoError(404, "Ride not found")
    if ride.status != RIDE_COMPLETED or not ride.fare_actual:
        raise PromoError(409, "Only a completed ride can use a promo code")

    paid = db.exec(
        select(Payment.id).where(
            Payment.ride_id == ride.id, Payment.status == PAYMENT_SUCCEEDED
        )
    ).first()
    if paid is not None:
        raise PromoError(409, "This ride is already paid")

    code = normalize_code(raw_code)
    if code is None:
        raise PromoError(404, "Promo code not valid")

    query = select(PromoCode).where(PromoCode.code == code)
    if lock:
        query = query.with_for_update()
    promo = db.exec(query).first()
    validate_promo_static(promo, datetime.now(timezone.utc), currency)

    existing = db.exec(
        select(PromoRedemption).where(PromoRedemption.ride_id == ride.id)
    ).first()
    if existing is not None and existing.promo_id != promo.id:
        raise PromoError(409, "A different promo code is already applied to this ride")

    total_uses = db.exec(
        select(func.count(PromoRedemption.id)).where(
            PromoRedemption.promo_id == promo.id,
            PromoRedemption.ride_id != ride.id,
        )
    ).one()
    if promo.max_total_uses is not None and total_uses >= promo.max_total_uses:
        raise PromoError(409, "This promo code has been fully used")

    user_uses = db.exec(
        select(func.count(PromoRedemption.id)).where(
            PromoRedemption.promo_id == promo.id,
            PromoRedemption.user_id == user_id,
            PromoRedemption.ride_id != ride.id,
        )
    ).one()
    if user_uses >= promo.max_uses_per_user:
        raise PromoError(409, "You have already used this promo code")

    fare = ride.fare_actual
    discount = calculate_discount(
        promo.discount_type,
        promo.discount_value,
        promo.max_discount,
        fare,
        min_charge_for(currency),
    )
    if discount <= 0:
        raise PromoError(409, "This promo code gives no discount on this ride")

    return {"promo": promo, "ride": ride, "fare": fare, "discount": discount}