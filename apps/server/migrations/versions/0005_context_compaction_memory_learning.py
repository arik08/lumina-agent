"""recoverable context compaction and memory learning candidates

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-11 20:14:00
"""

from typing import Sequence, Union

from alembic import context, op
import lumina.models
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        compacted_exists = inspector.has_table("compacted_context_entries")
        memory_columns = {
            str(column["name"]) for column in inspector.get_columns("user_memories")
        }
        if "conflict_key" not in memory_columns:
            op.add_column(
                "user_memories",
                sa.Column("conflict_key", sa.String(length=160), nullable=True),
            )
        _ensure_index(
            "user_memories",
            op.f("ix_user_memories_conflict_key"),
            ["conflict_key"],
        )
        if compacted_exists:
            _validate_legacy_compacted_context_table()
            _ensure_compacted_context_indexes()
            return
    else:
        op.add_column(
            "user_memories",
            sa.Column("conflict_key", sa.String(length=160), nullable=True),
        )
        op.create_index(
            op.f("ix_user_memories_conflict_key"),
            "user_memories",
            ["conflict_key"],
            unique=False,
        )
    op.create_table(
        "compacted_context_entries",
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("parent_compaction_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_message_ids_json", sa.JSON(), nullable=False),
        sa.Column("source_message_range_json", sa.JSON(), nullable=False),
        sa.Column("source_event_range_json", sa.JSON(), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("estimated_tokens_before", sa.Integer(), nullable=False),
        sa.Column("estimated_tokens_after", sa.Integer(), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("effective_input_budget", sa.Integer(), nullable=False),
        sa.Column("summary_model", sa.String(length=160), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("retrieval_policy", sa.String(length=80), nullable=False),
        sa.Column("access_scope", sa.String(length=40), nullable=False),
        sa.Column(
            "cooldown_until",
            lumina.models.UTCDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("ineffective_count", sa.Integer(), nullable=False),
        sa.Column(
            "compacted_at",
            lumina.models.UTCDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_compacted_context_entries_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_compaction_id"],
            ["compacted_context_entries.id"],
            name=op.f(
                "fk_compacted_context_entries_parent_compaction_id_compacted_context_entries"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_compacted_context_entries_run_id_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compacted_context_entries")),
        sa.UniqueConstraint(
            "conversation_id",
            "version",
            name="uq_compacted_context_entries_conversation_version",
        ),
    )
    op.create_index(
        op.f("ix_compacted_context_entries_conversation_id"),
        "compacted_context_entries",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_compacted_context_entries_history",
        "compacted_context_entries",
        ["conversation_id", "compacted_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_compacted_context_entries_run_id"),
        "compacted_context_entries",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_compacted_context_entries_status"),
        "compacted_context_entries",
        ["status"],
        unique=False,
    )


def _validate_legacy_compacted_context_table() -> None:
    expected_columns = {
        "conversation_id",
        "run_id",
        "parent_compaction_id",
        "version",
        "status",
        "summary",
        "source_message_ids_json",
        "source_message_range_json",
        "source_event_range_json",
        "source_refs_json",
        "source_hash",
        "estimated_tokens_before",
        "estimated_tokens_after",
        "context_window",
        "effective_input_budget",
        "summary_model",
        "prompt_version",
        "retrieval_policy",
        "access_scope",
        "cooldown_until",
        "ineffective_count",
        "compacted_at",
        "id",
    }
    inspector = sa.inspect(op.get_bind())
    actual_columns = {
        str(column["name"])
        for column in inspector.get_columns("compacted_context_entries")
    }
    missing = sorted(expected_columns - actual_columns)
    if missing:
        raise RuntimeError(
            "Legacy compacted_context_entries schema is incomplete: "
            + ", ".join(missing)
        )
    unique_column_sets = {
        tuple(str(column) for column in constraint.get("column_names") or ())
        for constraint in inspector.get_unique_constraints("compacted_context_entries")
    }
    if ("conversation_id", "version") not in unique_column_sets:
        raise RuntimeError(
            "Legacy compacted_context_entries schema lacks its version constraint."
        )


def _ensure_compacted_context_indexes() -> None:
    for name, columns in (
        (op.f("ix_compacted_context_entries_conversation_id"), ["conversation_id"]),
        (
            "ix_compacted_context_entries_history",
            ["conversation_id", "compacted_at"],
        ),
        (op.f("ix_compacted_context_entries_run_id"), ["run_id"]),
        (op.f("ix_compacted_context_entries_status"), ["status"]),
    ):
        _ensure_index("compacted_context_entries", name, columns)


def _ensure_index(table_name: str, index_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {
        str(index["name"])
        for index in inspector.get_indexes(table_name)
        if index.get("name")
    }
    if index_name not in existing:
        op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    op.drop_index(
        op.f("ix_compacted_context_entries_status"),
        table_name="compacted_context_entries",
    )
    op.drop_index(
        op.f("ix_compacted_context_entries_run_id"),
        table_name="compacted_context_entries",
    )
    op.drop_index(
        "ix_compacted_context_entries_history",
        table_name="compacted_context_entries",
    )
    op.drop_index(
        op.f("ix_compacted_context_entries_conversation_id"),
        table_name="compacted_context_entries",
    )
    op.drop_table("compacted_context_entries")
    op.drop_index(op.f("ix_user_memories_conflict_key"), table_name="user_memories")
    op.drop_column("user_memories", "conflict_key")
