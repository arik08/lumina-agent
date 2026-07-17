"""Add durable deep-analysis missions and workflow graphs.

Revision ID: 0034
Revises: 0033
"""

from alembic import op
import sqlalchemy as sa


revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deep_analysis_missions",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("start_mode", sa.String(length=32), nullable=False),
        sa.Column("autonomy_mode", sa.String(length=32), nullable=False),
        sa.Column("charter_json", sa.JSON(), nullable=False),
        sa.Column("completion_contract_json", sa.JSON(), nullable=False),
        sa.Column("budget_microusd", sa.BigInteger(), nullable=True),
        sa.Column("spent_microusd", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deep_analysis_missions_organization_id", "deep_analysis_missions", ["organization_id"])
    op.create_index("ix_deep_analysis_missions_project_id", "deep_analysis_missions", ["project_id"])
    op.create_index("ix_deep_analysis_missions_created_by_user_id", "deep_analysis_missions", ["created_by_user_id"])
    op.create_index("ix_deep_analysis_missions_status", "deep_analysis_missions", ["status"])
    op.create_index("ix_deep_analysis_missions_project_activity", "deep_analysis_missions", ["project_id", "updated_at"])

    op.create_table(
        "deep_analysis_workflow_revisions",
        sa.Column("mission_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("graph_digest", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["deep_analysis_missions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id", "revision_number", name="uq_deep_analysis_workflow_revisions_mission_revision"),
    )
    op.create_index("ix_deep_analysis_workflow_revisions_mission_state", "deep_analysis_workflow_revisions", ["mission_id", "state"])

    op.create_table(
        "deep_analysis_workflow_nodes",
        sa.Column("workflow_revision_id", sa.String(length=36), nullable=False),
        sa.Column("node_key", sa.String(length=32), nullable=False),
        sa.Column("node_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("position_x", sa.Integer(), nullable=False),
        sa.Column("position_y", sa.Integer(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=False),
        sa.Column("estimated_cost_microusd", sa.BigInteger(), nullable=False),
        sa.Column("actual_cost_microusd", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_revision_id"], ["deep_analysis_workflow_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_revision_id", "node_key", name="uq_deep_analysis_workflow_nodes_revision_key"),
    )
    op.create_index("ix_deep_analysis_workflow_nodes_revision_sequence", "deep_analysis_workflow_nodes", ["workflow_revision_id", "sequence"])

    op.create_table(
        "deep_analysis_workflow_edges",
        sa.Column("workflow_revision_id", sa.String(length=36), nullable=False),
        sa.Column("source_node_key", sa.String(length=32), nullable=False),
        sa.Column("target_node_key", sa.String(length=32), nullable=False),
        sa.Column("edge_type", sa.String(length=24), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_revision_id"], ["deep_analysis_workflow_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_revision_id", "source_node_key", "target_node_key", name="uq_deep_analysis_workflow_edges_revision_pair"),
    )
    op.create_index("ix_deep_analysis_workflow_edges_workflow_revision_id", "deep_analysis_workflow_edges", ["workflow_revision_id"])


def downgrade() -> None:
    op.drop_index("ix_deep_analysis_workflow_edges_workflow_revision_id", table_name="deep_analysis_workflow_edges")
    op.drop_table("deep_analysis_workflow_edges")
    op.drop_index("ix_deep_analysis_workflow_nodes_revision_sequence", table_name="deep_analysis_workflow_nodes")
    op.drop_table("deep_analysis_workflow_nodes")
    op.drop_index("ix_deep_analysis_workflow_revisions_mission_state", table_name="deep_analysis_workflow_revisions")
    op.drop_table("deep_analysis_workflow_revisions")
    op.drop_index("ix_deep_analysis_missions_project_activity", table_name="deep_analysis_missions")
    op.drop_index("ix_deep_analysis_missions_status", table_name="deep_analysis_missions")
    op.drop_index("ix_deep_analysis_missions_created_by_user_id", table_name="deep_analysis_missions")
    op.drop_index("ix_deep_analysis_missions_project_id", table_name="deep_analysis_missions")
    op.drop_index("ix_deep_analysis_missions_organization_id", table_name="deep_analysis_missions")
    op.drop_table("deep_analysis_missions")
