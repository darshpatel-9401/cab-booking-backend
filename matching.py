import uuid
from typing import Optional

from sqlalchemy import text
from sqlmodel import Session, col, select

from models import (
    DRIVER_ACTIVE,
    RIDE_ACCEPTED,
    RIDE_IN_PROGRESS,
    Driver,
    Ride,
)

BUSY_RIDE_STATUSES = [RIDE_ACCEPTED, RIDE_IN_PROGRESS]

NEARBY_SQL = text(
    """
    SELECT
        d.user_id,
        d.vehicle_info,
        ST_Distance(
            d.current_location::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
        ) AS distance_meters
    FROM drivers d
    WHERE d.status = 'active'
      AND d.verified = true
      AND d.current_location IS NOT NULL
      AND ST_DWithin(
            d.current_location::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            :radius
      )
      AND (
            CAST(:exclude_id AS uuid) IS NULL
            OR d.user_id <> CAST(:exclude_id AS uuid)
      )
      AND NOT EXISTS (
            SELECT 1 FROM rides r
            WHERE r.driver_id = d.user_id
              AND r.status IN ('accepted', 'in_progress')
      )
    ORDER BY distance_meters
    LIMIT :limit
    """
)

PICKUP_SQL = text(
    """
    SELECT ST_Y(pickup_point) AS lat, ST_X(pickup_point) AS lng
    FROM rides
    WHERE id = :ride_id
    """
)


def find_nearby_drivers(
    db: Session,
    lat: float,
    lng: float,
    radius_meters: int = 5000,
    limit: int = 10,
    exclude_user_id: Optional[uuid.UUID] = None,
):
    params = {
        "lat": lat,
        "lng": lng,
        "radius": radius_meters,
        "limit": limit,
        "exclude_id": str(exclude_user_id) if exclude_user_id else None,
    }
    rows = db.connection().execute(NEARBY_SQL, params).mappings().all()

    return [
        {
            "driver_id": str(row["user_id"]),
            "vehicle_info": row["vehicle_info"],
            "distance_meters": round(row["distance_meters"]),
        }
        for row in rows
    ]


def assign_nearest_driver(db: Session, ride: Ride, radius_meters: int = 5000):
    pickup = (
        db.connection().execute(PICKUP_SQL, {"ride_id": str(ride.id)}).mappings().first()
    )

    candidates = find_nearby_drivers(
        db,
        pickup["lat"],
        pickup["lng"],
        radius_meters=radius_meters,
        limit=5,
        exclude_user_id=ride.rider_id,
    )

    for candidate in candidates:
        driver_id = uuid.UUID(candidate["driver_id"])

        # Lock this driver's row so no other request can assign them right now
        driver = db.exec(
            select(Driver).where(Driver.user_id == driver_id).with_for_update()
        ).first()
        if driver is None or driver.status != DRIVER_ACTIVE or not driver.verified:
            continue

        busy_ride = db.exec(
            select(Ride).where(
                Ride.driver_id == driver_id,
                col(Ride.status).in_(BUSY_RIDE_STATUSES),
            )
        ).first()
        if busy_ride is not None:
            continue

        ride.driver_id = driver_id
        ride.status = RIDE_ACCEPTED
        db.add(ride)
        db.commit()
        return candidate

    return None