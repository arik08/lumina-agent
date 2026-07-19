"""add deep-analysis export cooldown timestamp

Revision ID: 0051
Revises: 0050
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import lumina.models


revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deep_analysis_missions",
        sa.Column(
            "last_export_requested_at",
            lumina.models.UTCDateTime(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("deep_analysis_missions", "last_export_requested_at")
