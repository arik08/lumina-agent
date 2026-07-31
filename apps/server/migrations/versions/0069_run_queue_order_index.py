"""Index deterministic run queue order.

Revision ID: 0069
Revises: 0068
"""

from __future__ import annotations

from alembic import op


revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.create_index(
                "ix_runs_queue_order",
                "runs",
                ["status", "queued_at", "id"],
                unique=False,
                postgresql_concurrently=True,
            )
    else:
        op.create_index(
            "ix_runs_queue_order",
            "runs",
            ["status", "queued_at", "id"],
            unique=False,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(
                "ix_runs_queue_order",
                table_name="runs",
                postgresql_concurrently=True,
            )
    else:
        op.drop_index("ix_runs_queue_order", table_name="runs")
