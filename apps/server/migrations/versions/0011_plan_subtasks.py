"""durable Plan subtasks for parallel tool execution

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-11 23:20:00
"""

from typing import Sequence, Union

from alembic import op
import lumina.models
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_subtasks",
        sa.Column("plan_step_id", sa.String(length=36), nullable=False),
        sa.Column("tool_execution_id", sa.String(length=36), nullable=True),
        sa.Column("tool_call_id", sa.String(length=200), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("depends_on_json", sa.JSON(), nullable=False),
        sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("artifact_ids_json", sa.JSON(), nullable=False),
        sa.Column("effect", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "completed_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["plan_step_id"],
            ["plan_steps.id"],
            name=op.f("fk_plan_subtasks_plan_step_id_plan_steps"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_execution_id"],
            ["tool_executions.id"],
            name=op.f("fk_plan_subtasks_tool_execution_id_tool_executions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_subtasks")),
        sa.UniqueConstraint(
            "plan_step_id",
            "position",
            name="uq_plan_subtasks_step_position",
        ),
        sa.UniqueConstraint(
            "plan_step_id",
            "tool_call_id",
            name="uq_plan_subtasks_step_tool_call",
        ),
        sa.UniqueConstraint(
            "tool_execution_id",
            name=op.f("uq_plan_subtasks_tool_execution_id"),
        ),
    )
    op.create_index(
        op.f("ix_plan_subtasks_plan_step_id"),
        "plan_subtasks",
        ["plan_step_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_plan_subtasks_status"),
        "plan_subtasks",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_plan_subtasks_timeline",
        "plan_subtasks",
        ["plan_step_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_plan_subtasks_timeline", table_name="plan_subtasks")
    op.drop_index(op.f("ix_plan_subtasks_status"), table_name="plan_subtasks")
    op.drop_index(op.f("ix_plan_subtasks_plan_step_id"), table_name="plan_subtasks")
    op.drop_table("plan_subtasks")
