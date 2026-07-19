"""store deep analysis execution settings

Revision ID: 0057
Revises: 0056
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deep_analysis_missions",
        sa.Column(
            "execution_settings_json", sa.JSON(), nullable=False, server_default="{}"
        ),
    )


def downgrade() -> None:
    op.drop_column("deep_analysis_missions", "execution_settings_json")
