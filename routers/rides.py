import uuid
import unicodedata
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from geoalchemy2.elements import WKTElement
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, col, select

from auth import get_current_user
from database import get_session
from fare import calculate_fare
from maps import RouteError, get_route
from matching import assign_nearest_driver
from receipts import ReceiptNotFound, ReceiptNotReady, build_receipt
from receipt_pdf import render_receipt_pdf
from ratings import average_rating, can_review_ride
from emailer import send_receipt_for_ride
from redis_client import redis_sync
from events import publish_event_sync
from stripe_client import CURRENCY
from ratelimit import rate_limit
from models import (
    RIDE_ACCEPTED,
    RIDE_CANCELLED,
    RIDE_COMPLETED,
    RIDE_IN_PROGRESS,
    RIDE_REQUESTED,
    Driver,
    Payment,
    Review,
    Ride,
    User,
)

router = APIRouter(prefix="/api/rides", tags=["rides"])

ACTIVE_STATUSES = [RIDE_REQUESTED, RIDE_ACCEPTED, RIDE_IN_PROGRESS]
CANCELLABLE_STATUSES = [RIDE_REQUESTED, RIDE_ACCEPTED]
MAX_TRIP_DISTANCE_METERS = 200_000


@router.get("/estimate", dependencies=[Depends(rate_limit("estimate", 30, 60))])
def estimate_ride(
    origin_lat: float = Query(..., ge=-90, le=90),
    origin_lng: float = Query(..., ge=-180, le=180),
    dest_lat: float = Query(..., ge=-90, le=90),
    dest_lng: float = Query(..., ge=-180, le=180),
    user: dict = Depends(get_current_user),
):
    try:
        route = get_route(origin_lat, origin_lng, dest_lat, dest_lng)
    except RouteError as e:
        print("Routing error:", e)
        raise HTTPException(
            status_code=502, detail="Could not calculate a route right now"
        )
    
    if route["distance_meters"] > MAX_TRIP_DISTANCE_METERS:
        raise HTTPException(
            status_code=422,
            detail="Trips longer than 200 km are not supported",
        )

    fare = calculate_fare(route["distance_meters"], route["duration_secs"])

    return {
        "distance_meters": route["distance_meters"],
        "duration_secs": route["duration_secs"],
        "fare_estimate": fare,
        "currency": CURRENCY,
    }


class RideRequest(BaseModel):
    pickup_lat: float = Field(ge=-90, le=90)
    pickup_lng: float = Field(ge=-180, le=180)
    drop_lat: float = Field(ge=-90, le=90)
    drop_lng: float = Field(ge=-180, le=180)


@router.post("/request", status_code=201, dependencies=[Depends(rate_limit("ride-request", 10, 60))])
def request_ride(
    body: RideRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    rider_id = uuid.UUID(user["id"])

    if db.get(User, rider_id) is None:
        raise HTTPException(
            status_code=400,
            detail="Profile not found. Call POST /api/auth/session first",
        )

    if body.pickup_lat == body.drop_lat and body.pickup_lng == body.drop_lng:
        raise HTTPException(
            status_code=400, detail="Pickup and drop-off must be different"
        )

    active_ride = db.exec(
        select(Ride).where(
            Ride.rider_id == rider_id,
            col(Ride.status).in_(ACTIVE_STATUSES),
        )
    ).first()
    if active_ride is not None:
        raise HTTPException(
            status_code=409, detail="You already have an active ride"
        )

    try:
        route = get_route(
            body.pickup_lat, body.pickup_lng, body.drop_lat, body.drop_lng
        )
    except RouteError as e:
        print("Routing error:", e)
        raise HTTPException(
            status_code=502, detail="Could not calculate a route right now"
        )

    if route["distance_meters"] > MAX_TRIP_DISTANCE_METERS:
        raise HTTPException(
            status_code=422,
            detail="Trips longer than 200 km are not supported",
        )

    fare = calculate_fare(route["distance_meters"], route["duration_secs"])

    ride = Ride(
        rider_id=rider_id,
        pickup_point=WKTElement(
            f"POINT({body.pickup_lng:.7f} {body.pickup_lat:.7f})", srid=4326
        ),
        drop_point=WKTElement(
            f"POINT({body.drop_lng:.7f} {body.drop_lat:.7f})", srid=4326
        ),
        fare_estimate=fare,
        distance_meters=route["distance_meters"],
        duration_secs=route["duration_secs"],
    )
    ride_id = ride.id

    db.add(ride)
    db.commit()

    return {
        "ride_id": str(ride_id),
        "status": RIDE_REQUESTED,
        "fare_estimate": fare,
        "distance_meters": route["distance_meters"],
        "duration_secs": route["duration_secs"],
        "currency": CURRENCY,
    }

@router.get("/{ride_id}/status")
def ride_status(
    ride_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])
    ride = db.get(Ride, ride_id)

    if ride is None or user_id not in (ride.rider_id, ride.driver_id):
        raise HTTPException(status_code=404, detail="Ride not found")

    # Only the rider of the ride sees the driver's vehicle
    vehicle_info = None
    if ride.driver_id is not None and user_id == ride.rider_id:
        driver = db.get(Driver, ride.driver_id)
        if driver is not None:
            vehicle_info = driver.vehicle_info

    return {
        "ride_id": str(ride.id),
        "status": ride.status,
        "driver_id": str(ride.driver_id) if ride.driver_id else None,
        "vehicle_info": vehicle_info,
        "fare_estimate": ride.fare_estimate,
        "fare_actual": ride.fare_actual,
        "distance_meters": ride.distance_meters,
        "duration_secs": ride.duration_secs,
        "created_at": ride.created_at.isoformat(),
    }

