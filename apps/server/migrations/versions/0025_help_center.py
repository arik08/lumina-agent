"""Add the organization-scoped Help manual tree.

Revision ID: 0025
Revises: 0024
"""

from alembic import context, op
import lumina.models
import sqlalchemy as sa


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if inspector.has_table("help_items"):
            _validate_existing_table(inspector)
            return
    op.create_table(
        "help_items",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("parent_scope_key", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("title_key", sa.String(length=160), nullable=False),
        sa.Column("markdown_content", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", lumina.models.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", lumina.models.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["help_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "parent_scope_key",
            "title_key",
            name="uq_help_items_sibling_title",
        ),
    )
    op.create_index("ix_help_items_organization_id", "help_items", ["organization_id"])
    op.create_index("ix_help_items_parent_id", "help_items", ["parent_id"])
    op.create_index(
        "ix_help_items_tree",
        "help_items",
        ["organization_id", "parent_id", "sort_order"],
    )


def _validate_existing_table(inspector: sa.Inspector) -> None:
    expected_columns = {
        "organization_id",
        "parent_id",
        "parent_scope_key",
        "kind",
        "title",
        "title_key",
        "markdown_content",
        "sort_order",
        "revision",
        "created_by_user_id",
        "updated_by_user_id",
        "id",
        "created_at",
        "updated_at",
    }
    actual_columns = {
        str(column["name"]) for column in inspector.get_columns("help_items")
    }
    expected_indexes = {
        "ix_help_items_organization_id",
        "ix_help_items_parent_id",
        "ix_help_items_tree",
    }
    actual_indexes = {
        str(index["name"])
        for index in inspector.get_indexes("help_items")
        if index.get("name")
    }
    unique_columns = {
        tuple(str(column) for column in constraint.get("column_names") or ())
        for constraint in inspector.get_unique_constraints("help_items")
    }
    if (
        expected_columns - actual_columns
        or expected_indexes - actual_indexes
        or ("organization_id", "parent_scope_key", "title_key") not in unique_columns
    ):
        raise RuntimeError(
            "Existing help_items schema is incompatible with migration 0025."
        )


def downgrade() -> None:
    op.drop_index("ix_help_items_tree", table_name="help_items")
    op.drop_index("ix_help_items_parent_id", table_name="help_items")
    op.drop_index("ix_help_items_organization_id", table_name="help_items")
    op.drop_table("help_items")
