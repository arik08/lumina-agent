from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from ..api.schemas import ApiModel, MessageReferenceInput


class MissionCreate(ApiModel):
    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(default="", max_length=20_000)
    autonomy_mode: Literal["guided", "balanced", "autonomous"] = "balanced"
    budget_microusd: int | None = Field(default=None, ge=0)
    analysis_depth: Literal["auto", "brief", "standard", "deep"] = "auto"
    answer_length: Literal["auto", "brief", "standard", "detailed"] = "auto"
    output_mode: Literal["auto", "chat", "file"] = "auto"
    target_output_tokens: int | None = Field(default=10_000, ge=1, le=40_000)
    prompt_references: list[MessageReferenceInput] = Field(default_factory=list, max_length=100)


class MissionPatch(ApiModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    objective: str | None = Field(default=None, max_length=20_000)
    autonomy_mode: Literal["guided", "balanced", "autonomous"] | None = None
    budget_microusd: int | None = Field(default=None, ge=0)
    is_favorite: bool | None = None
    is_liked: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "MissionPatch":
        if all(
            value is None
            for value in (
                self.title,
                self.objective,
                self.autonomy_mode,
                self.budget_microusd,
                self.is_favorite,
                self.is_liked,
            )
        ):
            raise ValueError("at least one mission field is required")
        return self


class MissionMove(ApiModel):
    project_id: str


class MissionStart(ApiModel):
    expected_revision: int = Field(ge=1)


class MissionCancel(ApiModel):
    expected_revision: int = Field(ge=1)


class MissionPause(ApiModel):
    expected_revision: int = Field(ge=1)


class MissionRetry(ApiModel):
    expected_revision: int = Field(ge=1)
    node_key: str = Field(min_length=1, max_length=32)


class MissionQualityGate(ApiModel):
    expected_revision: int = Field(ge=1)


class MissionExportCreate(ApiModel):
    pass


class MissionExportResponse(ApiModel):
    id: str
    mission_id: str
    scope: str
    include_originals: bool
    status: str
    filename: str
    content_hash: str | None
    size_bytes: int | None
    manifest: dict[str, Any]
    error_message: str
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MissionEventResponse(ApiModel):
    mission_id: str
    sequence: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class MissionCostRow(ApiModel):
    node_key: str
    node_title: str
    stage: str
    attempt: int
    is_retry: bool
    run_id: str
    status: str
    provider_id: str
    model_key: str
    model_display_name: str
    date: str
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    uncached_input_tokens: int
    output_tokens: int
    actual_cost_microusd: int
    no_cache_cost_microusd: int | None
    estimated_cache_saving_microusd: int | None
    pricing_version: str | None
    cost_basis: str


class MissionCostResponse(ApiModel):
    mission_id: str
    spent_microusd: int
    budget_microusd: int | None
    budget_usage_ratio: float | None
    estimated_completion_microusd: int
    no_cache_upper_bound_microusd: int
    estimated_cache_saving_microusd: int
    cache_hit_ratio: float
    totals: dict[str, int]
    rows: list[MissionCostRow]


class MissionFileResponse(ApiModel):
    id: str
    project_file_id: str
    project_file_version_id: str
    logical_path: str
    version: int
    content_hash: str
    producing_node_key: str | None
    producing_run_id: str | None
    purpose: str
    validation_status: str
    stale_status: str
    metadata: dict[str, Any]
    created_at: datetime


class WorkflowDraftCreate(ApiModel):
    expected_revision: int = Field(ge=1)


class WorkflowRegenerate(ApiModel):
    expected_revision: int = Field(ge=1)
    prompt: str = Field(min_length=1, max_length=20_000)


class WorkflowDraftNode(ApiModel):
    node_key: str = Field(min_length=1, max_length=32)
    node_type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=240)
    purpose: str = Field(default="", max_length=20_000)
    position_x: int = Field(ge=-100_000, le=100_000)
    position_y: int = Field(ge=-100_000, le=100_000)
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowDraftEdge(ApiModel):
    source_node_key: str = Field(min_length=1, max_length=32)
    target_node_key: str = Field(min_length=1, max_length=32)


class WorkflowDraftPatch(ApiModel):
    expected_revision: int = Field(ge=1)
    nodes: list[WorkflowDraftNode] = Field(min_length=1, max_length=200)
    edges: list[WorkflowDraftEdge] = Field(default_factory=list, max_length=1000)


class PatternCreate(ApiModel):
    mission_id: str
    name: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)


