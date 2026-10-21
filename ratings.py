import uuid

from sqlalchemy import func
from sqlmodel import Session, select

from models import RIDE_COMPLETED, Review


def average_rating(db: Session, user_id: uuid.UUID) -> float:
    average = db.exec(
        select(func.avg(Review.rating)).where(Review.rated_id == user_id)
    ).one()
    if average is None:
        return 0.0
    return round(float(average), 2)


def distribution_from_rows(rows) -> dict:
    """rows is a list of (rating, count) pairs. Always returns keys "1" to "5"."""
    distribution = {str(n): 0 for n in range(1, 6)}
    for rating, count in rows:
        distribution[str(rating)] = count
    return distribution

def can_review_ride(status: str, has_other_party: bool, reviewed: bool) -> bool:
    return status == RIDE_COMPLETED and has_other_party and not reviewed