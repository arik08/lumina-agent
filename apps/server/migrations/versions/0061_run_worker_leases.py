"""add durable run worker leases

Revision ID: 0061
Revises: 0060
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from lumina.models import UTCDateTime


revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("worker_id", sa.String(length=36)))
    op.add_column("runs", sa.Column("heartbeat_at", UTCDateTime()))
    op.add_column("runs", sa.Column("lease_expires_at", UTCDateTime()))
    op.execute(
        """
        UPDATE runs
        SET worker_id = json_extract(snapshot_json, '$.workerId')
        WHERE worker_id IS NULL
          AND snapshot_json IS NOT NULL
          AND json_valid(snapshot_json)
        """
        if op.get_bind().dialect.name == "sqlite"
        else """
        UPDATE runs
        SET worker_id = snapshot_json ->> 'workerId'
        WHERE worker_id IS NULL
          AND snapshot_json IS NOT NULL
        """
    )
    op.create_index(
        "ix_runs_worker_lease",
        "runs",
        ["worker_id", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_runs_worker_lease", table_name="runs")
    op.drop_column("runs", "lease_expires_at")
    op.drop_column("runs", "heartbeat_at")
    op.drop_column("runs", "worker_id")