class PatternVersionCreate(ApiModel):
    mission_id: str
    change_summary: str = Field(default="", max_length=4000)


class PatternVersionResponse(ApiModel):
    id: str
    pattern_id: str
    version_number: int
    status: str
    definition_digest: str
    definition: dict[str, Any]
    change_summary: str
    source_mission_id: str | None
    published_by_user_id: str | None
    published_at: datetime | None
    created_at: datetime


class PatternResponse(ApiModel):
    id: str
    project_id: str | None
    scope: str
    name: str
    description: str
    status: str
    latest_published_version: PatternVersionResponse | None
    created_at: datetime
    updated_at: datetime


class DecisionAnswer(ApiModel):
    expected_revision: int = Field(ge=1)
    selected_option_id: str = Field(min_length=1, max_length=64)
    answer_text: str = Field(default="", max_length=4000)


class DecisionResponse(ApiModel):
    id: str
    mission_id: str
    workflow_revision_id: str
    requested_by_node_key: str | None
    question: str
    options: list[dict[str, Any]]
    recommendation_option_id: str | None
    recommendation_rationale: str
    impact: dict[str, Any]
    affected_node_keys: list[str]
    status: str
    selected_option_id: str | None
    answer_text: str
    decided_by_user_id: str | None
    applied_workflow_revision_number: int | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class QualityGateResponse(ApiModel):
    id: str
    workflow_revision_id: str
    report_node_key: str | None
    parent_result_id: str | None
    waiver_decision_id: str | None
    result: str
    completion_outcome: str
    checks: list[dict[str, Any]]
    failure_reasons: list[str]
    evaluated_at: datetime
    created_at: datetime


class EvidenceResponse(ApiModel):
    id: str
    source_node_key: str | None
    source_type: str
    stable_id: str
    version_id: str | None
    content_digest: str | None
    locator: str
    title: str
    metadata: dict[str, Any]
    created_at: datetime


class ClaimEvidenceResponse(ApiModel):
    evidence: EvidenceResponse
    stance: str
    rationale: str


class ClaimResponse(ApiModel):
    id: str
    source_node_key: str | None
    statement: str
    level: str
    status: str
    confidence: float | None
    materiality: str
    report_inclusion: str
    validation: dict[str, Any]
    stale_status: str
    evidence: list[ClaimEvidenceResponse]
    created_at: datetime
    updated_at: datetime


class OpenIssueResponse(ApiModel):
    id: str
    source_node_key: str | None
    issue_type: str
    statement: str
    status: str
    materiality: str
    residual_amount: float | None
    residual_percent: float | None
    required_action: str
    report_inclusion: str
    created_at: datetime
    updated_at: datetime


class WorkflowNodeResponse(ApiModel):
    id: str
    node_key: str
    node_type: str
    title: str
    purpose: str
    status: str
    sequence: int
    position_x: int
    position_y: int
    config: dict[str, Any]
    conversation_id: str | None
    run_id: str | None
    output_project_file_id: str | None
    output_logical_path: str | None
    output_summary: str
    output_markdown: str
    generated_files: list[dict[str, Any]]
    run_history: list[dict[str, Any]]
    run_status: str | None
    execution_prompt: str | None
    context_manifest: dict[str, Any] | None
    live_output: str
    error_message: str | None
    actual_cost_microusd: int
    started_at: datetime | None
    finished_at: datetime | None


class WorkflowEdgeResponse(ApiModel):
    id: str
    source_node_key: str
    target_node_key: str
    edge_type: str


class WorkflowRevisionResponse(ApiModel):
    id: str
    revision_number: int
    state: str
    source: str
    reason: str
    graph_digest: str
    change_log: list[dict[str, Any]]
    nodes: list[WorkflowNodeResponse]
    edges: list[WorkflowEdgeResponse]
    created_at: datetime
    updated_at: datetime


class MissionSummaryResponse(ApiModel):
    id: str
    project_id: str
    title: str
    is_favorite: bool
    is_liked: bool
    objective: str
    status: str
    start_mode: str
    pattern_version_id: str | None
    autonomy_mode: str
    analysis_depth: str
    answer_length: str
    output_mode: str
    target_output_tokens: int | None
    prompt_references: list[dict[str, Any]]
    budget_microusd: int | None
    spent_microusd: int
    completion_outcome: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


class MissionDetailResponse(MissionSummaryResponse):
    execution_available: bool
    event_cursor: int
    source_manifest: list[dict[str, Any]]
    files: list[MissionFileResponse]
    workflow: WorkflowRevisionResponse
