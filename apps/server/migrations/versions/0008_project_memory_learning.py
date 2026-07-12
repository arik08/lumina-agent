"""Project Memory and approval-gated learning proposals

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-11 21:27:00
"""

import hashlib
from typing import Sequence, Union

from alembic import context, op
import lumina.models
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "concept_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "projects", sa.Column("concept_hash", sa.String(length=64), nullable=True)
    )
    if not context.is_offline_mode():
        connection = op.get_bind()
        projects = connection.execute(
            sa.text("SELECT id, concept FROM projects")
        ).mappings()
        for project in projects:
            digest = hashlib.sha256(
                str(project["concept"] or "").encode("utf-8")
            ).hexdigest()
            connection.execute(
                sa.text(
                    "UPDATE projects SET concept_hash = :digest WHERE id = :project_id"
                ),
                {"digest": digest, "project_id": project["id"]},
            )
    if not context.is_offline_mode():
        with op.batch_alter_table("projects") as batch_op:
            batch_op.alter_column(
                "concept_hash", existing_type=sa.String(length=64), nullable=False
            )

    op.create_table(
        "project_learning_proposals",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_run_ids_json", sa.JSON(), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("base_hash", sa.String(length=64), nullable=False),
        sa.Column("proposed_patch_json", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("expected_scope", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("proposed_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("applied_snapshot_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "reviewed_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "approved_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "rejected_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "applied_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "rolled_back_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_project_learning_proposals_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_learning_proposals_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by_user_id"],
            ["users.id"],
            name=op.f("fk_project_learning_proposals_proposed_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_project_learning_proposals_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_learning_proposals")),
    )
    for column in (
        "organization_id",
        "project_id",
        "proposed_by_user_id",
        "reviewed_by_user_id",
        "status",
        "target_id",
    ):
        op.create_index(
            op.f(f"ix_project_learning_proposals_{column}"),
            "project_learning_proposals",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_project_learning_proposals_listing",
        "project_learning_proposals",
        ["project_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "project_memories",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("memory_key", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("normalized_fact", sa.String(length=1000), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("parent_revision_id", sa.String(length=36), nullable=True),
        sa.Column("source_proposal_id", sa.String(length=36), nullable=False),
        sa.Column("source_run_ids_json", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_project_memories_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_project_memories_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"],
            ["project_memories.id"],
            name=op.f("fk_project_memories_parent_revision_id_project_memories"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_memories_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"],
            ["project_learning_proposals.id"],
            name=op.f(
                "fk_project_memories_source_proposal_id_project_learning_proposals"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_memories")),
        sa.UniqueConstraint(
            "project_id",
            "memory_key",
            "revision",
            name="uq_project_memories_revision",
        ),
    )
    for column in (
        "organization_id",
        "project_id",
        "memory_key",
        "source_proposal_id",
        "status",
    ):
        op.create_index(
            op.f(f"ix_project_memories_{column}"),
            "project_memories",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_project_memories_listing",
        "project_memories",
        ["project_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_project_memories_active",
        "project_memories",
        ["project_id", "memory_key"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_project_memories_active", table_name="project_memories")
    op.drop_index("ix_project_memories_listing", table_name="project_memories")
    for column in (
        "status",
        "source_proposal_id",
        "memory_key",
        "project_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_project_memories_{column}"), table_name="project_memories"
        )
    op.drop_table("project_memories")
    op.drop_index(
        "ix_project_learning_proposals_listing",
        table_name="project_learning_proposals",
    )
    for column in (
        "target_id",
        "status",
        "reviewed_by_user_id",
        "proposed_by_user_id",
        "project_id",
        "organization_id",
    ):
        op.drop_index(
            op.f(f"ix_project_learning_proposals_{column}"),
            table_name="project_learning_proposals",
        )
    op.drop_table("project_learning_proposals")
    if context.is_offline_mode():
        op.drop_column("projects", "concept_hash")
        op.drop_column("projects", "concept_revision")
    else:
        with op.batch_alter_table("projects") as batch_op:
            batch_op.drop_column("concept_hash")
            batch_op.drop_column("concept_revision")
