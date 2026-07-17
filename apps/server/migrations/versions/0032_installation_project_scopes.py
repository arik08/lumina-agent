"""Add per-project availability to Skill and MCP installations.

Revision ID: 0032
Revises: 0031
"""

from alembic import op
import sqlalchemy as sa


revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extension_installations") as batch_op:
        batch_op.add_column(sa.Column("project_ids_json", sa.JSON(), nullable=True))
    with op.batch_alter_table("mcp_installations") as batch_op:
        batch_op.add_column(sa.Column("project_ids_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("mcp_installations") as batch_op:
        batch_op.drop_column("project_ids_json")
    with op.batch_alter_table("extension_installations") as batch_op:
        batch_op.drop_column("project_ids_json")
