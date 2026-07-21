"""add Knowledge retrieval use mode

Revision ID: 0063
Revises: 0062
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_spaces") as batch_op:
        batch_op.add_column(
            sa.Column(
                "use_mode",
                sa.String(length=16),
                nullable=False,
                server_default="auto",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_spaces") as batch_op:
        batch_op.drop_column("use_mode")
