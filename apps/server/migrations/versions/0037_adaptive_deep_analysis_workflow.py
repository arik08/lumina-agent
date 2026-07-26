"""Record adaptive deep-analysis Workflow decisions.

Revision ID: 0037
Revises: 0036
"""

from alembic import op
import sqlalchemy as sa


revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deep_analysis_workflow_revisions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "change_log_json", sa.JSON(), nullable=False, server_default="[]"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("deep_analysis_workflow_revisions") as batch_op:
        batch_op.drop_column("change_log_json")
