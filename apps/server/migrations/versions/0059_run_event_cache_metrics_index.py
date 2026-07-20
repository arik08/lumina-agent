"""index run events for per-run metric aggregation

Revision ID: 0059
Revises: 0058
"""

from __future__ import annotations

from alembic import op


revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_run_events_run_type",
        "run_events",
        ["run_id", "event_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_run_events_run_type", table_name="run_events")
