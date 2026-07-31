"""Remove replay indexes duplicated by unique constraints.

Revision ID: 0070
Revises: 0069
"""

from __future__ import annotations

from alembic import op


revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


_INDEXES = (
    ("ix_run_events_replay", "run_events", ("run_id", "sequence")),
    (
        "ix_deep_analysis_events_replay",
        "deep_analysis_events",
        ("mission_id", "sequence"),
    ),
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
