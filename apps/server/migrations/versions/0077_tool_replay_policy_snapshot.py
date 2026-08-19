"""Persist the replay contract used by each Tool execution.

Revision ID: 0077
Revises: 0076
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tool_executions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "replay_policy_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tool_executions") as batch_op:
        batch_op.drop_column("replay_policy_json")
