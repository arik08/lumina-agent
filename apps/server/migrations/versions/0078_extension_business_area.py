"""Persist the Skill business-area folder classification.

Revision ID: 0078
Revises: 0077
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extensions") as batch_op:
        batch_op.add_column(sa.Column("business_area", sa.String(length=24), nullable=True))
        batch_op.create_index("ix_extensions_business_area", ["business_area"])


def downgrade() -> None:
    with op.batch_alter_table("extensions") as batch_op:
        batch_op.drop_index("ix_extensions_business_area")
        batch_op.drop_column("business_area")
