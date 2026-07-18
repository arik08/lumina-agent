"""Add deep-analysis Claim, Evidence, links, and Open Issues.

Revision ID: 0040
Revises: 0039
"""

from alembic import op
import sqlalchemy as sa


revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deep_analysis_claims",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mission_id", sa.String(length=36), nullable=False),
        sa.Column("source_node_id", sa.String(length=36), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("level", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("materiality", sa.String(length=24), nullable=False),
        sa.Column("report_inclusion", sa.String(length=80), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("stale_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["mission_id"], ["deep_analysis_missions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["deep_analysis_workflow_nodes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deep_analysis_claims_mission_status",
        "deep_analysis_claims",
        ["mission_id", "status"],
    )
    op.create_table(
        "deep_analysis_evidence_references",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mission_id", sa.String(length=36), nullable=False),
        sa.Column("source_node_id", sa.String(length=36), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("stable_id", sa.String(length=1000), nullable=False),
        sa.Column("version_id", sa.String(length=128), nullable=True),
        sa.Column("content_digest", sa.String(length=128), nullable=True),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["mission_id"], ["deep_analysis_missions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["deep_analysis_workflow_nodes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deep_analysis_evidence_mission_source",
        "deep_analysis_evidence_references",
        ["mission_id", "source_type"],
    )
    op.create_table(
        "deep_analysis_claim_evidence_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("stance", sa.String(length=24), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["deep_analysis_claims.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["deep_analysis_evidence_references.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id",
            "evidence_id",
            "stance",
            name="uq_deep_analysis_claim_evidence_stance",
        ),
    )
    op.create_table(
        "deep_analysis_open_issues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mission_id", sa.String(length=36), nullable=False),
        sa.Column("source_node_id", sa.String(length=36), nullable=True),
        sa.Column("issue_type", sa.String(length=40), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("materiality", sa.String(length=24), nullable=False),
        sa.Column("residual_amount", sa.Float(), nullable=True),
        sa.Column("residual_percent", sa.Float(), nullable=True),
        sa.Column("required_action", sa.Text(), nullable=False),
        sa.Column("report_inclusion", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["mission_id"], ["deep_analysis_missions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["deep_analysis_workflow_nodes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deep_analysis_open_issues_mission_status",
        "deep_analysis_open_issues",
        ["mission_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deep_analysis_open_issues_mission_status",
        table_name="deep_analysis_open_issues",
    )
    op.drop_table("deep_analysis_open_issues")
    op.drop_table("deep_analysis_claim_evidence_links")
    op.drop_index(
        "ix_deep_analysis_evidence_mission_source",
        table_name="deep_analysis_evidence_references",
    )
    op.drop_table("deep_analysis_evidence_references")
    op.drop_index(
        "ix_deep_analysis_claims_mission_status",
        table_name="deep_analysis_claims",
    )
    op.drop_table("deep_analysis_claims")
