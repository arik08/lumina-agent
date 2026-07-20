"""add skill version history metadata

Revision ID: 0062
Revises: 0061
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extension_versions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "change_summary",
                sa.String(length=500),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(
            sa.Column(
                "change_type",
                sa.String(length=24),
                nullable=False,
                server_default="save",
            )
        )
        batch_op.add_column(sa.Column("restored_from_version_id", sa.String(length=36)))
        batch_op.create_foreign_key(
            "fk_extension_versions_restored_from_version_id",
            "extension_versions",
            ["restored_from_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_extension_versions_restored_from_version_id",
            ["restored_from_version_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("extension_versions") as batch_op:
        batch_op.drop_index("ix_extension_versions_restored_from_version_id")
        batch_op.drop_constraint(
            "fk_extension_versions_restored_from_version_id", type_="foreignkey"
        )
        batch_op.drop_column("restored_from_version_id")
        batch_op.drop_column("change_type")
        batch_op.drop_column("change_summary")