@router.post("/{ride_id}/match", dependencies=[Depends(rate_limit("ride-match", 20, 60))])
def match_ride(
    ride_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    # Lock the ride row so two match requests can't run on it at once
    ride = db.exec(select(Ride).where(Ride.id == ride_id).with_for_update()).first()
    if ride is None or ride.rider_id != user_id:
        raise HTTPException(status_code=404, detail="Ride not found")

    if ride.status != RIDE_REQUESTED:
        raise HTTPException(
            status_code=409, detail="This ride is not waiting for a driver"
        )

    matched = assign_nearest_driver(db, ride)
    if matched is None:
        raise HTTPException(
            status_code=503, detail="No drivers available nearby right now"
        )

    driver_info = {
        "vehicle_info": matched["vehicle_info"],
        "distance_meters": matched["distance_meters"],
    }
    publish_event_sync(
        user_id,
        "ride_status",
        {"ride_id": str(ride_id), "status": RIDE_ACCEPTED, "driver": driver_info},
    )
    publish_event_sync(matched["driver_id"], "ride_assigned", {"ride_id": str(ride_id)})

    return {
        "ride_id": str(ride_id),
        "status": RIDE_ACCEPTED,
        "driver": driver_info,
    }

@router.post("/{ride_id}/start")
def start_ride(
    ride_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    ride = db.exec(select(Ride).where(Ride.id == ride_id).with_for_update()).first()
    if ride is None or ride.driver_id != user_id:
        raise HTTPException(status_code=404, detail="Ride not found")

    if ride.status != RIDE_ACCEPTED:
        raise HTTPException(
            status_code=409, detail="This ride cannot be started right now"
        )

    rider_id = ride.rider_id
    ride.status = RIDE_IN_PROGRESS
    db.add(ride)
    db.commit()

    publish_event_sync(
        rider_id,
        "ride_status",
        {"ride_id": str(ride_id), "status": RIDE_IN_PROGRESS},
    )

    return {"ride_id": str(ride_id), "status": RIDE_IN_PROGRESS}

@router.post("/{ride_id}/complete")
def complete_ride(
    ride_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    ride = db.exec(select(Ride).where(Ride.id == ride_id).with_for_update()).first()
    if ride is None or ride.driver_id != user_id:
        raise HTTPException(status_code=404, detail="Ride not found")

    if ride.status != RIDE_IN_PROGRESS:
        raise HTTPException(
            status_code=409, detail="Only a ride in progress can be completed"
        )

    rider_id = ride.rider_id
    fare = ride.fare_estimate
    ride.status = RIDE_COMPLETED
    ride.fare_actual = fare
    db.add(ride)
    db.commit()

    publish_event_sync(
        rider_id,
        "ride_status",
        {"ride_id": str(ride_id), "status": RIDE_COMPLETED, "fare_actual": fare},
    )

    return {"ride_id": str(ride_id), "status": RIDE_COMPLETED, "fare_actual": fare}


@router.post("/{ride_id}/cancel")
def cancel_ride(
    ride_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    ride = db.exec(select(Ride).where(Ride.id == ride_id).with_for_update()).first()
    if ride is None or ride.rider_id != user_id:
        raise HTTPException(status_code=404, detail="Ride not found")

    if ride.status not in CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=409, detail="This ride can no longer be cancelled"
        )

    driver_id = ride.driver_id
    ride.status = RIDE_CANCELLED
    db.add(ride)
    db.commit()

    if driver_id is not None:
        publish_event_sync(driver_id, "ride_cancelled", {"ride_id": str(ride_id)})

    return {"ride_id": str(ride_id), "status": RIDE_CANCELLED}

@router.get("/history")
def ride_history(
    role: Literal["rider", "driver"] = Query("rider"),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])
    owner_column = Ride.rider_id if role == "rider" else Ride.driver_id

    total = db.exec(
        select(func.count(Ride.id)).where(owner_column == user_id)
    ).one()

    rows = db.exec(
        select(
            Ride.id,
            Ride.status,
            Ride.driver_id,
            Ride.fare_estimate,
            Ride.fare_actual,
            Ride.distance_meters,
            Ride.duration_secs,
            Ride.created_at,
        )
        .where(owner_column == user_id)
        .order_by(col(Ride.created_at).desc(), col(Ride.id))
        .offset(offset)
        .limit(limit)
    ).all()

    ride_ids = [row.id for row in rows]

    payment_status = {}
    if role == "rider" and rows:
        payments = db.exec(
            select(Payment.ride_id, Payment.status)
            .where(col(Payment.ride_id).in_(ride_ids))
            .order_by(col(Payment.created_at))
        ).all()
        for payment in payments:
            payment_status[payment.ride_id] = payment.status  # newest ends up last

    reviewed_ride_ids = set()
    if rows:
        reviewed_ride_ids = set(
            db.exec(
                select(Review.ride_id).where(
                    Review.rater_id == user_id,
                    col(Review.ride_id).in_(ride_ids),
                )
            ).all()
        )

    rides = []
    for row in rows:
        reviewed = row.id in reviewed_ride_ids
        has_other_party = role == "driver" or row.driver_id is not None
        item = {
            "ride_id": str(row.id),
            "status": row.status,
            "fare_estimate": row.fare_estimate,
            "fare_actual": row.fare_actual,
            "distance_meters": row.distance_meters,
            "duration_secs": row.duration_secs,
            "created_at": row.created_at.isoformat(),
            "reviewed": reviewed,
            "can_review": can_review_ride(row.status, has_other_party, reviewed),
        }
        if role == "rider":
            item["payment_status"] = payment_status.get(row.id)
        rides.append(item)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "currency": CURRENCY,
        "rides": rides,
    }

@router.get("/{ride_id}/receipt")
def ride_receipt(
    ride_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    try:
        return build_receipt(db, ride_id, user_id)
    except ReceiptNotFound:
        raise HTTPException(status_code=404, detail="Ride not found")
    except ReceiptNotReady:
        raise HTTPException(
            status_code=409, detail="No paid receipt exists for this ride yet"
        )

@router.get("/{ride_id}/receipt/pdf")
def ride_receipt_pdf(
    ride_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    try:
        receipt = build_receipt(db, ride_id, user_id)
    except ReceiptNotFound:
        raise HTTPException(status_code=404, detail="Ride not found")
    except ReceiptNotReady:
        raise HTTPException(
            status_code=409, detail="No paid receipt exists for this ride yet"
        )

    pdf_bytes = render_receipt_pdf(receipt)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{receipt["receipt_number"]}.pdf"',
            "Cache-Control": "no-store",
        },
    )

@router.post("/{ride_id}/receipt/email", status_code=202)
def email_receipt(
    ride_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    try:
        build_receipt(db, ride_id, user_id)  # checks ownership and that it is paid
    except ReceiptNotFound:
        raise HTTPException(status_code=404, detail="Ride not found")
    except ReceiptNotReady:
        raise HTTPException(
            status_code=409, detail="No paid receipt exists for this ride yet"
        )

    try:
        allowed = redis_sync.set(f"receipt-email:{ride_id}", "1", nx=True, ex=60)
    except Exception as e:
        print("Redis error (cooldown skipped):", e)
        allowed = True

    if not allowed:
        raise HTTPException(
            status_code=429, detail="A receipt was just emailed. Try again in a minute"
        )

    background_tasks.add_task(send_receipt_for_ride, ride_id, user_id)
    return {"queued": True}

class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5, strict=True)
    comment: Optional[str] = Field(default=None, max_length=500)

    @field_validator("comment")
    @classmethod
    def clean_comment(cls, value):
        if value is None:
            return None
        cleaned = "".join(
            ch
            for ch in value
            if ch in "\n\t" or unicodedata.category(ch) != "Cc"
        ).strip()
        return cleaned or None


@router.post("/{ride_id}/review", status_code=201, dependencies=[Depends(rate_limit("review", 10, 60))])
def review_ride(
    ride_id: uuid.UUID,
    body: ReviewCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    ride = db.get(Ride, ride_id)
    if ride is None or user_id not in (ride.rider_id, ride.driver_id):
        raise HTTPException(status_code=404, detail="Ride not found")

    if ride.status != RIDE_COMPLETED:
        raise HTTPException(
            status_code=409, detail="Only a completed ride can be reviewed"
        )

    if user_id == ride.rider_id:
        rated_id = ride.driver_id
        rated_role = "driver"
    else:
        rated_id = ride.rider_id
        rated_role = "rider"

    if rated_id is None:
        raise HTTPException(status_code=409, detail="This ride has nobody to review")

    existing = db.exec(
        select(Review).where(Review.ride_id == ride_id, Review.rater_id == user_id)
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="You already reviewed this ride")

    # Lock the reviewed user's row so two reviews of the same person take turns
    rated_user = db.exec(
        select(User).where(User.id == rated_id).with_for_update()
    ).first()
    if rated_user is None:
        raise HTTPException(status_code=409, detail="This ride has nobody to review")

    review = Review(
        ride_id=ride_id,
        rater_id=user_id,
        rated_id=rated_id,
        rating=body.rating,
        comment=body.comment,
    )
    review_id = review.id

    try:
        db.add(review)
        db.flush()  # send the insert now, so the average includes it
        rated_user.rating_avg = average_rating(db, rated_id)
        db.add(rated_user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already reviewed this ride")

    return {
        "review_id": str(review_id),
        "ride_id": str(ride_id),
        "rated_role": rated_role,
        "rating": body.rating,
        "comment": body.comment,
    }