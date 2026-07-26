"""remove per-node estimated cost

Revision ID: 0049
Revises: 0048
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deep_analysis_workflow_nodes") as batch_op:
        batch_op.drop_column("estimated_cost_microusd")


def downgrade() -> None:
    with op.batch_alter_table("deep_analysis_workflow_nodes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "estimated_cost_microusd",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            )
        )
