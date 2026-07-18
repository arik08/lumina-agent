"""add durable Knowledge ingestion jobs

Revision ID: 0036
Revises: 0035
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

import lumina.models


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_ingestion_jobs",
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_revision_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("provider_id", sa.String(length=80), nullable=False),
        sa.Column("model_key", sa.String(length=160), nullable=False),
        sa.Column("runtime_model_id", sa.String(length=240), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column("input_segment_count", sa.Integer(), nullable=False),
        sa.Column("input_character_count", sa.Integer(), nullable=False),
        sa.Column("entity_count", sa.Integer(), nullable=False),
        sa.Column("statement_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("started_at", lumina.models.UTCDateTime(), nullable=True),
        sa.Column("finished_at", lumina.models.UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("updated_at", lumina.models.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["knowledge_source_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_space_id",
        "knowledge_ingestion_jobs",
        ["space_id"],
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_source_id",
        "knowledge_ingestion_jobs",
        ["source_id"],
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_source_revision_id",
        "knowledge_ingestion_jobs",
        ["source_revision_id"],
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_status",
        "knowledge_ingestion_jobs",
        ["status"],
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_space_status",
        "knowledge_ingestion_jobs",
        ["space_id", "status"],
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_source_revision",
        "knowledge_ingestion_jobs",
        ["source_revision_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_ingestion_jobs")
