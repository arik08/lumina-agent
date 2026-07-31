from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


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
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_liked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="draft", index=True, nullable=False
    )
    start_mode: Mapped[str] = mapped_column(
        String(32), default="zero_based", nullable=False
    )
    pattern_version_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "deep_analysis_workflow_pattern_versions.id",
            name="fk_deep_analysis_mission_pattern_version",
            ondelete="SET NULL",
            use_alter=True,
        )
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
    execution_settings_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    budget_microusd: Mapped[int | None] = mapped_column(BigInteger)
    spent_microusd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completion_outcome: Mapped[str | None] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    event_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_export_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DeepAnalysisEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "deep_analysis_events"
    __table_args__ = (
        UniqueConstraint(
            "mission_id", "sequence", name="uq_deep_analysis_event_sequence"
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class DeepAnalysisCommand(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "deep_analysis_commands"
    __table_args__ = (
        UniqueConstraint(
            "mission_id", "idempotency_key", name="uq_deep_analysis_command_key"
        ),
        Index("ix_deep_analysis_commands_mission_created", "mission_id", "created_at"),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeepAnalysisContextManifest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_context_manifests"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_deep_analysis_context_manifest_run"),
        Index(
            "ix_deep_analysis_context_manifest_mission_node", "mission_id", "node_id"
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_workflow_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    mission_context_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    prefix_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    items_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    lineage_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )


class DeepAnalysisMissionFileLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_mission_file_links"
    __table_args__ = (
        Index("ix_deep_analysis_file_links_mission_purpose", "mission_id", "purpose"),
        UniqueConstraint(
            "mission_id",
            "project_file_id",
            "project_file_version_id",
            "purpose",
            "producing_run_id",
            name="uq_deep_analysis_file_link_lineage",
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    project_file_id: Mapped[str] = mapped_column(
        ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False
    )
    project_file_version_id: Mapped[str] = mapped_column(
        ForeignKey("project_file_versions.id", ondelete="RESTRICT"), nullable=False
    )
    producing_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("deep_analysis_workflow_nodes.id", ondelete="SET NULL")
    )
    producing_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL")
    )
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(
        String(32), default="unvalidated", nullable=False
    )
    stale_status: Mapped[str] = mapped_column(
        String(32), default="fresh", nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )


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
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), unique=True
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
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
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
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class DeepAnalysisClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_claims"
    __table_args__ = (
        Index("ix_deep_analysis_claims_mission_status", "mission_id", "status"),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    source_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("deep_analysis_workflow_nodes.id", ondelete="SET NULL")
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    materiality: Mapped[str] = mapped_column(
        String(24), default="medium", nullable=False
    )
    report_inclusion: Mapped[str] = mapped_column(
        String(80), default="", nullable=False
    )
    validation_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    stale_status: Mapped[str] = mapped_column(
        String(32), default="fresh", nullable=False
    )


class DeepAnalysisEvidenceReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_evidence_references"
    __table_args__ = (
        Index(
            "ix_deep_analysis_evidence_mission_source",
            "mission_id",
            "source_type",
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    source_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("deep_analysis_workflow_nodes.id", ondelete="SET NULL")
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    stable_id: Mapped[str] = mapped_column(String(1000), nullable=False)
    version_id: Mapped[str | None] = mapped_column(String(128))
    content_digest: Mapped[str | None] = mapped_column(String(128))
    locator: Mapped[str] = mapped_column(Text, default="", nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )


class DeepAnalysisClaimEvidenceLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_claim_evidence_links"
    __table_args__ = (
        UniqueConstraint(
            "claim_id",
            "evidence_id",
            "stance",
            name="uq_deep_analysis_claim_evidence_stance",
        ),
    )

    claim_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_claims.id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_evidence_references.id", ondelete="CASCADE"),
        nullable=False,
    )
    stance: Mapped[str] = mapped_column(String(24), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)


class DeepAnalysisOpenIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_open_issues"
    __table_args__ = (
        Index(
            "ix_deep_analysis_open_issues_mission_status",
            "mission_id",
            "status",
        ),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    source_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("deep_analysis_workflow_nodes.id", ondelete="SET NULL")
    )
    issue_type: Mapped[str] = mapped_column(String(40), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)
    materiality: Mapped[str] = mapped_column(
        String(24), default="medium", nullable=False
    )
    residual_amount: Mapped[float | None] = mapped_column(Float)
    residual_percent: Mapped[float | None] = mapped_column(Float)
    required_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    report_inclusion: Mapped[str] = mapped_column(
        String(80), default="open_issues", nullable=False
    )


class DeepAnalysisMissionExport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_mission_exports"
    __table_args__ = (
        Index("ix_deep_analysis_exports_mission_created", "mission_id", "created_at"),
    )

    mission_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    include_originals: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="preparing", nullable=False)
    filename: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(1000))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeepAnalysisWorkflowPattern(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_workflow_patterns"
    __table_args__ = (
        Index("ix_deep_analysis_patterns_project_status", "project_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(24), default="project", nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)


class DeepAnalysisWorkflowPatternVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deep_analysis_workflow_pattern_versions"
    __table_args__ = (
        UniqueConstraint(
            "pattern_id", "version_number", name="uq_deep_analysis_pattern_version"
        ),
    )

    pattern_id: Mapped[str] = mapped_column(
        ForeignKey("deep_analysis_workflow_patterns.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    definition_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_mission_id: Mapped[str | None] = mapped_column(
        ForeignKey("deep_analysis_missions.id", ondelete="SET NULL")
    )
    published_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
