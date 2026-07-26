"""Add replayable deep analysis events and idempotent commands.

Revision ID: 0043
Revises: 0042
"""

from alembic import op
import sqlalchemy as sa


revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deep_analysis_missions") as batch:
        batch.add_column(
            sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0")
        )

    op.create_table(
        "deep_analysis_events",
        sa.Column("mission_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["deep_analysis_missions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id", "sequence", name="uq_deep_analysis_event_sequence"),
    )
    op.create_index(
        "ix_deep_analysis_events_replay",
        "deep_analysis_events",
        ["mission_id", "sequence"],
    )

    op.create_table(
        "deep_analysis_commands",
        sa.Column("mission_id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("command_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["mission_id"], ["deep_analysis_missions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id", "idempotency_key", name="uq_deep_analysis_command_key"),
    )
    op.create_index(
        "ix_deep_analysis_commands_mission_created",
        "deep_analysis_commands",
        ["mission_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deep_analysis_commands_mission_created",
        table_name="deep_analysis_commands",
    )
    op.drop_table("deep_analysis_commands")
    op.drop_index("ix_deep_analysis_events_replay", table_name="deep_analysis_events")
    op.drop_table("deep_analysis_events")
    with op.batch_alter_table("deep_analysis_missions") as batch:
        batch.drop_column("event_sequence")
