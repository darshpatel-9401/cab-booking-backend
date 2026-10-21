import uuid

from sqlalchemy import text
from sqlmodel import Session, col, select

from models import (
    PAYMENT_SUCCEEDED,
    REDEMPTION_REDEEMED,
    Driver,
    Payment,
    PromoCode,
    PromoRedemption,
    Ride,
    User,
)


class ReceiptNotFound(Exception):
    """The ride doesn't exist, or it doesn't belong to this rider."""


class ReceiptNotReady(Exception):
    """The ride has no successful payment yet."""


POINTS_SQL = text(
    """
    SELECT
        ST_Y(pickup_point) AS pickup_lat,
        ST_X(pickup_point) AS pickup_lng,
        ST_Y(drop_point) AS drop_lat,
        ST_X(drop_point) AS drop_lng
    FROM rides
    WHERE id = :ride_id
    """
)


def discount_applied(fare: int, paid: int) -> int:
    return max(fare - paid, 0)


def build_receipt(db: Session, ride_id: uuid.UUID, rider_id: uuid.UUID) -> dict:
    ride = db.get(Ride, ride_id)
    if ride is None or ride.rider_id != rider_id:
        raise ReceiptNotFound()

    rider = db.get(User, rider_id)
    if rider is None:
        raise ReceiptNotFound()

    payment = db.exec(
        select(Payment)
        .where(Payment.ride_id == ride_id, Payment.status == PAYMENT_SUCCEEDED)
        .order_by(col(Payment.created_at).desc())
    ).first()
    if payment is None:
        raise ReceiptNotReady()

    points = (
        db.connection()
        .execute(POINTS_SQL, {"ride_id": str(ride_id)})
        .mappings()
        .first()
    )
    driver = db.get(Driver, ride.driver_id) if ride.driver_id else None

    fare = ride.fare_actual if ride.fare_actual else payment.amount
    discount = discount_applied(fare, payment.amount)

    promo_code = None
    if discount > 0:
        redemption = db.exec(
            select(PromoRedemption).where(
                PromoRedemption.ride_id == ride_id,
                PromoRedemption.status == REDEMPTION_REDEEMED,
            )
        ).first()
        if redemption is not None:
            promo = db.get(PromoCode, redemption.promo_id)
            if promo is not None:
                promo_code = promo.code

    return {
        "receipt_number": f"RCPT-{payment.id.hex[:8].upper()}",
        "ride_id": str(ride.id),
        "payment_id": str(payment.id),
        "ride_date": ride.created_at.isoformat(),
        "rider": {"name": rider.name, "email": rider.email},
        "vehicle": driver.vehicle_info if driver else None,
        "pickup": {"lat": points["pickup_lat"], "lng": points["pickup_lng"]},
        "drop": {"lat": points["drop_lat"], "lng": points["drop_lng"]},
        "distance_meters": ride.distance_meters,
        "duration_secs": ride.duration_secs,
        "original_amount": fare,
        "discount_amount": discount,
        "promo_code": promo_code,
        "amount": payment.amount,
        "currency": payment.currency,
    }