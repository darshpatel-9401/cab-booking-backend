import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

ROLE_RIDER = "rider"
ROLE_DRIVER = "driver"

DRIVER_ACTIVE = "active"
DRIVER_OFFLINE = "offline"

RIDE_REQUESTED = "requested"
RIDE_ACCEPTED = "accepted"
RIDE_IN_PROGRESS = "in_progress"
RIDE_COMPLETED = "completed"
RIDE_CANCELLED = "cancelled"

PAYMENT_PENDING = "pending"
PAYMENT_SUCCEEDED = "succeeded"
PAYMENT_FAILED = "failed"

DISCOUNT_PERCENT = "percent"
DISCOUNT_FIXED = "fixed"

REDEMPTION_RESERVED = "reserved"
REDEMPTION_REDEEMED = "redeemed"

WALLET_TOPUP = "topup"
WALLET_RIDE_PAYMENT = "ride_payment"

class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(primary_key=True)
    name: Optional[str] = Field(default=None)
    email: str = Field(unique=True, index=True)
    phone: Optional[str] = Field(default=None)
    role: str = Field(default=ROLE_RIDER)
    profile_pic: Optional[str] = Field(default=None)
    rating_avg: float = Field(default=0.0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Driver(SQLModel, table=True):
    __tablename__ = "drivers"
    __table_args__ = (
        Index(
            "ix_drivers_current_location",
            "current_location",
            postgresql_using="gist",
        ),
    )

    user_id: uuid.UUID = Field(foreign_key="users.id", primary_key=True)
    vehicle_info: Optional[str] = Field(default=None)
    verified: bool = Field(default=False)
    current_location: Optional[Any] = Field(
        default=None,
        sa_column=Column(
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False)
        ),
    )
    status: str = Field(default=DRIVER_OFFLINE)


class Ride(SQLModel, table=True):
    __tablename__ = "rides"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    rider_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    driver_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="drivers.user_id", index=True
    )
    pickup_point: Any = Field(
        sa_column=Column(
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        )
    )
    drop_point: Any = Field(
        sa_column=Column(
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        )
    )
    status: str = Field(default=RIDE_REQUESTED, index=True)
    fare_estimate: Optional[int] = Field(default=None)
    fare_actual: Optional[int] = Field(default=None)
    distance_meters: Optional[int] = Field(default=None)
    duration_secs: Optional[int] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Payment(SQLModel, table=True):
    __tablename__ = "payments"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ride_id: uuid.UUID = Field(foreign_key="rides.id", index=True)
    stripe_payment_intent_id: str = Field(unique=True, index=True)
    amount: int
    currency: str = Field(sa_column=Column(String(3), nullable=False))
    status: str = Field(default=PAYMENT_PENDING, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Review(SQLModel, table=True):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating_range"),
        CheckConstraint("rater_id <> rated_id", name="ck_reviews_no_self_review"),
        UniqueConstraint("ride_id", "rater_id", name="uq_reviews_ride_rater"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ride_id: uuid.UUID = Field(foreign_key="rides.id", index=True)
    rater_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    rated_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    rating: int
    comment: Optional[str] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

class PromoCode(SQLModel, table=True):
    __tablename__ = "promo_codes"
    __table_args__ = (
        CheckConstraint(
            "code ~ '^[A-Z0-9_-]{3,32}$'", name="ck_promo_codes_code_format"
        ),
        CheckConstraint(
            "(discount_type = 'percent' AND discount_value BETWEEN 1 AND 100) "
            "OR (discount_type = 'fixed' AND discount_value > 0 AND currency IS NOT NULL)",
            name="ck_promo_codes_type_and_value",
        ),
        CheckConstraint(
            "max_discount IS NULL OR max_discount > 0",
            name="ck_promo_codes_max_discount_positive",
        ),
        CheckConstraint(
            "max_total_uses IS NULL OR max_total_uses > 0",
            name="ck_promo_codes_max_total_uses_positive",
        ),
        CheckConstraint(
            "max_uses_per_user > 0", name="ck_promo_codes_per_user_positive"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, index=True)
    discount_type: str
    discount_value: int
    max_discount: Optional[int] = Field(default=None)
    currency: Optional[str] = Field(
        default=None, sa_column=Column(String(3), nullable=True)
    )
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    max_total_uses: Optional[int] = Field(default=None)
    max_uses_per_user: int = Field(default=1)
    active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PromoRedemption(SQLModel, table=True):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        CheckConstraint(
            "discount_amount > 0", name="ck_promo_redemptions_amount_positive"
        ),
        CheckConstraint(
            "status IN ('reserved', 'redeemed')", name="ck_promo_redemptions_status"
        ),
        UniqueConstraint("ride_id", name="uq_promo_redemptions_ride"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    promo_id: uuid.UUID = Field(foreign_key="promo_codes.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    ride_id: uuid.UUID = Field(foreign_key="rides.id")
    discount_amount: int
    status: str = Field(default=REDEMPTION_RESERVED)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

class Wallet(SQLModel, table=True):
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_wallets_balance_not_negative"),
        UniqueConstraint("user_id", "currency", name="uq_wallets_user_currency"),
    )

    user_id: uuid.UUID = Field(foreign_key="users.id", primary_key=True)
    currency: str = Field(sa_column=Column(String(3), nullable=False))
    balance: int = Field(default=0)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class WalletTransaction(SQLModel, table=True):
    __tablename__ = "wallet_transactions"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="ck_wallet_tx_amount_not_zero"),
        CheckConstraint(
            "(kind = 'topup' AND amount > 0) "
            "OR (kind = 'ride_payment' AND amount < 0)",
            name="ck_wallet_tx_kind_and_sign",
        ),
        CheckConstraint(
            "balance_after >= 0", name="ck_wallet_tx_balance_after_not_negative"
        ),
        ForeignKeyConstraint(
            ["user_id", "currency"],
            ["wallets.user_id", "wallets.currency"],
            name="fk_wallet_tx_wallet",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(index=True)
    currency: str = Field(sa_column=Column(String(3), nullable=False))
    kind: str
    amount: int
    balance_after: int
    idempotency_key: str = Field(unique=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
