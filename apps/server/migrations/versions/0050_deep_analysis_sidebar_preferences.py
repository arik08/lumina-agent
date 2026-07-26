"""add deep-analysis sidebar preferences

Revision ID: 0050
Revises: 0049
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deep_analysis_missions") as batch_op:
        batch_op.add_column(
            sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("is_liked", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("deep_analysis_missions") as batch_op:
        batch_op.drop_column("is_liked")
        batch_op.drop_column("is_favorite")
