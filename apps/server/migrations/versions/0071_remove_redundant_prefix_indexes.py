"""Remove indexes covered by composite index prefixes.

Revision ID: 0071
Revises: 0070
"""

from __future__ import annotations

from alembic import op


revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


_INDEXES = (
    ("ix_runs_conversation_id", "runs", ("conversation_id",)),
    ("ix_runs_user_id", "runs", ("user_id",)),
    ("ix_runs_status", "runs", ("status",)),
    ("ix_plan_steps_timeline", "plan_steps", ("plan_id", "position")),
    ("ix_plan_steps_plan_id", "plan_steps", ("plan_id",)),
    (
        "ix_plan_subtasks_timeline",
        "plan_subtasks",
        ("plan_step_id", "position"),
    ),
    ("ix_plan_subtasks_plan_step_id", "plan_subtasks", ("plan_step_id",)),
    ("ix_messages_conversation_id", "messages", ("conversation_id",)),
    ("ix_tool_executions_run_id", "tool_executions", ("run_id",)),
)


def upgrade() -> None:
    postgresql = op.get_bind().dialect.name == "postgresql"
    if postgresql:
        with op.get_context().autocommit_block():
            for index_name, table_name, _columns in _INDEXES:
                op.drop_index(
                    index_name,
                    table_name=table_name,
                    postgresql_concurrently=True,
                )
        return
    for index_name, table_name, _columns in _INDEXES:
        op.drop_index(index_name, table_name=table_name)


def downgrade() -> None:
    postgresql = op.get_bind().dialect.name == "postgresql"
    if postgresql:
        with op.get_context().autocommit_block():
            for index_name, table_name, columns in _INDEXES:
                op.create_index(
                    index_name,
                    table_name,
                    list(columns),
                    unique=False,
                    postgresql_concurrently=True,
                )
        return
    for index_name, table_name, columns in _INDEXES:
        op.create_index(index_name, table_name, list(columns), unique=False)
