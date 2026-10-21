import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlmodel import Session, col, select

from auth import get_current_user
from database import get_session
from models import (
    RIDE_ACCEPTED,
    RIDE_COMPLETED,
    RIDE_IN_PROGRESS,
    Review,
    Ride,
    User,
)
from ratings import distribution_from_rows

router = APIRouter(prefix="/api", tags=["reviews"])

SHARED_RIDE_STATUSES = [RIDE_ACCEPTED, RIDE_IN_PROGRESS, RIDE_COMPLETED]


def can_view_rating(db: Session, viewer_id: uuid.UUID, target_id: uuid.UUID) -> bool:
    if viewer_id == target_id:
        return True

    shared_ride = db.exec(
        select(Ride.id)
        .where(
            col(Ride.status).in_(SHARED_RIDE_STATUSES),
            or_(
                and_(Ride.rider_id == viewer_id, Ride.driver_id == target_id),
                and_(Ride.rider_id == target_id, Ride.driver_id == viewer_id),
            ),
        )
        .limit(1)
    ).first()
    return shared_ride is not None


@router.get("/users/{user_id}/rating")
def user_rating(
    user_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    viewer_id = uuid.UUID(user["id"])

    target = db.get(User, user_id)
    if target is None or not can_view_rating(db, viewer_id, user_id):
        raise HTTPException(status_code=404, detail="User not found")

    rows = db.exec(
        select(Review.rating, func.count(Review.id))
        .where(Review.rated_id == user_id)
        .group_by(Review.rating)
    ).all()
    distribution = distribution_from_rows(rows)
    review_count = sum(distribution.values())

    return {
        "user_id": str(user_id),
        "rating_avg": target.rating_avg if review_count else None,
        "review_count": review_count,
        "distribution": distribution,
    }


@router.get("/reviews/received")
def received_reviews(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    total = db.exec(
        select(func.count(Review.id)).where(Review.rated_id == user_id)
    ).one()

    rows = db.exec(
        select(
            Review.id,
            Review.ride_id,
            Review.rating,
            Review.comment,
            Review.created_at,
            Review.rater_id,
            Ride.rider_id,
        )
        .select_from(Review)
        .join(Ride, Ride.id == Review.ride_id)
        .where(Review.rated_id == user_id)
        .order_by(col(Review.created_at).desc(), col(Review.id))
        .offset(offset)
        .limit(limit)
    ).all()

    reviews = [
        {
            "review_id": str(row.id),
            "ride_id": str(row.ride_id),
            "rating": row.rating,
            "comment": row.comment,
            "from_role": "rider" if row.rater_id == row.rider_id else "driver",
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]

    return {"total": total, "limit": limit, "offset": offset, "reviews": reviews}