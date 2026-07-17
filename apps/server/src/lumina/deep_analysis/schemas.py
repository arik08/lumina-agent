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


class MissionPatch(ApiModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    objective: str | None = Field(default=None, max_length=20_000)
    autonomy_mode: Literal["guided", "balanced", "autonomous"] | None = None
    budget_microusd: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_change(self) -> "MissionPatch":
        if all(
            value is None
            for value in (
                self.title,
                self.objective,
                self.autonomy_mode,
                self.budget_microusd,
            )
        ):
            raise ValueError("at least one mission field is required")
        return self


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
    output_summary: str
    estimated_cost_microusd: int
    actual_cost_microusd: int


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
    revision: int
    created_at: datetime
    updated_at: datetime


class MissionDetailResponse(MissionSummaryResponse):
    charter: dict[str, Any]
    completion_contract: dict[str, Any]
    workflow: WorkflowRevisionResponse
