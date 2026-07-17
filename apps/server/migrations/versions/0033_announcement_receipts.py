"""Add per-user announcement read receipts.

Revision ID: 0033
Revises: 0032
"""

from alembic import op
import sqlalchemy as sa


revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcement_receipts",
        sa.Column("announcement_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "announcement_id",
            "user_id",
            name="uq_announcement_receipts_announcement_user",
        ),
    )
    op.create_index(
        "ix_announcement_receipts_announcement_id",
        "announcement_receipts",
        ["announcement_id"],
    )
    op.create_index(
        "ix_announcement_receipts_user_id",
        "announcement_receipts",
        ["user_id"],
    )
    op.create_index(
        "ix_announcement_receipts_user_read",
        "announcement_receipts",
        ["user_id", "read_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_announcement_receipts_user_read", table_name="announcement_receipts")
    op.drop_index("ix_announcement_receipts_user_id", table_name="announcement_receipts")
    op.drop_index("ix_announcement_receipts_announcement_id", table_name="announcement_receipts")
    op.drop_table("announcement_receipts")
