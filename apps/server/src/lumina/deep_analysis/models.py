from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), unique=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="draft", index=True, nullable=False
    )
    start_mode: Mapped[str] = mapped_column(
        String(32), default="zero_based", nullable=False
    )
    autonomy_mode: Mapped[str] = mapped_column(
        String(32), default="balanced", nullable=False
    )
    charter_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    completion_contract_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    source_manifest_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    budget_microusd: Mapped[int | None] = mapped_column(BigInteger)
    spent_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completion_outcome: Mapped[str | None] = mapped_column(String(40))
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
    change_log_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )


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
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), unique=True
    )
    output_project_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_files.id", ondelete="SET NULL")
    )
    output_logical_path: Mapped[str | None] = mapped_column(String(1000))
    output_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    output_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    generated_files_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    run_history_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    estimated_cost_microusd: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )
    actual_cost_microusd: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    edge_type: Mapped[str] = mapped_column(
        String(24), default="sequence", nullable=False
    )


class DeepAnalysisDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_decisions"
    __table_args__ = (
        Index(
            "ix_deep_analysis_decisions_mission_status",
            "mission_id",
            "status",
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    workflow_revision_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_workflow_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("deep_analysis_workflow_nodes.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    recommendation_option_id: Mapped[str | None] = mapped_column(String(64))
    recommendation_rationale: Mapped[str] = mapped_column(
        Text, default="", nullable=False
    )
    impact_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    affected_node_keys_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default="pending", nullable=False
    )
    applied_workflow_revision_number: Mapped[int | None] = mapped_column(Integer)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeepAnalysisDecisionResponse(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_decision_responses"

    decision_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_decisions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    selected_option_id: Mapped[str] = mapped_column(String(64), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    decided_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class DeepAnalysisQualityGateResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_quality_gate_results"
    __table_args__ = (
        Index(
            "ix_deep_analysis_quality_gates_mission_created",
            "mission_id",
            "created_at",
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    workflow_revision_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_workflow_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("deep_analysis_workflow_nodes.id", ondelete="SET NULL")
    )
    parent_result_id: Mapped[str | None] = mapped_column(
        ForeignKey("deep_analysis_quality_gate_results.id", ondelete="SET NULL")
    )
    waiver_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("deep_analysis_decisions.id", ondelete="SET NULL")
    )
    result: Mapped[str] = mapped_column(String(24), nullable=False)
    completion_outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    checks_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    failure_reasons_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
