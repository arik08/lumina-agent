"""Add organization-scoped runtime prompt overrides.

Revision ID: 0023
Revises: 0022
"""

from alembic import context, op
import sqlalchemy as sa


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if inspector.has_table("runtime_prompt_overrides"):
            _validate_existing_table(inspector)
            return
    op.create_table(
        "runtime_prompt_overrides",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_key", sa.String(length=80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("is_overridden", sa.Boolean(), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("organization_id", "prompt_key"),
    )


def _validate_existing_table(inspector: sa.Inspector) -> None:
    expected_columns = {
        "organization_id",
        "prompt_key",
        "content",
        "revision",
        "digest",
        "is_overridden",
        "updated_by_user_id",
        "created_at",
        "updated_at",
    }
    actual_columns = {
        str(column["name"])
        for column in inspector.get_columns("runtime_prompt_overrides")
    }
    missing = sorted(expected_columns - actual_columns)
    primary_key = tuple(
        str(column)
        for column in inspector.get_pk_constraint("runtime_prompt_overrides").get(
            "constrained_columns", ()
        )
    )
    if missing or primary_key != ("organization_id", "prompt_key"):
        raise RuntimeError(
            "Existing runtime_prompt_overrides schema is incompatible with migration 0023."
        )


def downgrade() -> None:
    op.drop_table("runtime_prompt_overrides")
