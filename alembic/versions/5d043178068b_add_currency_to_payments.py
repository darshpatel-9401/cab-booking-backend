"""add currency to payments

Revision ID: 5d043178068b
Revises: 214a7e1b34e6
Create Date: 2026-10-17 13:12:37.527458

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = '5d043178068b'
down_revision: Union[str, Sequence[str], None] = '214a7e1b34e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("currency", sa.String(length=3), nullable=True))
    # Existing rows are test payments. Set this to the same value as STRIPE_CURRENCY in your .env
    op.execute("UPDATE payments SET currency = 'inr'")
    op.alter_column("payments", "currency", nullable=False)


def downgrade() -> None:
    op.drop_column("payments", "currency")
