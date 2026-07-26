"""Add mutable Skill tag metadata.

Revision ID: 0031
Revises: 0030
"""

from alembic import op
import sqlalchemy as sa


revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extensions") as batch_op:
        batch_op.add_column(sa.Column("tags_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("extensions") as batch_op:
        batch_op.drop_column("tags_json")
