"""Clean orphaned legacy Deep Analysis mission records.

Revision ID: 0072
Revises: 0071
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


_CASCADE_CHILDREN = (
    ("deep_analysis_claims", "mission_id"),
    ("deep_analysis_commands", "mission_id"),
    ("deep_analysis_context_manifests", "mission_id"),
    ("deep_analysis_decisions", "mission_id"),
    ("deep_analysis_events", "mission_id"),
    ("deep_analysis_evidence_references", "mission_id"),
    ("deep_analysis_mission_exports", "mission_id"),
    ("deep_analysis_mission_file_links", "mission_id"),
    ("deep_analysis_open_issues", "mission_id"),
    ("deep_analysis_quality_gate_results", "mission_id"),
    ("deep_analysis_workflow_revisions", "mission_id"),
)


def upgrade() -> None:
    for table_name, column_name in _CASCADE_CHILDREN:
        op.execute(
            sa.text(
                f"DELETE FROM {table_name} "
                f"WHERE {column_name} IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM deep_analysis_missions mission "
                f"WHERE mission.id = {table_name}.{column_name})"
            )
        )
    op.execute(
        sa.text(
            "DELETE FROM deep_analysis_claim_evidence_links "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM deep_analysis_claims claim "
            "WHERE claim.id = deep_analysis_claim_evidence_links.claim_id) "
            "OR NOT EXISTS ("
            "SELECT 1 FROM deep_analysis_evidence_references evidence "
            "WHERE evidence.id = "
            "deep_analysis_claim_evidence_links.evidence_id)"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM deep_analysis_decision_responses "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM deep_analysis_decisions decision "
            "WHERE decision.id = deep_analysis_decision_responses.decision_id)"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM deep_analysis_workflow_edges "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM deep_analysis_workflow_revisions revision "
            "WHERE revision.id = "
            "deep_analysis_workflow_edges.workflow_revision_id)"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM deep_analysis_workflow_nodes "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM deep_analysis_workflow_revisions revision "
            "WHERE revision.id = "
            "deep_analysis_workflow_nodes.workflow_revision_id)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE deep_analysis_workflow_pattern_versions "
            "SET source_mission_id = NULL "
            "WHERE source_mission_id IS NOT NULL AND NOT EXISTS ("
            "SELECT 1 FROM deep_analysis_missions mission "
            "WHERE mission.id = "
            "deep_analysis_workflow_pattern_versions.source_mission_id)"
        )
    )


def downgrade() -> None:
    # The removed rows had no parent mission and could not be restored into a
    # referentially valid state. Downgrading the schema therefore keeps the
    # cleanup in place.
    pass
