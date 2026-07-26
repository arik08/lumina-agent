"""add Knowledge tag proposals

Revision ID: 0064
Revises: 0063
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_tag_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("namespace", sa.String(length=80), nullable=False),
        sa.Column("canonical_name", sa.String(length=160), nullable=False),
        sa.Column("normalized_name", sa.String(length=160), nullable=False),
        sa.Column("scope_note", sa.Text(), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.Column("document_ids_json", sa.JSON(), nullable=False),
        sa.Column("provider_id", sa.String(length=120), nullable=False),
        sa.Column("model_key", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("resolved_tag_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_tag_id"], ["knowledge_tags.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("space_id", "namespace", "normalized_name", name="uq_knowledge_tag_proposals_name"),
    )
    op.create_index("ix_knowledge_tag_proposals_space_id", "knowledge_tag_proposals", ["space_id"])
    op.create_index("ix_knowledge_tag_proposals_status", "knowledge_tag_proposals", ["status"])
    op.create_index("ix_knowledge_tag_proposals_resolved_tag_id", "knowledge_tag_proposals", ["resolved_tag_id"])
    op.create_index("ix_knowledge_tag_proposals_resolved_by_user_id", "knowledge_tag_proposals", ["resolved_by_user_id"])
    op.create_index(
        "ix_knowledge_tag_proposals_space_status",
        "knowledge_tag_proposals",
        ["space_id", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_tag_proposals")
