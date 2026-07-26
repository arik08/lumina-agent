"""Persist deep-analysis decisions and immutable responses.

Revision ID: 0038
Revises: 0037
"""

from alembic import op
import sqlalchemy as sa


revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deep_analysis_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mission_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_revision_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_node_id", sa.String(length=36), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("recommendation_option_id", sa.String(length=64), nullable=True),
        sa.Column("recommendation_rationale", sa.Text(), nullable=False),
        sa.Column("impact_json", sa.JSON(), nullable=False),
        sa.Column("affected_node_keys_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("applied_workflow_revision_number", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["mission_id"], ["deep_analysis_missions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_revision_id"],
            ["deep_analysis_workflow_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_node_id"],
            ["deep_analysis_workflow_nodes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deep_analysis_decisions_mission_status",
        "deep_analysis_decisions",
        ["mission_id", "status"],
    )
    op.create_table(
        "deep_analysis_decision_responses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("selected_option_id", sa.String(length=64), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("decided_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["deep_analysis_decisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "decision_id", name="uq_deep_analysis_decision_responses_decision_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("deep_analysis_decision_responses")
    op.drop_index(
        "ix_deep_analysis_decisions_mission_status",
        table_name="deep_analysis_decisions",
    )
    op.drop_table("deep_analysis_decisions")
