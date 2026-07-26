"""add Artifact sources to Knowledge documents

Revision ID: 0065
Revises: 0064
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.add_column(
            sa.Column("source_artifact_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "source_artifact_version_id", sa.String(length=36), nullable=True
            )
        )
        batch_op.create_foreign_key(
            "fk_knowledge_documents_source_artifact",
            "artifacts",
            ["source_artifact_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_knowledge_documents_source_artifact_version",
            "artifact_versions",
            ["source_artifact_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_knowledge_documents_source_artifact_id",
            ["source_artifact_id"],
        )
        batch_op.create_index(
            "ix_knowledge_documents_source_artifact_version_id",
            ["source_artifact_version_id"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.drop_index("ix_knowledge_documents_source_artifact_version_id")
        batch_op.drop_index("ix_knowledge_documents_source_artifact_id")
        batch_op.drop_constraint(
            "fk_knowledge_documents_source_artifact_version",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_knowledge_documents_source_artifact",
            type_="foreignkey",
        )
        batch_op.drop_column("source_artifact_version_id")
        batch_op.drop_column("source_artifact_id")
