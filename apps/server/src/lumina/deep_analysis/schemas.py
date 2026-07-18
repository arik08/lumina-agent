from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from ..api.schemas import ApiModel


class MissionCreate(ApiModel):
    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(default="", max_length=20_000)
    autonomy_mode: Literal["guided", "balanced", "autonomous"] = "balanced"
    budget_microusd: int | None = Field(default=None, ge=0)


class MissionCharter(ApiModel):
    purpose: str = Field(default="", max_length=20_000)
    key_questions: list[str] = Field(default_factory=list, max_length=12)
    deliverables: list[str] = Field(default_factory=list, max_length=12)
    audience: str = Field(default="", max_length=500)
    in_scope: list[str] = Field(default_factory=list, max_length=20)
    out_of_scope: list[str] = Field(default_factory=list, max_length=20)
    comparison_basis: str = Field(default="", max_length=2000)
    quality_standards: list[str] = Field(default_factory=list, max_length=20)
    confirmed: bool = False


class CompletionContract(ApiModel):
    required_sections: list[str] = Field(default_factory=list, max_length=12)
    required_node_types: list[str] = Field(default_factory=list, max_length=12)
    require_report: bool = True
    require_no_failed_nodes: bool = True
    require_no_stale_nodes: bool = True
    minimum_evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    maximum_open_issues: int = Field(default=0, ge=0, le=1000)
    maximum_unexplained_residual_percent: float | None = Field(
        default=None, ge=0.0, le=100.0
    )
    requires_final_review: bool = False
    allow_waiver: bool = True


class MissionPatch(ApiModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    objective: str | None = Field(default=None, max_length=20_000)
    autonomy_mode: Literal["guided", "balanced", "autonomous"] | None = None
    budget_microusd: int | None = Field(default=None, ge=0)
    charter: MissionCharter | None = None
    completion_contract: CompletionContract | None = None

    @model_validator(mode="after")
    def require_change(self) -> "MissionPatch":
        if all(
            value is None
            for value in (
                self.title,
                self.objective,
                self.autonomy_mode,
                self.budget_microusd,
                self.charter,
                self.completion_contract,
            )
        ):
            raise ValueError("at least one mission field is required")
        return self


class MissionStart(ApiModel):
    expected_revision: int = Field(ge=1)


class MissionCancel(ApiModel):
    expected_revision: int = Field(ge=1)


class MissionRetry(ApiModel):
    expected_revision: int = Field(ge=1)
    node_key: str = Field(min_length=1, max_length=32)


class MissionQualityGate(ApiModel):
    expected_revision: int = Field(ge=1)


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
    run_id: str | None
    output_project_file_id: str | None
    output_logical_path: str | None
    output_summary: str
    output_markdown: str
    generated_files: list[dict[str, Any]]
    run_history: list[dict[str, Any]]
    run_status: str | None
    live_output: str
    error_message: str | None
    estimated_cost_microusd: int
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
    objective: str
    status: str
    start_mode: str
    autonomy_mode: str
    budget_microusd: int | None
    spent_microusd: int
    completion_outcome: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


class MissionDetailResponse(MissionSummaryResponse):
    execution_available: bool
    charter: dict[str, Any]
    completion_contract: dict[str, Any]
    source_manifest: list[dict[str, Any]]
    decisions: list[DecisionResponse]
    quality_gates: list[QualityGateResponse]
    claims: list[ClaimResponse]
    evidence: list[EvidenceResponse]
    open_issues: list[OpenIssueResponse]
    workflow: WorkflowRevisionResponse
