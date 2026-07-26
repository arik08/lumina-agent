"""store Project scopes selected for Knowledge spaces

Revision ID: 0054
Revises: 0053
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_spaces") as batch_op:
        batch_op.add_column(sa.Column("project_ids_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("knowledge_spaces") as batch_op:
        batch_op.drop_column("project_ids_json")
