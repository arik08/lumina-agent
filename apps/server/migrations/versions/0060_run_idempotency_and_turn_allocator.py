"""make run creation idempotent and allocate conversation turns atomically

Revision ID: 0060
Revises: 0059
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("next_turn_index", sa.Integer(), server_default="1", nullable=False),
    )
    op.execute(
        """
        UPDATE conversations
        SET next_turn_index = COALESCE(
            (
                SELECT MAX(messages.turn_index) + 1
                FROM messages
                WHERE messages.conversation_id = conversations.id
            ),
            1
        )
        """
    )
    op.execute(
        """
        WITH duplicate_keys AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY conversation_id, user_id, idempotency_key
                       ORDER BY created_at, id
                   ) AS duplicate_rank
            FROM runs
            WHERE idempotency_key IS NOT NULL
        )
        UPDATE runs
        SET idempotency_key = NULL
        WHERE id IN (
            SELECT id FROM duplicate_keys WHERE duplicate_rank > 1
        )
        """
    )
    with op.batch_alter_table("runs") as batch_op:
        batch_op.create_unique_constraint(
            "uq_runs_conversation_user_idempotency",
            ["conversation_id", "user_id", "idempotency_key"],
        )
    op.create_index(
        "ix_runs_queue_claim",
        "runs",
        ["status", "queued_at", "conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_runs_queue_claim", table_name="runs")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_constraint(
            "uq_runs_conversation_user_idempotency",
            type_="unique",
        )
    op.drop_column("conversations", "next_turn_index")
