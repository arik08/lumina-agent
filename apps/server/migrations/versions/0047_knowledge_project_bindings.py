"""add fixed Knowledge revision bindings for Projects

Revision ID: 0047
Revises: 0046
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

import lumina.models


revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_project_bindings",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_revision_id", sa.String(length=36), nullable=False),
        sa.Column("permission", sa.String(length=24), nullable=False),
        sa.Column("follow_latest_approved", sa.Boolean(), nullable=False),
        sa.Column("namespace_filters_json", sa.JSON(), nullable=False),
        sa.Column("tag_filters_json", sa.JSON(), nullable=False),
        sa.Column("binding_revision", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("updated_at", lumina.models.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_revision_id"],
            ["knowledge_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "space_id", name="uq_knowledge_project_bindings_scope"
        ),
    )
    op.create_index(
        "ix_knowledge_project_bindings_project_id",
        "knowledge_project_bindings",
        ["project_id"],
    )
    op.create_index(
        "ix_knowledge_project_bindings_space_id",
        "knowledge_project_bindings",
        ["space_id"],
    )
    op.create_index(
        "ix_knowledge_project_bindings_knowledge_revision_id",
        "knowledge_project_bindings",
        ["knowledge_revision_id"],
    )
    op.create_index(
        "ix_knowledge_project_bindings_space_revision",
        "knowledge_project_bindings",
        ["space_id", "knowledge_revision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_project_bindings_space_revision",
        table_name="knowledge_project_bindings",
    )
    op.drop_index(
        "ix_knowledge_project_bindings_knowledge_revision_id",
        table_name="knowledge_project_bindings",
    )
    op.drop_index(
        "ix_knowledge_project_bindings_space_id",
        table_name="knowledge_project_bindings",
    )
    op.drop_index(
        "ix_knowledge_project_bindings_project_id",
        table_name="knowledge_project_bindings",
    )
    op.drop_table("knowledge_project_bindings")
