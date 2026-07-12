"""Compact repetitive completion notifications.

Revision ID: 0016
Revises: 0015
"""

from alembic import op


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM notifications
        WHERE kind = 'run_completed'
          AND id IN (
            SELECT id FROM (
              SELECT id,
                     ROW_NUMBER() OVER (
                       PARTITION BY user_id, conversation_id
                       ORDER BY created_at DESC, id DESC
                     ) AS row_number
              FROM notifications
              WHERE kind = 'run_completed'
            ) ranked
            WHERE row_number > 1
          )
        """
    )
    op.execute(
        """
        UPDATE notifications
        SET title = (
          SELECT conversations.title || ' · 완료'
          FROM conversations
          WHERE conversations.id = notifications.conversation_id
        )
        WHERE kind = 'run_completed'
          AND conversation_id IS NOT NULL
        """
    )


def downgrade() -> None:
    pass
