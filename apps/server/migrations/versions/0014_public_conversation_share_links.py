"""Allow recipient-free conversation share links.

Revision ID: 0014
Revises: 0013
"""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_share_grants") as batch_op:
        batch_op.drop_constraint(
            "fk_conversation_share_grants_recipient_user_id_users",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "recipient_user_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch_op.create_foreign_key(
            "fk_conversation_share_grants_recipient_user_id_users",
            "users",
            ["recipient_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM conversation_share_grants WHERE recipient_user_id IS NULL"
    )
    with op.batch_alter_table("conversation_share_grants") as batch_op:
        batch_op.drop_constraint(
            "fk_conversation_share_grants_recipient_user_id_users",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "recipient_user_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_conversation_share_grants_recipient_user_id_users",
            "users",
            ["recipient_user_id"],
            ["id"],
            ondelete="CASCADE",
        )
