"""Persist Project file explorer folders.

Revision ID: 0024
Revises: 0023
"""

from alembic import op
import lumina.models
import sqlalchemy as sa


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_folders",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("logical_path", sa.String(length=1000), nullable=False),
        sa.Column("active_path_key", sa.String(length=1000), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", lumina.models.UTCDateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", lumina.models.UTCDateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "active_path_key", name="uq_project_folders_active_path"),
    )
    op.create_index("ix_project_folders_deleted_at", "project_folders", ["deleted_at"])
    op.create_index("ix_project_folders_listing", "project_folders", ["project_id", "status", "logical_path"])
    op.create_index("ix_project_folders_organization_id", "project_folders", ["organization_id"])
    op.create_index("ix_project_folders_project_id", "project_folders", ["project_id"])
    op.create_index("ix_project_folders_status", "project_folders", ["status"])


def downgrade() -> None:
    op.drop_index("ix_project_folders_status", table_name="project_folders")
    op.drop_index("ix_project_folders_project_id", table_name="project_folders")
    op.drop_index("ix_project_folders_organization_id", table_name="project_folders")
    op.drop_index("ix_project_folders_listing", table_name="project_folders")
    op.drop_index("ix_project_folders_deleted_at", table_name="project_folders")
    op.drop_table("project_folders")
