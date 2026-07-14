"""Add organization announcements managed by administrators.

Revision ID: 0027
Revises: 0026
"""

from alembic import op
import sqlalchemy as sa


revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("creator_user_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_announcements_organization_id", "announcements", ["organization_id"])
    op.create_index("ix_announcements_creator_user_id", "announcements", ["creator_user_id"])
    op.create_index(
        "ix_announcements_organization_created",
        "announcements",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_announcements_organization_created", table_name="announcements")
    op.drop_index("ix_announcements_creator_user_id", table_name="announcements")
    op.drop_index("ix_announcements_organization_id", table_name="announcements")
    op.drop_table("announcements")
