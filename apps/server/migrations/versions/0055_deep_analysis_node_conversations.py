"""Give each Deep Analysis node its own conversation and discard legacy missions.

Revision ID: 0055
Revises: 0054
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deep Analysis is still pre-release. The old mission-wide conversation and
    # audit-ledger data model is intentionally not migrated.
    op.execute(
        sa.text(
            "DELETE FROM conversations WHERE id IN "
            "(SELECT conversation_id FROM deep_analysis_missions "
            "WHERE conversation_id IS NOT NULL)"
        )
    )
    op.execute(sa.text("DELETE FROM deep_analysis_missions"))
    with op.batch_alter_table("deep_analysis_workflow_nodes") as batch_op:
        batch_op.add_column(sa.Column("conversation_id", sa.String(length=36)))
        batch_op.create_foreign_key(
            "fk_deep_analysis_node_conversation",
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_deep_analysis_node_conversation",
            ["conversation_id"],
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM deep_analysis_missions"))
    with op.batch_alter_table("deep_analysis_workflow_nodes") as batch_op:
        batch_op.drop_constraint(
            "uq_deep_analysis_node_conversation", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_deep_analysis_node_conversation", type_="foreignkey"
        )
        batch_op.drop_column("conversation_id")
