"""MCP runtime credential header templates

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-11 22:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mcp_configuration_revisions",
        sa.Column(
            "allowed_ip_ranges_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "mcp_configuration_revisions",
        sa.Column(
            "header_templates_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_configuration_revisions", "header_templates_json")
    op.drop_column("mcp_configuration_revisions", "allowed_ip_ranges_json")
