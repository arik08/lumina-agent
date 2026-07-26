"""Add versioned deep analysis workflow patterns.

Revision ID: 0042
Revises: 0041
"""

from alembic import op
import sqlalchemy as sa


revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deep_analysis_workflow_patterns",
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(24), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deep_analysis_patterns_project_status", "deep_analysis_workflow_patterns", ["project_id", "status"])
    op.create_table(
        "deep_analysis_workflow_pattern_versions",
        sa.Column("pattern_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("definition_digest", sa.String(64), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("source_mission_id", sa.String(36), nullable=True),
        sa.Column("published_by_user_id", sa.String(36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pattern_id"], ["deep_analysis_workflow_patterns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_mission_id"], ["deep_analysis_missions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pattern_id", "version_number", name="uq_deep_analysis_pattern_version"),
    )
    with op.batch_alter_table("deep_analysis_missions") as batch:
        batch.add_column(sa.Column("pattern_version_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_deep_analysis_mission_pattern_version", "deep_analysis_workflow_pattern_versions", ["pattern_version_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("deep_analysis_missions") as batch:
        batch.drop_constraint("fk_deep_analysis_mission_pattern_version", type_="foreignkey")
        batch.drop_column("pattern_version_id")
    op.drop_table("deep_analysis_workflow_pattern_versions")
    op.drop_index("ix_deep_analysis_patterns_project_status", table_name="deep_analysis_workflow_patterns")
    op.drop_table("deep_analysis_workflow_patterns")
