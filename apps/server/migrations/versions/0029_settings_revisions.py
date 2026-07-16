"""Add atomic user and project settings revisions.

Revision ID: 0029
Revises: 0028
"""

from alembic import op
import sqlalchemy as sa


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "settings_revision",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(
            sa.Column(
                "settings_revision",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("settings_revision")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("settings_revision")
