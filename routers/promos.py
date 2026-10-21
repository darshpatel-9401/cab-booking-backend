import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from auth import get_current_user
from database import get_session
from promos import PromoError, evaluate_promo
from stripe_client import CURRENCY

router = APIRouter(prefix="/api/promos", tags=["promos"])


class PromoPreview(BaseModel):
    ride_id: uuid.UUID
    code: str = Field(min_length=1, max_length=64)


@router.post("/preview")
def preview_promo(
    body: PromoPreview,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])

    try:
        result = evaluate_promo(db, body.ride_id, user_id, body.code, CURRENCY)
    except PromoError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    fare = result["fare"]
    discount = result["discount"]
    return {
        "code": result["promo"].code,
        "original_amount": fare,
        "discount_amount": discount,
        "final_amount": fare - discount,
        "currency": CURRENCY,
    }