from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..providers.types import ProviderAdapter, ProviderMessage, ProviderRequest
from .planning import InitialWorkflowPlan, PlannedNode


MAX_INITIAL_WORKFLOW_NODES = 10
_ALLOWED_NODE_TYPES = {
    "task",
    "scope",
    "research",
    "data_check",
    "analysis",
    "validation",
    "synthesis",
    "report",
}


class _PlannedNodePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ref: str = Field(min_length=1, max_length=40)
    node_type: str = Field(alias="nodeType", min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=2_000)
    depends_on: list[str] = Field(alias="dependsOn", default_factory=list)


class _WorkflowPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1_000)
    nodes: list[_PlannedNodePayload] = Field(
        min_length=2, max_length=MAX_INITIAL_WORKFLOW_NODES
    )


@dataclass(frozen=True, slots=True)
class InitialWorkflowDesign:
    plan: InitialWorkflowPlan


def _response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "deep_analysis_initial_workflow",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "nodes": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": MAX_INITIAL_WORKFLOW_NODES,
                        "items": {
                            "type": "object",
                            "properties": {
                                "ref": {"type": "string"},
                                "nodeType": {
                                    "type": "string",
                                    "enum": sorted(_ALLOWED_NODE_TYPES),
                                },
                                "title": {"type": "string"},
                                "purpose": {"type": "string"},
                                "dependsOn": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "ref",
                                "nodeType",
                                "title",
                                "purpose",
                                "dependsOn",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["reason", "nodes"],
                "additionalProperties": False,
            },
        },
    }


def _json_text(value: str) -> str:
    clean = value.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    start = clean.find("{")
    end = clean.rfind("}")
    return clean[start : end + 1] if start >= 0 and end >= start else clean


def _to_plan(payload: _WorkflowPayload) -> InitialWorkflowPlan:
    refs = [item.ref.strip() for item in payload.nodes]
    if len(set(refs)) != len(refs):
        raise ValueError("Workflow node refs must be unique")
    ref_set = set(refs)
    dependencies = {
        item.ref.strip(): tuple(dict.fromkeys(value.strip() for value in item.depends_on))
        for item in payload.nodes
    }
    for ref, values in dependencies.items():
        if ref in values or any(value not in ref_set for value in values):
            raise ValueError("Workflow contains an invalid dependency")

    pending = list(refs)
    ordered_refs: list[str] = []
    while pending:
        ready = [ref for ref in pending if set(dependencies[ref]) <= set(ordered_refs)]
        if not ready:
            raise ValueError("Workflow must be acyclic")
        for ref in ready:
            ordered_refs.append(ref)
            pending.remove(ref)

    item_by_ref = {item.ref.strip(): item for item in payload.nodes}
    key_by_ref = {
        ref: "N001" if index == 0 else f"N{index * 10:03d}"
        for index, ref in enumerate(ordered_refs)
    }
    planned_nodes: list[PlannedNode] = []
    for ref in ordered_refs:
        item = item_by_ref[ref]
        node_type = item.node_type.strip().lower()
        if node_type not in _ALLOWED_NODE_TYPES:
            raise ValueError("Workflow contains an unsupported node type")
        planned_nodes.append(
            PlannedNode(
                key=key_by_ref[ref],
                node_type=node_type,
                title=item.title.strip(),
                purpose=item.purpose.strip(),
                depends_on=tuple(key_by_ref[value] for value in dependencies[ref]),
            )
        )
    return InitialWorkflowPlan(
        kind="ai_designed",
        reason=payload.reason.strip(),
        nodes=tuple(planned_nodes),
    )


async def design_initial_workflow(
    *,
    provider: ProviderAdapter,
    model: str,
    title: str,
    objective: str,
    effort: str | None,
    instruction: str = "",
) -> InitialWorkflowDesign:
    prompt = (
        "다음 Mission을 사람이 여러 채팅에서 순서대로 수행한다고 생각하고, 그 작업을 "
        "2~10개의 Node와 Edge로 자동화할 초기 Workflow를 설계하세요. 각 Node는 독립된 "
        "채팅 세션이며 purpose는 그 세션에 전달할 구체적인 작업 프롬프트입니다. 보통 "
        "3~7개 Node면 충분합니다. 서로 독립적으로 수행할 가치가 있을 때만 분기하고, "
        "뒤 Node가 두 결과를 함께 써야 할 때만 합류하세요. Claim Ledger, Evidence 추출, "
        "Quality Gate, 법률식 검토 단계나 형식적인 단계를 추가하지 마세요. 최종 보고서가 "
        "목표에 필요하면 마지막 report Node를 두되, 모든 Workflow에 억지로 강제하지 마세요.\n\n"
        f"Mission: {title.strip()}\n설명: {objective.strip()}"
    )
    if instruction.strip():
        prompt += f"\n\nWorkflow 재설계 요청:\n{instruction.strip()}"
    chunks: list[str] = []
    async for event in provider.stream(
        ProviderRequest(
            model=model,
            messages=(
                ProviderMessage(
                    role="system",
                    content="Return only the initial workflow in the strict JSON schema.",
                ),
                ProviderMessage(role="user", content=prompt),
            ),
            effort=None if effort == "auto" else effort,
            response_format=_response_format(),
            max_output_tokens=2_400,
            temperature=0,
            metadata={"purpose": "deep_analysis_initial_workflow"},
        )
    ):
        if event.type == "text_delta" and event.text:
            chunks.append(event.text)
    try:
        payload = _WorkflowPayload.model_validate_json(_json_text("".join(chunks)))
        return InitialWorkflowDesign(plan=_to_plan(payload))
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Provider returned an invalid Deep Analysis workflow") from exc
