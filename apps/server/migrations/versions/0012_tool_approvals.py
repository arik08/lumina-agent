"""durable Tool approval requests

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-11 23:55:00
"""

from typing import Sequence, Union

from alembic import op
import lumina.models
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_approvals",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("tool_call_id", sa.String(length=200), nullable=False),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("effect", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=24), nullable=False),
        sa.Column("argument_digest", sa.String(length=64), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("resolved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("resolution_note", sa.String(length=2000), nullable=True),
        sa.Column(
            "requested_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "resolved_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            name=op.f("fk_tool_approvals_resolved_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_tool_approvals_run_id_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_approvals")),
        sa.UniqueConstraint(
            "run_id", "tool_call_id", name=op.f("uq_tool_approvals_run_id")
        ),
    )
    op.create_index(
        op.f("ix_tool_approvals_resolved_by_user_id"),
        "tool_approvals",
        ["resolved_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_approvals_run_id"),
        "tool_approvals",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_approvals_status"),
        "tool_approvals",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_tool_approvals_run_status",
        "tool_approvals",
        ["run_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tool_approvals_run_status", table_name="tool_approvals")
    op.drop_index(op.f("ix_tool_approvals_status"), table_name="tool_approvals")
    op.drop_index(op.f("ix_tool_approvals_run_id"), table_name="tool_approvals")
    op.drop_index(
        op.f("ix_tool_approvals_resolved_by_user_id"),
        table_name="tool_approvals",
    )
    op.drop_table("tool_approvals")
