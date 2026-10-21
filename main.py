import time
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session
from starlette.datastructures import MutableHeaders

from auth import get_current_user
from config import ALLOWED_ORIGINS, ENABLE_DOCS
from database import engine, get_session
from models import User
from ratelimit import rate_limit
from redis_client import redis_sync
from routers.drivers import router as drivers_router
from routers.payments import router as payments_router
from routers.promos import router as promos_router
from routers.reviews import router as reviews_router
from routers.rides import router as rides_router
from routers.wallet import router as wallet_router
from routers.webhooks import router as webhooks_router
from routers.ws import router as ws_router


class SecurityHeadersMiddleware:
    """Adds safe default headers to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
                if path.startswith("/api/"):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


app = FastAPI(
    title="Cab Booking API",
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(rides_router)
app.include_router(drivers_router)
app.include_router(ws_router)
app.include_router(payments_router)
app.include_router(webhooks_router)
app.include_router(reviews_router)
app.include_router(promos_router)
app.include_router(wallet_router)

_ready_cache = {"at": 0.0, "code": 200, "body": {}}


@app.get("/")
def root():
    return {"message": "Cab Booking API is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    # Cached for 10 seconds, so this open route can't be used to hammer the database
    now = time.monotonic()
    if _ready_cache["body"] and now - _ready_cache["at"] < 10:
        return JSONResponse(
            status_code=_ready_cache["code"], content=_ready_cache["body"]
        )

    status = {"database": "ok", "redis": "ok"}

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        print("Readiness check: database failed:", e)
        status["database"] = "failed"

    try:
        redis_sync.ping()
    except Exception as e:
        print("Readiness check: redis failed:", e)
        status["redis"] = "failed"

    code = 200 if all(value == "ok" for value in status.values()) else 503
    _ready_cache.update(at=now, code=code, body=status)
    return JSONResponse(status_code=code, content=status)


@app.get("/api/me")
def read_me(user: dict = Depends(get_current_user)):
    return {"user": user}


@app.post(
    "/api/auth/session",
    dependencies=[Depends(rate_limit("auth-session", 30, 60))],
)
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