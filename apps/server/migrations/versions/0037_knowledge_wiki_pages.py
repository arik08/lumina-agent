"""add durable Knowledge wiki pages and revisions

Revision ID: 0037
Revises: 0036
"""

from __future__ import annotations

from datetime import UTC, datetime
import re
from uuid import uuid4

from alembic import context, op
import sqlalchemy as sa

import lumina.models


revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_pages",
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=560), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("page_type", sa.String(length=24), nullable=False),
        sa.Column("current_revision_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("updated_at", lumina.models.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["knowledge_entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "space_id", "entity_id", name="uq_knowledge_pages_space_entity"
        ),
        sa.UniqueConstraint("space_id", "slug", name="uq_knowledge_pages_space_slug"),
    )
    op.create_index("ix_knowledge_pages_space_id", "knowledge_pages", ["space_id"])
    op.create_index("ix_knowledge_pages_entity_id", "knowledge_pages", ["entity_id"])
    op.create_index(
        "ix_knowledge_pages_current_revision_id",
        "knowledge_pages",
        ["current_revision_id"],
    )
    op.create_index("ix_knowledge_pages_status", "knowledge_pages", ["status"])
    op.create_index(
        "ix_knowledge_pages_space_status",
        "knowledge_pages",
        ["space_id", "status"],
    )

    op.create_table(
        "knowledge_page_revisions",
        sa.Column("page_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("markdown_body", sa.Text(), nullable=False),
        sa.Column("generated_sections_json", sa.JSON(), nullable=False),
        sa.Column("manual_sections_json", sa.JSON(), nullable=False),
        sa.Column("source_statement_revision_id", sa.String(length=36), nullable=True),
        sa.Column("generation_run_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["generation_run_id"], ["runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["knowledge_pages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_statement_revision_id"],
            ["knowledge_revisions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "page_id", "revision_number", name="uq_knowledge_page_revisions_number"
        ),
    )
    op.create_index(
        "ix_knowledge_page_revisions_page_id",
        "knowledge_page_revisions",
        ["page_id"],
    )
    op.create_index(
        "ix_knowledge_page_revisions_source_statement_revision_id",
        "knowledge_page_revisions",
        ["source_statement_revision_id"],
    )
    op.create_index(
        "ix_knowledge_page_revisions_generation_run_id",
        "knowledge_page_revisions",
        ["generation_run_id"],
    )
    op.create_index(
        "ix_knowledge_page_revisions_page_created",
        "knowledge_page_revisions",
        ["page_id", "created_at"],
    )

    if not context.is_offline_mode():
        _backfill_entity_pages()


def _backfill_entity_pages() -> None:
    bind = op.get_bind()
    pages = sa.table(
        "knowledge_pages",
        sa.column("space_id", sa.String(36)),
        sa.column("entity_id", sa.String(36)),
        sa.column("slug", sa.String(560)),
        sa.column("title", sa.String(500)),
        sa.column("page_type", sa.String(24)),
        sa.column("current_revision_id", sa.String(36)),
        sa.column("status", sa.String(24)),
        sa.column("id", sa.String(36)),
        sa.column("created_at", lumina.models.UTCDateTime()),
        sa.column("updated_at", lumina.models.UTCDateTime()),
    )
    revisions = sa.table(
        "knowledge_page_revisions",
        sa.column("page_id", sa.String(36)),
        sa.column("revision_number", sa.Integer()),
        sa.column("markdown_body", sa.Text()),
        sa.column("generated_sections_json", sa.JSON()),
        sa.column("manual_sections_json", sa.JSON()),
        sa.column("source_statement_revision_id", sa.String(36)),
        sa.column("generation_run_id", sa.String(36)),
        sa.column("created_by_user_id", sa.String(36)),
        sa.column("created_at", lumina.models.UTCDateTime()),
        sa.column("id", sa.String(36)),
    )
    entities = bind.execute(
        sa.text(
            "SELECT e.id, e.space_id, e.canonical_name, e.description, "
            "s.owner_user_id FROM knowledge_entities e "
            "JOIN knowledge_spaces s ON s.id = e.space_id "
            "WHERE e.status = 'active' AND s.owner_user_id IS NOT NULL"
        )
    ).mappings()
    now = datetime.now(UTC)
    for entity in entities:
        page_id = str(uuid4())
        revision_id = str(uuid4())
        slug_base = re.sub(r"[^\w\-]+", "-", entity["canonical_name"].casefold()).strip(
            "-"
        ) or "entity"
        slug = f"{slug_base}-{entity['id'][:8]}"
        generated = str(entity["description"] or "").strip()
        markdown = f"# {entity['canonical_name']}" + (
            f"\n\n{generated}" if generated else ""
        )
        bind.execute(
            pages.insert(),
            {
                "space_id": entity["space_id"],
                "entity_id": entity["id"],
                "slug": slug,
                "title": entity["canonical_name"],
                "page_type": "entity",
                "current_revision_id": revision_id,
                "status": "active",
                "id": page_id,
                "created_at": now,
                "updated_at": now,
            },
        )
        bind.execute(
            revisions.insert(),
            {
                "page_id": page_id,
                "revision_number": 1,
                "markdown_body": markdown,
                "generated_sections_json": {"markdown": generated},
                "manual_sections_json": {"markdown": ""},
                "source_statement_revision_id": None,
                "generation_run_id": None,
                "created_by_user_id": entity["owner_user_id"],
                "created_at": now,
                "id": revision_id,
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_page_revisions_page_created",
        table_name="knowledge_page_revisions",
    )
    op.drop_index(
        "ix_knowledge_page_revisions_generation_run_id",
        table_name="knowledge_page_revisions",
    )
    op.drop_index(
        "ix_knowledge_page_revisions_source_statement_revision_id",
        table_name="knowledge_page_revisions",
    )
    op.drop_index(
        "ix_knowledge_page_revisions_page_id", table_name="knowledge_page_revisions"
    )
    op.drop_table("knowledge_page_revisions")
    op.drop_index("ix_knowledge_pages_space_status", table_name="knowledge_pages")
    op.drop_index("ix_knowledge_pages_status", table_name="knowledge_pages")
    op.drop_index(
        "ix_knowledge_pages_current_revision_id", table_name="knowledge_pages"
    )
    op.drop_index("ix_knowledge_pages_entity_id", table_name="knowledge_pages")
    op.drop_index("ix_knowledge_pages_space_id", table_name="knowledge_pages")
    op.drop_table("knowledge_pages")
