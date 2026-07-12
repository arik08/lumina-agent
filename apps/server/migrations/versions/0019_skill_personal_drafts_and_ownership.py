"""Add per-user Skill drafts and transferable ownership records.

Revision ID: 0019
Revises: 0018
"""

from alembic import op
import sqlalchemy as sa

import lumina.models


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extensions") as batch_op:
        batch_op.add_column(
            sa.Column("creator_user_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_extensions_creator_user_id_users",
            "users",
            ["creator_user_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_extensions_creator_user_id", ["creator_user_id"])

    op.execute(sa.text("UPDATE extensions SET creator_user_id = owner_user_id"))

    with op.batch_alter_table("extensions") as batch_op:
        batch_op.alter_column(
            "creator_user_id", existing_type=sa.String(length=36), nullable=False
        )

    op.create_table(
        "skill_ownerships",
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("principal_type", sa.String(length=24), nullable=False),
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at", lumina.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_skill_ownerships_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["extensions.id"],
            name="fk_skill_ownerships_skill_id_extensions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skill_ownerships"),
        sa.UniqueConstraint(
            "skill_id",
            "principal_type",
            "principal_id",
            name="uq_skill_ownerships_principal",
        ),
    )
    op.create_index("ix_skill_ownerships_skill_id", "skill_ownerships", ["skill_id"])
    op.create_index(
        "ix_skill_ownerships_principal",
        "skill_ownerships",
        ["principal_type", "principal_id", "role"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO skill_ownerships (
                id, skill_id, principal_type, principal_id, role,
                created_by_user_id, created_at
            )
            SELECT
                id,
                id, 'user', owner_user_id, 'owner', owner_user_id, created_at
            FROM extensions
            """
        )
    )

    with op.batch_alter_table("extension_drafts") as batch_op:
        batch_op.drop_constraint("uq_extension_drafts_extension_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_extension_drafts_extension_owner",
            ["extension_id", "owner_user_id"],
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM extension_drafts
            WHERE id IN (
                SELECT draft.id
                FROM extension_drafts AS draft
                JOIN extensions AS extension ON extension.id = draft.extension_id
                WHERE draft.owner_user_id != extension.owner_user_id
            )
            """
        )
    )
    with op.batch_alter_table("extension_drafts") as batch_op:
        batch_op.drop_constraint("uq_extension_drafts_extension_owner", type_="unique")
        batch_op.create_unique_constraint(
            "uq_extension_drafts_extension_id", ["extension_id"]
        )

    op.drop_index("ix_skill_ownerships_principal", table_name="skill_ownerships")
    op.drop_index("ix_skill_ownerships_skill_id", table_name="skill_ownerships")
    op.drop_table("skill_ownerships")

    with op.batch_alter_table("extensions") as batch_op:
        batch_op.drop_index("ix_extensions_creator_user_id")
        batch_op.drop_constraint(
            "fk_extensions_creator_user_id_users", type_="foreignkey"
        )
        batch_op.drop_column("creator_user_id")
