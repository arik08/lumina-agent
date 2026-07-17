from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import TimestampMixin, UUIDPrimaryKeyMixin


class DeepAnalysisMission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_missions"
    __table_args__ = (
        Index(
            "ix_deep_analysis_missions_project_activity",
            "project_id",
            "updated_at",
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True, nullable=False)
    start_mode: Mapped[str] = mapped_column(String(32), default="zero_based", nullable=False)
    autonomy_mode: Mapped[str] = mapped_column(String(32), default="balanced", nullable=False)
    charter_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    completion_contract_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    budget_microusd: Mapped[int | None] = mapped_column(BigInteger)
    spent_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class DeepAnalysisWorkflowRevision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_workflow_revisions"
    __table_args__ = (
        UniqueConstraint(
            "mission_id",
            "revision_number",
            name="uq_deep_analysis_workflow_revisions_mission_revision",
        ),
        Index(
            "ix_deep_analysis_workflow_revisions_mission_state",
            "mission_id",
            "state",
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="generated", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="mission_created", nullable=False)
    graph_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class DeepAnalysisWorkflowNode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_workflow_nodes"
    __table_args__ = (
        UniqueConstraint(
            "workflow_revision_id",
            "node_key",
            name="uq_deep_analysis_workflow_nodes_revision_key",
        ),
        Index(
            "ix_deep_analysis_workflow_nodes_revision_sequence",
            "workflow_revision_id",
            "sequence",
        ),
    )

    workflow_revision_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_workflow_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_key: Mapped[str] = mapped_column(String(32), nullable=False)
    node_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    position_x: Mapped[int] = mapped_column(Integer, nullable=False)
    position_y: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    estimated_cost_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    actual_cost_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class DeepAnalysisWorkflowEdge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_workflow_edges"
    __table_args__ = (
        UniqueConstraint(
            "workflow_revision_id",
            "source_node_key",
            "target_node_key",
            name="uq_deep_analysis_workflow_edges_revision_pair",
        ),
    )

    workflow_revision_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_workflow_revisions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_node_key: Mapped[str] = mapped_column(String(32), nullable=False)
    target_node_key: Mapped[str] = mapped_column(String(32), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(24), default="sequence", nullable=False)
