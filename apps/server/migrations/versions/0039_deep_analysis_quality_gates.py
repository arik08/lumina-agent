"""Add deep-analysis completion outcome and immutable Quality Gate results.

Revision ID: 0039
Revises: 0038
"""

from alembic import op
import sqlalchemy as sa


revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deep_analysis_missions") as batch_op:
        batch_op.add_column(
            sa.Column("completion_outcome", sa.String(length=40), nullable=True)
        )

    op.create_table(
        "deep_analysis_quality_gate_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mission_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_revision_id", sa.String(length=36), nullable=False),
        sa.Column("report_node_id", sa.String(length=36), nullable=True),
        sa.Column("parent_result_id", sa.String(length=36), nullable=True),
        sa.Column("waiver_decision_id", sa.String(length=36), nullable=True),
        sa.Column("result", sa.String(length=24), nullable=False),
        sa.Column("completion_outcome", sa.String(length=40), nullable=False),
        sa.Column("checks_json", sa.JSON(), nullable=False),
        sa.Column("failure_reasons_json", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
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
            ["report_node_id"],
            ["deep_analysis_workflow_nodes.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_result_id"],
            ["deep_analysis_quality_gate_results.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["waiver_decision_id"],
            ["deep_analysis_decisions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deep_analysis_quality_gates_mission_created",
        "deep_analysis_quality_gate_results",
        ["mission_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deep_analysis_quality_gates_mission_created",
        table_name="deep_analysis_quality_gate_results",
    )
    op.drop_table("deep_analysis_quality_gate_results")
    with op.batch_alter_table("deep_analysis_missions") as batch_op:
        batch_op.drop_column("completion_outcome")
