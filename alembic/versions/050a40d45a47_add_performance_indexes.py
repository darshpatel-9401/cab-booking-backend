"""add performance indexes

Revision ID: 050a40d45a47
Revises: 5c99f19bc809
Create Date: 2026-10-22 03:14:09.252897

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = '050a40d45a47'
down_revision: Union[str, Sequence[str], None] = '5c99f19bc809'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_perf_rides_rider_created ON rides (rider_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_perf_rides_driver_created ON rides (driver_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_perf_rides_driver_status ON rides (driver_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_perf_reviews_rated_created ON reviews (rated_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_perf_wallet_tx_user_created ON wallet_transactions (user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_perf_drivers_location_geog ON drivers USING gist ((current_location::geography))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_perf_drivers_location_geog")
    op.execute("DROP INDEX IF EXISTS ix_perf_wallet_tx_user_created")
    op.execute("DROP INDEX IF EXISTS ix_perf_reviews_rated_created")
    op.execute("DROP INDEX IF EXISTS ix_perf_rides_driver_status")
    op.execute("DROP INDEX IF EXISTS ix_perf_rides_driver_created")
    op.execute("DROP INDEX IF EXISTS ix_perf_rides_rider_created")