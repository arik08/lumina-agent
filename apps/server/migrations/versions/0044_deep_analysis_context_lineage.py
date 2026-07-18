"""Add deep analysis context manifests and file lineage.

Revision ID: 0044
Revises: 0043
"""

from alembic import op
import sqlalchemy as sa


revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deep_analysis_context_manifests",
        sa.Column("mission_id", sa.String(36), nullable=False),
        sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("mission_context_revision", sa.Integer(), nullable=False),
        sa.Column("prefix_hash", sa.String(64), nullable=False),
        sa.Column("tool_profile", sa.String(80), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("items_json", sa.JSON(), nullable=False),
        sa.Column("lineage_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["deep_analysis_missions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["deep_analysis_workflow_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_deep_analysis_context_manifest_run"),
    )
    op.create_index(
        "ix_deep_analysis_context_manifest_mission_node",
        "deep_analysis_context_manifests",
        ["mission_id", "node_id"],
    )
    op.create_table(
        "deep_analysis_mission_file_links",
        sa.Column("mission_id", sa.String(36), nullable=False),
        sa.Column("project_file_id", sa.String(36), nullable=False),
        sa.Column("project_file_version_id", sa.String(36), nullable=False),
        sa.Column("producing_node_id", sa.String(36), nullable=True),
        sa.Column("producing_run_id", sa.String(36), nullable=True),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("validation_status", sa.String(32), nullable=False),
        sa.Column("stale_status", sa.String(32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["deep_analysis_missions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_file_id"], ["project_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_file_version_id"], ["project_file_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["producing_node_id"], ["deep_analysis_workflow_nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["producing_run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mission_id",
            "project_file_id",
            "project_file_version_id",
            "purpose",
            "producing_run_id",
            name="uq_deep_analysis_file_link_lineage",
        ),
    )
    op.create_index(
        "ix_deep_analysis_file_links_mission_purpose",
        "deep_analysis_mission_file_links",
        ["mission_id", "purpose"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deep_analysis_file_links_mission_purpose",
        table_name="deep_analysis_mission_file_links",
    )
    op.drop_table("deep_analysis_mission_file_links")
    op.drop_index(
        "ix_deep_analysis_context_manifest_mission_node",
        table_name="deep_analysis_context_manifests",
    )
    op.drop_table("deep_analysis_context_manifests")
