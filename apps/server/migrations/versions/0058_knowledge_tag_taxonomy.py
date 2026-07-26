"""add editable knowledge tag definitions and hierarchy

Revision ID: 0058
Revises: 0057
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_tags") as batch_op:
        batch_op.add_column(
            sa.Column("definition", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("parent_tag_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.create_foreign_key(
            "fk_knowledge_tags_parent_tag",
            "knowledge_tags",
            ["parent_tag_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_knowledge_tags_parent_tag_id", ["parent_tag_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_tags") as batch_op:
        batch_op.drop_index("ix_knowledge_tags_parent_tag_id")
        batch_op.drop_constraint("fk_knowledge_tags_parent_tag", type_="foreignkey")
        batch_op.drop_column("revision")
        batch_op.drop_column("parent_tag_id")
        batch_op.drop_column("definition")
