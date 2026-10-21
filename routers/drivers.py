import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.elements import WKTElement
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select
from stripe_client import CURRENCY
from ratelimit import rate_limit

from auth import get_current_user
from database import get_session
from events import publish_event_sync
from matching import find_nearby_drivers
from models import (
    DRIVER_ACTIVE,
    RIDE_ACCEPTED,
    RIDE_IN_PROGRESS,
    ROLE_DRIVER,
    Driver,
    Ride,
    User,
)

router = APIRouter(prefix="/api/drivers", tags=["drivers"])


class DriverRegister(BaseModel):
    vehicle_info: str = Field(max_length=200)


class LocationUpdate(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class StatusUpdate(BaseModel):
    status: Literal["active", "offline"]


def get_registered_driver(user_id: uuid.UUID, db: Session) -> Driver:
    driver = db.get(Driver, user_id)
    if driver is None:
        raise HTTPException(status_code=403, detail="Register as a driver first")
    return driver


@router.post("/register", status_code=201, dependencies=[Depends(rate_limit("driver-register", 5, 60))])
def register_driver(
    body: DriverRegister,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    db_user = db.get(User, user_id)
    if db_user is None:
        raise HTTPException(
            status_code=400,
            detail="Profile not found. Call POST /api/auth/session first",
        )

    vehicle_info = body.vehicle_info.strip()
    if len(vehicle_info) < 2:
        raise HTTPException(status_code=400, detail="Vehicle info is too short")

    if db.get(Driver, user_id) is not None:
        raise HTTPException(status_code=409, detail="Already registered as a driver")

    driver = Driver(user_id=user_id, vehicle_info=vehicle_info)
    db_user.role = ROLE_DRIVER
    db.add(driver)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Already registered as a driver")

    return {
        "user_id": str(user_id),
        "vehicle_info": vehicle_info,
        "verified": False,
        "status": "offline",
        "role": ROLE_DRIVER,
    }


@router.put("/location", dependencies=[Depends(rate_limit("driver-location", 60, 60))])
def update_location(
    body: LocationUpdate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])
    driver = get_registered_driver(user_id, db)

    driver.current_location = WKTElement(
        f"POINT({body.lng:.7f} {body.lat:.7f})", srid=4326
    )
    db.add(driver)
    db.commit()

    active_ride = db.exec(
        select(Ride).where(
            Ride.driver_id == user_id,
            col(Ride.status).in_([RIDE_ACCEPTED, RIDE_IN_PROGRESS]),
        )
    ).first()
    if active_ride is not None:
        publish_event_sync(
            active_ride.rider_id,
            "driver_location",
            {"ride_id": str(active_ride.id), "lat": body.lat, "lng": body.lng},
        )

    return {"lat": body.lat, "lng": body.lng}


@router.put("/status")
def update_status(
    body: StatusUpdate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])
    driver = get_registered_driver(user_id, db)

    if body.status == DRIVER_ACTIVE:
        if not driver.verified:
            raise HTTPException(
                status_code=403, detail="Your driver account is not verified yet"
            )
        if driver.current_location is None:
            raise HTTPException(status_code=400, detail="Send your location first")

    driver.status = body.status
    db.add(driver)
    db.commit()

    return {"status": body.status}


@router.get("/nearby", dependencies=[Depends(rate_limit("nearby", 60, 60))])
def nearby_drivers(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_meters: int = Query(5000, ge=100, le=20000),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    drivers = find_nearby_drivers(
        db, lat, lng, radius_meters, exclude_user_id=uuid.UUID(user["id"])
    )
    return {
        "count": len(drivers),
        "drivers": [{"distance_meters": d["distance_meters"]} for d in drivers],
    }


CURRENT_RIDE_SQL = text(
    """
    SELECT
        id,
        status,
        fare_estimate,
        distance_meters,
        duration_secs,
        ST_Y(pickup_point) AS pickup_lat,
        ST_X(pickup_point) AS pickup_lng,
        ST_Y(drop_point) AS drop_lat,
        ST_X(drop_point) AS drop_lng
    FROM rides
    WHERE driver_id = :driver_id
      AND status IN ('accepted', 'in_progress')
    ORDER BY created_at DESC
    LIMIT 1
    """
)


@router.get("/current-ride")
def current_ride(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])
    get_registered_driver(user_id, db)

    row = (
        db.connection()
        .execute(CURRENT_RIDE_SQL, {"driver_id": str(user_id)})
        .mappings()
        .first()
    )
    if row is None:
        return {"ride": None}

    return {
        "ride": {
            "ride_id": str(row["id"]),
            "status": row["status"],
            "fare_estimate": row["fare_estimate"],
            "distance_meters": row["distance_meters"],
            "duration_secs": row["duration_secs"],
            "pickup": {"lat": row["pickup_lat"], "lng": row["pickup_lng"]},
            "drop": {"lat": row["drop_lat"], "lng": row["drop_lng"]},
        }
    }

DRIVER_LOCATION_SQL = text(
    """
    SELECT ST_Y(current_location) AS lat, ST_X(current_location) AS lng
    FROM drivers
    WHERE user_id = :driver_id
    """
)


@router.get("/me")
def driver_me(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])
    driver = get_registered_driver(user_id, db)

    row = (
        db.connection()
        .execute(DRIVER_LOCATION_SQL, {"driver_id": str(user_id)})
        .mappings()
        .first()
    )
    location = None
    if row is not None and row["lat"] is not None and row["lng"] is not None:
        location = {"lat": row["lat"], "lng": row["lng"]}

    return {
        "vehicle_info": driver.vehicle_info,
        "verified": driver.verified,
        "status": driver.status,
        "location": location,
        "currency": CURRENCY,
    }