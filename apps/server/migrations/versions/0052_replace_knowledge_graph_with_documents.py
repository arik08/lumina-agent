"""replace entity knowledge graph with document knowledge graph

Revision ID: 0052
Revises: 0051
"""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

from alembic import context, op
import sqlalchemy as sa

import lumina.models


revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


_LEGACY_FTS = (
    ("knowledge_entity_fts", "knowledge_entities"),
    ("knowledge_statement_fts", "knowledge_statements"),
    ("knowledge_source_fts", "knowledge_sources"),
    ("knowledge_evidence_fts", "knowledge_evidence_segments"),
)


def upgrade() -> None:
    if context.get_context().dialect.name == "sqlite":
        for index_name, content_table in _LEGACY_FTS:
            for suffix in ("au", "ad", "ai"):
                op.execute(f"DROP TRIGGER IF EXISTS trg_{content_table}_fts_{suffix}")
            op.execute(f"DROP TABLE IF EXISTS {index_name}")

    for table_name in (
        "knowledge_statement_evidence",
        "knowledge_page_revisions",
        "knowledge_pages",
        "knowledge_statements",
        "knowledge_entities",
        "knowledge_project_bindings",
        "knowledge_ingestion_jobs",
        "knowledge_evidence_segments",
        "knowledge_source_revisions",
        "knowledge_sources",
        "knowledge_revisions",
    ):
        op.drop_table(table_name)

    op.create_table(
        "knowledge_documents",
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("source_message_id", sa.String(length=36), nullable=True),
        sa.Column("source_run_id", sa.String(length=36), nullable=True),
        sa.Column("source_conversation_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("researched_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("citations_json", sa.JSON(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("updated_at", lumina.models.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_message_id", name="uq_knowledge_documents_source_message"),
    )
    op.create_index("ix_knowledge_documents_space_id", "knowledge_documents", ["space_id"])
    op.create_index("ix_knowledge_documents_project_id", "knowledge_documents", ["project_id"])
    op.create_index("ix_knowledge_documents_owner_user_id", "knowledge_documents", ["owner_user_id"])
    op.create_index("ix_knowledge_documents_source_message_id", "knowledge_documents", ["source_message_id"])
    op.create_index("ix_knowledge_documents_source_run_id", "knowledge_documents", ["source_run_id"])
    op.create_index("ix_knowledge_documents_source_conversation_id", "knowledge_documents", ["source_conversation_id"])
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])
    op.create_index("ix_knowledge_documents_space_researched", "knowledge_documents", ["space_id", "researched_at"])
    op.create_index("ix_knowledge_documents_project_researched", "knowledge_documents", ["project_id", "researched_at"])

    op.create_table(
        "knowledge_tags",
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("namespace", sa.String(length=80), nullable=False),
        sa.Column("canonical_name", sa.String(length=160), nullable=False),
        sa.Column("normalized_name", sa.String(length=160), nullable=False),
        sa.Column("scope_note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("updated_at", lumina.models.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("space_id", "namespace", "normalized_name", name="uq_knowledge_tags_name"),
    )
    op.create_index("ix_knowledge_tags_space_id", "knowledge_tags", ["space_id"])
    op.create_index("ix_knowledge_tags_status", "knowledge_tags", ["status"])
    op.create_index("ix_knowledge_tags_space_name", "knowledge_tags", ["space_id", "canonical_name"])

    op.create_table(
        "knowledge_tag_aliases",
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.Column("normalized_alias", sa.String(length=160), nullable=False),
        sa.Column("alias", sa.String(length=160), nullable=False),
        sa.Column("language", sa.String(length=24), nullable=True),
        sa.ForeignKeyConstraint(["tag_id"], ["knowledge_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tag_id", "normalized_alias"),
    )

    op.create_table(
        "knowledge_document_tags",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["knowledge_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id", "tag_id"),
    )
    op.create_index("ix_knowledge_document_tags_tag_id", "knowledge_document_tags", ["tag_id"])


def downgrade() -> None:
    # The forward migration intentionally discards incompatible Knowledge data.
    # Downgrade restores the previous *empty schema* so older migration round-trip
    # tests and local recovery remain usable; deleted Entity/Statement data cannot
    # be reconstructed.
    op.drop_index("ix_knowledge_document_tags_tag_id", table_name="knowledge_document_tags")
    op.drop_table("knowledge_document_tags")
    op.drop_table("knowledge_tag_aliases")
    op.drop_index("ix_knowledge_tags_space_name", table_name="knowledge_tags")
    op.drop_index("ix_knowledge_tags_status", table_name="knowledge_tags")
    op.drop_index("ix_knowledge_tags_space_id", table_name="knowledge_tags")
    op.drop_table("knowledge_tags")
    for index_name in (
        "ix_knowledge_documents_project_researched",
        "ix_knowledge_documents_space_researched",
        "ix_knowledge_documents_status",
        "ix_knowledge_documents_source_conversation_id",
        "ix_knowledge_documents_source_run_id",
        "ix_knowledge_documents_source_message_id",
        "ix_knowledge_documents_owner_user_id",
        "ix_knowledge_documents_project_id",
        "ix_knowledge_documents_space_id",
    ):
        op.drop_index(index_name, table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("ix_knowledge_spaces_owner_activity", table_name="knowledge_spaces")
    op.drop_index("ix_knowledge_spaces_status", table_name="knowledge_spaces")
    op.drop_index("ix_knowledge_spaces_owner_user_id", table_name="knowledge_spaces")
    op.drop_index("ix_knowledge_spaces_organization_id", table_name="knowledge_spaces")
    op.drop_table("knowledge_spaces")

    versions_dir = Path(__file__).parent
    for filename in (
        "0035_knowledge_core.py",
        "0045_knowledge_ingestion_jobs.py",
        "0046_knowledge_wiki_pages.py",
        "0047_knowledge_project_bindings.py",
        "0048_knowledge_sqlite_fts.py",
    ):
        run_path(str(versions_dir / filename))["upgrade"]()
