from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Plan, PlanStep, PlanSubtask, Run, ToolExecution, new_uuid, utc_now


_TOOL_LABELS = {
    "create_report": "보고서 생성 및 검증",
    "generate_image": "이미지 생성 및 검증",
    "web_search": "웹 검색",
    "web_fetch": "원문 근거 확인",
}


def ensure_tool_subtasks(
    db: Session, run: Run, calls: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    step = _tools_step(db, run.id)
    existing = {
        subtask.tool_call_id: subtask
        for subtask in db.scalars(
            select(PlanSubtask).where(PlanSubtask.plan_step_id == step.id)
        )
    }
    next_position = (
        db.scalar(
            select(func.max(PlanSubtask.position)).where(
                PlanSubtask.plan_step_id == step.id
            )
        )
        or 0
    )
    created: list[PlanSubtask] = []
    for call in calls:
        tool_call_id = str(call.get("id") or "").strip()
        tool_name = str(call.get("name") or "unknown").strip()[:160]
        if not tool_call_id or tool_call_id in existing:
            continue
        next_position += 1
        raw_arguments = str(call.get("arguments") or "{}")
        subtask = PlanSubtask(
            id=new_uuid(),
            plan_step_id=step.id,
            tool_call_id=tool_call_id[:200],
            label=_tool_label(tool_name),
            position=next_position,
            status="queued",
            depends_on_json=[],
            input_snapshot_json={
                "toolName": tool_name,
                "argumentDigest": hashlib.sha256(
                    raw_arguments.encode("utf-8")
                ).hexdigest(),
            },
            result_json={},
            artifact_ids_json=[],
            effect="read_only"
            if tool_name in {"web_search", "web_fetch"}
            else "side_effect",
            attempt=0,
        )
        db.add(subtask)
        existing[tool_call_id] = subtask
        created.append(subtask)
    db.flush()
    return [subtask_payload(item) for item in created]


def bind_tool_subtask(
    db: Session, run_id: str, tool: ToolExecution
) -> dict[str, Any] | None:
    subtask = _subtask_for_call(db, run_id, tool.tool_call_id)
    if subtask is None:
        return None
    subtask.tool_execution_id = tool.id
    subtask.status = "running"
    subtask.attempt += 1
    subtask.started_at = tool.started_at or utc_now()
    subtask.completed_at = None
    subtask.error_code = None
    subtask.error_message = None
    db.flush()
    return subtask_payload(subtask)


def mark_tool_subtask_approval(
    db: Session,
    run_id: str,
    tool_call_id: str,
    *,
    approval_id: str,
    effect: str,
) -> dict[str, Any] | None:
    subtask = _subtask_for_call(db, run_id, tool_call_id)
    if subtask is None:
        return None
    subtask.status = "approval"
    subtask.effect = effect
    subtask.result_json = {"approvalId": approval_id}
    db.flush()
    return subtask_payload(subtask)


def finish_tool_subtask(db: Session, tool: ToolExecution) -> dict[str, Any] | None:
    subtask = db.scalar(
        select(PlanSubtask).where(PlanSubtask.tool_execution_id == tool.id)
    )
    if subtask is None:
        return None
    subtask.status = "completed" if tool.status == "completed" else "failed"
    subtask.completed_at = tool.finished_at or utc_now()
    subtask.result_json = {
        "toolExecutionId": tool.id,
        "status": tool.status,
        "summary": (tool.result_summary or "")[:1000],
    }
    subtask.artifact_ids_json = [tool.artifact_id] if tool.artifact_id else []
    subtask.error_code = tool.error_code
    subtask.error_message = (tool.error_message or "")[:1000] or None
    db.flush()
    return subtask_payload(subtask)


def list_step_subtasks(db: Session, step_id: str) -> list[dict[str, Any]]:
    return [
        subtask_payload(subtask)
        for subtask in db.scalars(
            select(PlanSubtask)
            .where(PlanSubtask.plan_step_id == step_id)
            .order_by(PlanSubtask.position, PlanSubtask.id)
        )
    ]


def subtask_payload(subtask: PlanSubtask) -> dict[str, Any]:
    return {
        "id": subtask.id,
        "toolExecutionId": subtask.tool_execution_id,
        "toolCallId": subtask.tool_call_id,
        "label": subtask.label,
        "order": subtask.position,
        "status": subtask.status,
        "dependsOn": subtask.depends_on_json,
        "inputSnapshot": subtask.input_snapshot_json,
        "result": subtask.result_json,
        "artifactIds": subtask.artifact_ids_json,
        "effect": subtask.effect,
        "attempt": subtask.attempt,
        "errorCode": subtask.error_code,
        "errorMessage": subtask.error_message,
        "startedAt": subtask.started_at,
        "completedAt": subtask.completed_at,
    }


def _tools_step(db: Session, run_id: str) -> PlanStep:
    step = db.scalar(
        select(PlanStep)
        .join(Plan, Plan.id == PlanStep.plan_id)
        .where(Plan.run_id == run_id, PlanStep.step_key == "tools")
    )
    if step is None:
        raise RuntimeError("Run tools Plan step is unavailable")
    return step


def _subtask_for_call(
    db: Session, run_id: str, tool_call_id: str
) -> PlanSubtask | None:
    return db.scalar(
        select(PlanSubtask)
        .join(PlanStep, PlanStep.id == PlanSubtask.plan_step_id)
        .join(Plan, Plan.id == PlanStep.plan_id)
        .where(Plan.run_id == run_id, PlanSubtask.tool_call_id == tool_call_id)
    )


def _tool_label(tool_name: str) -> str:
    if tool_name in _TOOL_LABELS:
        return _TOOL_LABELS[tool_name]
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 3:
            return f"{parts[1]} · {parts[2]}"
    return tool_name.replace("_", " ")[:240] or "도구 실행"


__all__ = [
    "bind_tool_subtask",
    "ensure_tool_subtasks",
    "finish_tool_subtask",
    "list_step_subtasks",
    "mark_tool_subtask_approval",
    "subtask_payload",
]
