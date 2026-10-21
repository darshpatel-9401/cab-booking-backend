import uuid

from routers.rides import router as rides_router
from routers.drivers import router as drivers_router
from routers.ws import router as ws_router
from routers.payments import router as payments_router
from routers.reviews import router as reviews_router
from routers.webhooks import router as webhooks_router
from routers.promos import router as promos_router
from routers.wallet import router as wallet_router

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from auth import get_current_user
from database import engine, get_session
from redis_client import redis_client
from stripe_client import CURRENCY, stripe
from models import User

app = FastAPI(title="Cab Booking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rides_router)
app.include_router(drivers_router)
app.include_router(ws_router)
app.include_router(payments_router)
app.include_router(reviews_router)
app.include_router(webhooks_router)
app.include_router(promos_router)
app.include_router(wallet_router)

@app.get("/")
def root():
    return {"message": "Cab Booking API is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"database": "connected"}
    except Exception as e:
        print("Database error:", e)
        raise HTTPException(status_code=500, detail="Database connection failed")


@app.get("/health/postgis")
def health_postgis():
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT postgis_version()")).scalar()
        return {"postgis": version}
    except Exception as e:
        print("PostGIS error:", e)
        raise HTTPException(status_code=500, detail="PostGIS not available")

@app.get("/health/redis")
async def health_redis():
    try:
        await redis_client.set("health:check", "ok", ex=30)
        value = await redis_client.get("health:check")
        return {"redis": "connected", "roundtrip": value}
    except Exception as e:
        print("Redis error:", e)
        raise HTTPException(status_code=500, detail="Redis connection failed")

@app.get("/health/stripe")
def health_stripe():
    try:
        balance = stripe.Balance.retrieve()
        return {
            "stripe": "connected",
            "livemode": balance.livemode,
            "currency": CURRENCY,
        }
    except Exception as e:
        print("Stripe error:", e)
        raise HTTPException(status_code=500, detail="Stripe connection failed")

@app.get("/api/me")
def read_me(user: dict = Depends(get_current_user)):
    return {"user": user}


@app.post("/api/auth/session")
def create_session(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user_id = uuid.UUID(user["id"])
    db_user = db.get(User, user_id)

    if db_user is None:
        if not user["email"]:
            raise HTTPException(status_code=400, detail="Token has no email")

        db_user = User(id=user_id, email=user["email"])
        db.add(db_user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            db_user = db.get(User, user_id)
            if db_user is None:
                raise HTTPException(
                    status_code=409, detail="A user with this email already exists"
                )
        else:
            db.refresh(db_user)

    return {
        "id": str(db_user.id),
        "email": db_user.email,
        "name": db_user.name,
        "role": db_user.role,
        "rating_avg": db_user.rating_avg,
    }