"""persistent user notifications

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-11 23:12:00
"""

from typing import Sequence, Union

from alembic import op
import lumina.models
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("scheduled_task_id", sa.String(length=36), nullable=True),
        sa.Column("scheduled_run_id", sa.String(length=36), nullable=True),
        sa.Column("deep_link_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("read_at", lumina.models.UTCDateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            lumina.models.UTCDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_notifications_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_notifications_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_notifications_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_notifications_run_id_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_run_id"],
            ["scheduled_runs.id"],
            name=op.f("fk_notifications_scheduled_run_id_scheduled_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_task_id"],
            ["scheduled_tasks.id"],
            name=op.f("fk_notifications_scheduled_task_id_scheduled_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_notifications_user_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_notifications_organization_id"),
        "notifications",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_user_id"),
        "notifications",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_kind"), "notifications", ["kind"], unique=False
    )
    op.create_index(
        op.f("ix_notifications_project_id"),
        "notifications",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_conversation_id"),
        "notifications",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_run_id"),
        "notifications",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_scheduled_task_id"),
        "notifications",
        ["scheduled_task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_scheduled_run_id"),
        "notifications",
        ["scheduled_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_user_created",
        "notifications",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id", "read_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_index(op.f("ix_notifications_scheduled_run_id"), table_name="notifications")
    op.drop_index(
        op.f("ix_notifications_scheduled_task_id"), table_name="notifications"
    )
    op.drop_index(op.f("ix_notifications_run_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_conversation_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_project_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_kind"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_organization_id"), table_name="notifications")
    op.drop_table("notifications")
