"""structured plans and durable plan steps

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-11 19:35:00
"""

from typing import Sequence, Union

from alembic import op
import lumina.models
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the DB-owned Plan timeline introduced in Phase 2."""
    op.create_table(
        "plans",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_plans_run_id_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("run_id", name=op.f("uq_plans_run_id")),
    )
    op.create_index(op.f("ix_plans_run_id"), "plans", ["run_id"], unique=False)
    op.create_index(op.f("ix_plans_status"), "plans", ["status"], unique=False)

    op.create_table(
        "plan_steps",
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("step_key", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("depends_on_json", sa.JSON(), nullable=False),
        sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("artifact_ids_json", sa.JSON(), nullable=False),
        sa.Column("effect", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
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
            ["plan_id"],
            ["plans.id"],
            name=op.f("fk_plan_steps_plan_id_plans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_steps")),
        sa.UniqueConstraint(
            "plan_id", "position", name="uq_plan_steps_plan_id_position"
        ),
        sa.UniqueConstraint(
            "plan_id", "step_key", name="uq_plan_steps_plan_id_step_key"
        ),
    )
    op.create_index(
        op.f("ix_plan_steps_plan_id"), "plan_steps", ["plan_id"], unique=False
    )
    op.create_index(
        op.f("ix_plan_steps_status"), "plan_steps", ["status"], unique=False
    )
    op.create_index(
        "ix_plan_steps_timeline",
        "plan_steps",
        ["plan_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    """Remove structured Plan data while preserving core Runs."""
    op.drop_index("ix_plan_steps_timeline", table_name="plan_steps")
    op.drop_index(op.f("ix_plan_steps_status"), table_name="plan_steps")
    op.drop_index(op.f("ix_plan_steps_plan_id"), table_name="plan_steps")
    op.drop_table("plan_steps")
    op.drop_index(op.f("ix_plans_status"), table_name="plans")
    op.drop_index(op.f("ix_plans_run_id"), table_name="plans")
    op.drop_table("plans")
