"""Server Workspace Project files and immutable versions

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-11 21:14:00
"""

from typing import Sequence, Union

from alembic import op
import lumina.models
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_files",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("logical_path", sa.String(length=1000), nullable=False),
        sa.Column("active_path_key", sa.String(length=1000), nullable=True),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "deleted_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_project_files_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_project_files_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_files_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_files")),
        sa.UniqueConstraint(
            "project_id", "active_path_key", name="uq_project_files_active_path"
        ),
    )
    op.create_index(
        op.f("ix_project_files_deleted_at"),
        "project_files",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_project_files_listing",
        "project_files",
        ["project_id", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_files_organization_id"),
        "project_files",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_files_project_id"),
        "project_files",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_files_status"),
        "project_files",
        ["status"],
        unique=False,
    )

    op.create_table(
        "project_file_versions",
        sa.Column("project_file_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_backend", sa.String(length=40), nullable=False),
        sa.Column("storage_key", sa.String(length=1000), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=200), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("source_run_id", sa.String(length=36), nullable=True),
        sa.Column("extraction_status", sa.String(length=40), nullable=False),
        sa.Column("extraction_version", sa.String(length=80), nullable=True),
        sa.Column("locator_map_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_project_file_versions_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["project_file_versions.id"],
            name=op.f(
                "fk_project_file_versions_parent_version_id_project_file_versions"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_file_id"],
            ["project_files.id"],
            name=op.f("fk_project_file_versions_project_file_id_project_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["runs.id"],
            name=op.f("fk_project_file_versions_source_run_id_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_file_versions")),
        sa.UniqueConstraint(
            "project_file_id",
            "version_number",
            name="uq_project_file_versions_number",
        ),
        sa.UniqueConstraint(
            "storage_key", name=op.f("uq_project_file_versions_storage_key")
        ),
    )
    op.create_index(
        "ix_project_file_versions_digest",
        "project_file_versions",
        ["project_file_id", "content_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_file_versions_project_file_id"),
        "project_file_versions",
        ["project_file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_file_versions_source_run_id"),
        "project_file_versions",
        ["source_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_project_file_versions_source_run_id"),
        table_name="project_file_versions",
    )
    op.drop_index(
        op.f("ix_project_file_versions_project_file_id"),
        table_name="project_file_versions",
    )
    op.drop_index("ix_project_file_versions_digest", table_name="project_file_versions")
    op.drop_table("project_file_versions")
    op.drop_index(op.f("ix_project_files_status"), table_name="project_files")
    op.drop_index(op.f("ix_project_files_project_id"), table_name="project_files")
    op.drop_index(op.f("ix_project_files_organization_id"), table_name="project_files")
    op.drop_index("ix_project_files_listing", table_name="project_files")
    op.drop_index(op.f("ix_project_files_deleted_at"), table_name="project_files")
    op.drop_table("project_files")
