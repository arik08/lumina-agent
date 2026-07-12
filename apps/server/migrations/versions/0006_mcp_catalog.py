"""approved MCP catalog and per-user Secret Store bindings

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-11 21:05:00
"""

from typing import Sequence, Union

from alembic import op
import lumina.models
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_definitions",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_revision_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "approved_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "disabled_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "revoked_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name=op.f("fk_mcp_definitions_approved_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_mcp_definitions_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_mcp_definitions_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_definitions")),
        sa.UniqueConstraint(
            "organization_id", "slug", name=op.f("uq_mcp_definitions_organization_id")
        ),
    )
    op.create_index(
        "ix_mcp_definitions_catalog",
        "mcp_definitions",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_definitions_organization_id"),
        "mcp_definitions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_definitions_status"),
        "mcp_definitions",
        ["status"],
        unique=False,
    )

    op.create_table(
        "mcp_configuration_revisions",
        sa.Column("definition_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("transport", sa.String(length=32), nullable=False),
        sa.Column("command_json", sa.JSON(), nullable=False),
        sa.Column("url_template", sa.Text(), nullable=True),
        sa.Column("allowed_hosts_json", sa.JSON(), nullable=False),
        sa.Column("tool_schemas_json", sa.JSON(), nullable=False),
        sa.Column("required_secret_names_json", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("config_digest", sa.String(length=64), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("health_status", sa.String(length=32), nullable=False),
        sa.Column("schema_status", sa.String(length=32), nullable=False),
        sa.Column("approval_status", sa.String(length=24), nullable=False),
        sa.Column("validation_summary", sa.String(length=500), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "validated_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "approved_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name=op.f("fk_mcp_configuration_revisions_approved_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_mcp_configuration_revisions_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["mcp_definitions.id"],
            name=op.f("fk_mcp_configuration_revisions_definition_id_mcp_definitions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_configuration_revisions")),
        sa.UniqueConstraint(
            "definition_id",
            "config_digest",
            name="uq_mcp_configuration_revision_digest",
        ),
        sa.UniqueConstraint(
            "definition_id",
            "revision_number",
            name="uq_mcp_configuration_revision_number",
        ),
    )
    op.create_index(
        op.f("ix_mcp_configuration_revisions_approval_status"),
        "mcp_configuration_revisions",
        ["approval_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_configuration_revisions_definition_id"),
        "mcp_configuration_revisions",
        ["definition_id"],
        unique=False,
    )

    op.create_table(
        "mcp_installations",
        sa.Column("definition_id", sa.String(length=36), nullable=False),
        sa.Column("configuration_revision_id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=24), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("tool_allowlist_json", sa.JSON(), nullable=False),
        sa.Column("installed_by_user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "installed_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "removed_at", lumina.models.UTCDateTime(timezone=True), nullable=True
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["configuration_revision_id"],
            ["mcp_configuration_revisions.id"],
            name=op.f(
                "fk_mcp_installations_configuration_revision_id_mcp_configuration_revisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["mcp_definitions.id"],
            name=op.f("fk_mcp_installations_definition_id_mcp_definitions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["installed_by_user_id"],
            ["users.id"],
            name=op.f("fk_mcp_installations_installed_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_installations")),
    )
    op.create_index(
        "ix_mcp_installations_active",
        "mcp_installations",
        ["scope_type", "scope_id", "enabled", "removed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_installations_configuration_revision_id"),
        "mcp_installations",
        ["configuration_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_installations_definition_id"),
        "mcp_installations",
        ["definition_id"],
        unique=False,
    )

    op.create_table(
        "mcp_secret_bindings",
        sa.Column("installation_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("secret_name", sa.String(length=80), nullable=False),
        sa.Column("secret_ref", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["mcp_installations.id"],
            name=op.f("fk_mcp_secret_bindings_installation_id_mcp_installations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_mcp_secret_bindings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_secret_bindings")),
        sa.UniqueConstraint(
            "installation_id",
            "user_id",
            "secret_name",
            name=op.f("uq_mcp_secret_bindings_installation_id"),
        ),
    )
    op.create_index(
        op.f("ix_mcp_secret_bindings_installation_id"),
        "mcp_secret_bindings",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_secret_bindings_owner",
        "mcp_secret_bindings",
        ["user_id", "installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_secret_bindings_user_id"),
        "mcp_secret_bindings",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mcp_secret_bindings_user_id"), table_name="mcp_secret_bindings"
    )
    op.drop_index("ix_mcp_secret_bindings_owner", table_name="mcp_secret_bindings")
    op.drop_index(
        op.f("ix_mcp_secret_bindings_installation_id"),
        table_name="mcp_secret_bindings",
    )
    op.drop_table("mcp_secret_bindings")
    op.drop_index(
        op.f("ix_mcp_installations_definition_id"), table_name="mcp_installations"
    )
    op.drop_index(
        op.f("ix_mcp_installations_configuration_revision_id"),
        table_name="mcp_installations",
    )
    op.drop_index("ix_mcp_installations_active", table_name="mcp_installations")
    op.drop_table("mcp_installations")
    op.drop_index(
        op.f("ix_mcp_configuration_revisions_definition_id"),
        table_name="mcp_configuration_revisions",
    )
    op.drop_index(
        op.f("ix_mcp_configuration_revisions_approval_status"),
        table_name="mcp_configuration_revisions",
    )
    op.drop_table("mcp_configuration_revisions")
    op.drop_index(op.f("ix_mcp_definitions_status"), table_name="mcp_definitions")
    op.drop_index(
        op.f("ix_mcp_definitions_organization_id"), table_name="mcp_definitions"
    )
    op.drop_index("ix_mcp_definitions_catalog", table_name="mcp_definitions")
    op.drop_table("mcp_definitions")
