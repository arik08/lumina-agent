"""Add account-scoped Knowledge core tables.

Revision ID: 0035
Revises: 0034
"""

from alembic import op
import lumina.models
import sqlalchemy as sa


revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_spaces",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("space_type", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("settings_revision", sa.Integer(), nullable=False),
        sa.Column("archived_at", lumina.models.UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("updated_at", lumina.models.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_spaces_organization_id", "knowledge_spaces", ["organization_id"]
    )
    op.create_index(
        "ix_knowledge_spaces_owner_user_id", "knowledge_spaces", ["owner_user_id"]
    )
    op.create_index("ix_knowledge_spaces_status", "knowledge_spaces", ["status"])
    op.create_index(
        "ix_knowledge_spaces_owner_activity",
        "knowledge_spaces",
        ["owner_user_id", "updated_at"],
    )

    op.create_table(
        "knowledge_revisions",
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("approved_at", lumina.models.UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"], ["knowledge_revisions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "space_id", "revision_number", name="uq_knowledge_revisions_number"
        ),
    )
    op.create_index(
        "ix_knowledge_revisions_space_id", "knowledge_revisions", ["space_id"]
    )
    op.create_index(
        "ix_knowledge_revisions_parent_revision_id",
        "knowledge_revisions",
        ["parent_revision_id"],
    )
    op.create_index(
        "ix_knowledge_revisions_space_status",
        "knowledge_revisions",
        ["space_id", "status"],
    )

    op.create_table(
        "knowledge_sources",
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("canonical_locator", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("updated_at", lumina.models.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_sources_space_id", "knowledge_sources", ["space_id"])
    op.create_index("ix_knowledge_sources_status", "knowledge_sources", ["status"])
    op.create_index(
        "ix_knowledge_sources_space_status",
        "knowledge_sources",
        ["space_id", "status"],
    )

    op.create_table(
        "knowledge_source_revisions",
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=200), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_reference", sa.Text(), nullable=True),
        sa.Column("captured_text", sa.Text(), nullable=True),
        sa.Column("parser_name", sa.String(length=120), nullable=True),
        sa.Column("parser_version", sa.String(length=80), nullable=True),
        sa.Column("parse_digest", sa.String(length=64), nullable=True),
        sa.Column("supersedes_revision_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("captured_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_revision_id"],
            ["knowledge_source_revisions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "revision_number",
            name="uq_knowledge_source_revisions_number",
        ),
        sa.UniqueConstraint(
            "source_id",
            "content_digest",
            name="uq_knowledge_source_revisions_digest",
        ),
    )
    op.create_index(
        "ix_knowledge_source_revisions_source_id",
        "knowledge_source_revisions",
        ["source_id"],
    )
    op.create_index(
        "ix_knowledge_source_revisions_supersedes_revision_id",
        "knowledge_source_revisions",
        ["supersedes_revision_id"],
    )
    op.create_index(
        "ix_knowledge_source_revisions_digest",
        "knowledge_source_revisions",
        ["content_digest"],
    )

    op.create_table(
        "knowledge_evidence_segments",
        sa.Column("source_revision_id", sa.String(length=36), nullable=False),
        sa.Column("segment_ordinal", sa.Integer(), nullable=False),
        sa.Column("locator_json", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_digest", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["knowledge_source_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_revision_id",
            "segment_ordinal",
            name="uq_knowledge_evidence_segments_ordinal",
        ),
    )
    op.create_index(
        "ix_knowledge_evidence_segments_source_revision_id",
        "knowledge_evidence_segments",
        ["source_revision_id"],
    )
    op.create_index(
        "ix_knowledge_evidence_segments_revision_digest",
        "knowledge_evidence_segments",
        ["source_revision_id", "text_digest"],
    )

    op.create_table(
        "knowledge_entities",
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("canonical_name", sa.String(length=500), nullable=False),
        sa.Column("normalized_key", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("merged_into_entity_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("updated_at", lumina.models.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["merged_into_entity_id"], ["knowledge_entities.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "space_id",
            "normalized_key",
            "entity_type",
            name="uq_knowledge_entities_normalized_type",
        ),
    )
    op.create_index(
        "ix_knowledge_entities_space_id", "knowledge_entities", ["space_id"]
    )
    op.create_index("ix_knowledge_entities_status", "knowledge_entities", ["status"])
    op.create_index(
        "ix_knowledge_entities_merged_into_entity_id",
        "knowledge_entities",
        ["merged_into_entity_id"],
    )
    op.create_index(
        "ix_knowledge_entities_space_name",
        "knowledge_entities",
        ["space_id", "canonical_name"],
    )

    op.create_table(
        "knowledge_statements",
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("subject_entity_id", sa.String(length=36), nullable=False),
        sa.Column("predicate_key", sa.String(length=160), nullable=False),
        sa.Column("object_kind", sa.String(length=24), nullable=False),
        sa.Column("object_entity_id", sa.String(length=36), nullable=True),
        sa.Column("object_value_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("rank", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("valid_from", lumina.models.UTCDateTime(), nullable=True),
        sa.Column("valid_to", lumina.models.UTCDateTime(), nullable=True),
        sa.Column("recorded_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("created_by_type", sa.String(length=24), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_run_id", sa.String(length=36), nullable=True),
        sa.Column("supersedes_statement_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_run_id"], ["runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["object_entity_id"], ["knowledge_entities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["knowledge_revisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["subject_entity_id"], ["knowledge_entities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_statement_id"],
            ["knowledge_statements.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_statements_space_id", "knowledge_statements", ["space_id"]
    )
    op.create_index(
        "ix_knowledge_statements_revision_id", "knowledge_statements", ["revision_id"]
    )
    op.create_index(
        "ix_knowledge_statements_status", "knowledge_statements", ["status"]
    )
    op.create_index(
        "ix_knowledge_statements_supersedes_statement_id",
        "knowledge_statements",
        ["supersedes_statement_id"],
    )
    op.create_index(
        "ix_knowledge_statements_space_subject",
        "knowledge_statements",
        ["space_id", "subject_entity_id"],
    )
    op.create_index(
        "ix_knowledge_statements_space_object",
        "knowledge_statements",
        ["space_id", "object_entity_id"],
    )
    op.create_index(
        "ix_knowledge_statements_space_predicate",
        "knowledge_statements",
        ["space_id", "predicate_key"],
    )

    op.create_table(
        "knowledge_statement_evidence",
        sa.Column("statement_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_segment_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_segment_id"],
            ["knowledge_evidence_segments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["statement_id"], ["knowledge_statements.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("statement_id", "evidence_segment_id"),
    )
    op.create_index(
        "ix_knowledge_statement_evidence_evidence_segment_id",
        "knowledge_statement_evidence",
        ["evidence_segment_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_statement_evidence_evidence_segment_id",
        table_name="knowledge_statement_evidence",
    )
    op.drop_table("knowledge_statement_evidence")
    op.drop_table("knowledge_statements")
    op.drop_table("knowledge_entities")
    op.drop_table("knowledge_evidence_segments")
    op.drop_table("knowledge_source_revisions")
    op.drop_table("knowledge_sources")
    op.drop_table("knowledge_revisions")
    op.drop_table("knowledge_spaces")
