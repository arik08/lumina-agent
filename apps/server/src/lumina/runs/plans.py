from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..models import Plan, PlanStep, PlanSubtask, Run, new_uuid, utc_now
from .events import append_event
from .state import COMPLETED, QUEUED, TERMINAL_STATUSES
from .subtasks import list_step_subtasks
from .transitions import transition_run

PLAN_STEP_QUEUED = "queued"
PLAN_STEP_RUNNING = "running"
PLAN_STEP_BLOCKED = "blocked"
PLAN_STEP_COMPLETED = "completed"
PLAN_STEP_FAILED = "failed"
PLAN_STEP_CANCELLED = "cancelled"

WORK_PLAN_PHASES = {
    "planning",
    "research",
    "analysis",
    "drafting",
    "validation",
    "other",
}

_PLAN_STEP_TRANSITIONS = {
    PLAN_STEP_QUEUED: {
        PLAN_STEP_RUNNING,
        PLAN_STEP_BLOCKED,
        PLAN_STEP_COMPLETED,
        PLAN_STEP_CANCELLED,
    },
    PLAN_STEP_RUNNING: {
        PLAN_STEP_BLOCKED,
        PLAN_STEP_COMPLETED,
        PLAN_STEP_FAILED,
        PLAN_STEP_CANCELLED,
    },
    PLAN_STEP_BLOCKED: {
        PLAN_STEP_QUEUED,
        PLAN_STEP_RUNNING,
        PLAN_STEP_FAILED,
        PLAN_STEP_CANCELLED,
    },
    PLAN_STEP_FAILED: {PLAN_STEP_QUEUED},
    PLAN_STEP_CANCELLED: {PLAN_STEP_QUEUED},
    PLAN_STEP_COMPLETED: set(),
}


def create_run_plan(db: Session, run: Run, *, goal: str) -> Plan:
    existing = db.scalar(select(Plan).where(Plan.run_id == run.id))
    if existing is not None:
        return existing

    plan = Plan(run_id=run.id, goal=goal.strip(), status="active")
    db.add(plan)
    db.flush()
    step_specs = _dynamic_plan_step_specs(run, goal)
    previous_step_id: str | None = None
    for position, (step_key, label, effect, input_snapshot) in enumerate(
        step_specs, start=1
    ):
        step = PlanStep(
            id=new_uuid(),
            plan_id=plan.id,
            step_key=step_key,
            label=label,
            position=position,
            status=PLAN_STEP_QUEUED,
            depends_on_json=[previous_step_id] if previous_step_id else [],
            input_snapshot_json=input_snapshot,
            result_json={},
            artifact_ids_json=[],
            effect=effect,
            attempt=0,
        )
        db.add(step)
        previous_step_id = step.id
    db.flush()
    snapshot = _plan_snapshot_payload(db, run)
    append_event(db, run, "plan_created", {"plan": snapshot})
    return plan


def _dynamic_plan_step_specs(
    run: Run, goal: str
) -> tuple[tuple[str, str, str, dict[str, Any]], ...]:
    normalized = goal.casefold()
    if any(
        token in normalized
        for token in ("보고서", "report", "조사", "리서치", "동향", "비교", "분석")
    ):
        labels = (
            "요청 범위와 조사 기준을 정리합니다",
            "관련 자료를 탐색하고 근거를 수집합니다",
            "핵심 내용을 분석하고 결과를 구조화합니다",
            "결과를 검증하고 보고서를 전달합니다",
        )
    elif any(
        token in normalized
        for token in (
            "코드",
            "구현",
            "수정",
            "버그",
            "리팩터",
            "테스트",
            "build",
            "fix",
        )
    ):
        labels = (
            "요청과 관련된 코드의 영향 범위를 확인합니다",
            "변경 방향을 설계하고 구현합니다",
            "테스트와 실제 동작을 검증합니다",
            "변경 결과를 정리하고 전달합니다",
        )
    elif any(
        token in normalized
        for token in ("표", "엑셀", "데이터", "csv", "xlsx", "통계", "차트")
    ):
        labels = (
            "데이터 범위와 산출물 기준을 확인합니다",
            "데이터를 정리하고 분석합니다",
            "표와 시각화 결과를 검증합니다",
            "분석 결과와 산출물을 전달합니다",
        )
    elif any(
        token in normalized for token in ("파일", "문서", "pdf", "docx", "pptx", "요약")
    ):
        labels = (
            "대상 문서와 요청 범위를 확인합니다",
            "문서 내용을 분석하고 핵심 정보를 추출합니다",
            "결과 구성과 산출물을 검증합니다",
            "완성된 결과를 전달합니다",
        )
    else:
        labels = (
            "요청 목표와 제약을 확인합니다",
            "필요한 정보를 확인하고 작업을 수행합니다",
            "결과를 검토하고 정확성을 확인합니다",
            "최종 답변을 정리하고 전달합니다",
        )

    return (
        (
            "prepare",
            labels[0],
            "read_only",
            {
                "project_id": run.project_id,
                "attachment_ids": run.snapshot_json.get("attachments", []),
                "prompt_references": run.snapshot_json.get("prompt_references", []),
            },
        ),
        (
            "model",
            labels[1],
            "read_only",
            {
                "execution": run.snapshot_json.get("execution", {}),
                "prompt_prefix_hash": run.snapshot_json.get("prompt_prefix_hash"),
            },
        ),
        (
            "tools",
            labels[2],
            "side_effect",
            {
                "allowed_tools": ["create_report", "web_search", "web_fetch"],
                "approval_mode": run.approval_mode,
            },
        ),
        (
            "final",
            labels[3],
            "read_only",
            {"assistant_message_id": run.snapshot_json.get("assistant_message_id")},
        ),
    )


def plan_snapshot(db: Session, run: Run) -> dict[str, Any] | None:
    plan = db.scalar(select(Plan).where(Plan.run_id == run.id))
    if plan is None:
        return None
    steps = list(
        db.scalars(
            select(PlanStep)
            .where(PlanStep.plan_id == plan.id)
            .order_by(PlanStep.position, PlanStep.id)
        )
    )
    return {
        "id": plan.id,
        "goal": plan.goal,
        "status": plan.status,
        "steps": [_plan_step_payload(db, step) for step in steps],
        "createdAt": plan.created_at,
        "updatedAt": plan.updated_at,
    }


def plan_snapshots(
    db: Session, runs: Sequence[Run]
) -> dict[str, dict[str, Any] | None]:
    run_ids = [run.id for run in runs]
    if not run_ids:
        return {}
    plans = list(db.scalars(select(Plan).where(Plan.run_id.in_(run_ids))))
    plans_by_run = {plan.run_id: plan for plan in plans}
    plan_ids = [plan.id for plan in plans]
    steps = (
        list(
            db.scalars(
                select(PlanStep)
                .where(PlanStep.plan_id.in_(plan_ids))
                .order_by(PlanStep.plan_id, PlanStep.position, PlanStep.id)
            )
        )
        if plan_ids
        else []
    )
    step_ids = [step.id for step in steps]
    subtasks = (
        list(
            db.scalars(
                select(PlanSubtask)
                .where(PlanSubtask.plan_step_id.in_(step_ids))
                .order_by(
                    PlanSubtask.plan_step_id,
                    PlanSubtask.position,
                    PlanSubtask.id,
                )
            )
        )
        if step_ids
        else []
    )
    from .subtasks import subtask_payload

    subtasks_by_step: dict[str, list[dict[str, Any]]] = {}
    for subtask in subtasks:
        subtasks_by_step.setdefault(subtask.plan_step_id, []).append(
            subtask_payload(subtask)
        )
    steps_by_plan: dict[str, list[dict[str, Any]]] = {}
    for step in steps:
        payload = _plan_step_payload(db, step, include_subtasks=False)
        payload["subtasks"] = subtasks_by_step.get(step.id, [])
        steps_by_plan.setdefault(step.plan_id, []).append(payload)
    return {
        run.id: (
            {
                "id": plan.id,
                "goal": plan.goal,
                "status": plan.status,
                "steps": steps_by_plan.get(plan.id, []),
                "createdAt": plan.created_at,
                "updatedAt": plan.updated_at,
            }
            if (plan := plans_by_run.get(run.id)) is not None
            else None
        )
        for run in runs
    }


def update_work_plan(
    db: Session,
    run: Run,
    *,
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist the model-authored, user-visible work plan for a Run."""
    if not 1 <= len(steps) <= 8:
        raise ValueError("업무 계획은 1개 이상 8개 이하의 단계여야 합니다.")

    previous_value = run.snapshot_json.get("work_plan", [])
    previous = previous_value if isinstance(previous_value, list) else []
    previous_ids = {
        str(item.get("step", "")).strip().casefold(): str(item.get("id"))
        for item in previous
        if isinstance(item, dict) and item.get("id")
    }
    previous_ids_by_order: dict[int, str] = {}
    previous_phases_by_order: dict[int, str] = {}
    for item in previous:
        if not isinstance(item, dict):
            continue
        order_value = item.get("order")
        if not isinstance(order_value, int) or isinstance(order_value, bool):
            continue
        item_id = item.get("id")
        if item_id:
            previous_ids_by_order[order_value] = str(item_id)
        phase_value = item.get("phase")
        if isinstance(phase_value, str) and phase_value in WORK_PLAN_PHASES:
            previous_phases_by_order[order_value] = phase_value
    normalized: list[dict[str, Any]] = []
    active_count = 0
    for order, item in enumerate(steps, start=1):
        if not isinstance(item, dict):
            raise ValueError("각 업무 계획 단계는 객체여야 합니다.")
        label = " ".join(str(item.get("step", "")).split())
        if not label or len(label) > 240:
            raise ValueError("업무 계획 단계명은 1자 이상 240자 이하여야 합니다.")
        status = str(item.get("status", "pending"))
        if status not in {"pending", "in_progress", "completed"}:
            raise ValueError("업무 계획 상태가 올바르지 않습니다.")
        phase = item.get("phase")
        if phase is None:
            phase = previous_phases_by_order.get(order) or _infer_work_plan_phase(label)
        if phase not in WORK_PLAN_PHASES:
            raise ValueError("업무 계획 단계 성격이 올바르지 않습니다.")
        if status == "in_progress":
            active_count += 1
        normalized.append(
            {
                "id": previous_ids.get(label.casefold())
                or previous_ids_by_order.get(order)
                or new_uuid(),
                "step": label,
                "status": status,
                "order": order,
                "phase": phase,
            }
        )
    if active_count > 1:
        raise ValueError("동시에 진행 중인 업무 계획 단계는 하나만 허용됩니다.")
    if (
        run.status not in TERMINAL_STATUSES
        and normalized
        and all(item["status"] == "completed" for item in normalized)
    ):
        raise ValueError(
            "Run이 진행 중일 때 업무 계획 전체를 완료할 수 없습니다. "
            "최종 답변 작성도 실제 작업으로 판단하여 해당 단계를 직접 추가하거나 "
            "선택하고 in_progress로 유지해 주세요."
        )

    run.snapshot_json = {**run.snapshot_json, "work_plan": normalized}
    append_event(db, run, "work_plan_updated", {"steps": normalized})
    db.flush()
    return normalized


def _infer_work_plan_phase(label: str) -> str:
    """Classify legacy plan rows that predate explicit phase metadata."""
    normalized = " ".join(label.casefold().split())
    report_nouns = ("보고서", "report")
    drafting_actions = (
        "작성",
        "생성",
        "제작",
        "구성",
        "write",
        "draft",
        "create",
        "compose",
        "generate",
        "produce",
    )
    if any(noun in normalized for noun in report_nouns) and any(
        action in normalized for action in drafting_actions
    ):
        return "drafting"
    return "other"


def align_work_plan_for_tool_start(
    db: Session,
    run: Run,
    *,
    tool_name: str,
) -> list[dict[str, Any]] | None:
    """Align the user-visible plan with an authoritative streaming tool phase."""
    target_phase = {"create_report": "drafting"}.get(tool_name)
    if target_phase is None:
        return None

    previous = run.snapshot_json.get("work_plan", [])
    if not isinstance(previous, list) or not previous:
        return None
    steps = [dict(item) for item in previous if isinstance(item, dict)]
    if len(steps) != len(previous):
        return None

    active_index = next(
        (
            index
            for index, item in enumerate(steps)
            if item.get("status") == "in_progress"
        ),
        None,
    )
    if (
        active_index is not None
        and (
            steps[active_index].get("phase")
            or _infer_work_plan_phase(str(steps[active_index].get("step", "")))
        )
        == target_phase
    ):
        return None

    target_index = next(
        (
            index
            for index, item in enumerate(steps)
            if item.get("status") != "completed"
            and (item.get("phase") or _infer_work_plan_phase(str(item.get("step", ""))))
            == target_phase
            and (active_index is None or index > active_index)
        ),
        None,
    )
    if target_index is None:
        return None

    changed = False
    for index, item in enumerate(steps):
        current_status_value = item.get("status")
        current_status = (
            current_status_value
            if isinstance(current_status_value, str)
            and current_status_value in {"pending", "in_progress", "completed"}
            else "pending"
        )
        if index < target_index:
            next_status = "completed"
        elif index == target_index:
            next_status = "in_progress"
        elif current_status == "in_progress":
            next_status = "pending"
        else:
            next_status = current_status
        if next_status != current_status_value:
            item["status"] = next_status
            changed = True
    if not changed:
        return None

    run.snapshot_json = {**run.snapshot_json, "work_plan": steps}
    append_event(db, run, "work_plan_updated", {"steps": steps})
    db.flush()
    return steps


def _plan_step_payload(
    db: Session, step: PlanStep, *, include_subtasks: bool = True
) -> dict[str, Any]:
    payload = {
        "id": step.id,
        "key": step.step_key,
        "label": step.label,
        "status": step.status,
        "order": step.position,
        "dependsOn": step.depends_on_json,
        "inputSnapshot": step.input_snapshot_json,
        "result": step.result_json,
        "artifactIds": step.artifact_ids_json,
        "effect": step.effect,
        "attempt": step.attempt,
        "idempotencyKey": step.idempotency_key,
        "startedAt": step.started_at,
        "completedAt": step.completed_at,
        "errorCode": step.error_code,
        "error": step.error_message,
    }
    if include_subtasks:
        payload["subtasks"] = list_step_subtasks(db, step.id)
    return payload


def _plan_snapshot_payload(db: Session, run: Run) -> dict[str, Any]:
    snapshot = plan_snapshot(db, run)
    if snapshot is None:
        raise ApiProblem(409, "plan_missing", "Run의 Plan을 찾을 수 없습니다.")
    return jsonable_encoder(snapshot)


def _plan_rows(db: Session, run: Run) -> tuple[Plan, list[PlanStep]]:
    plan = db.scalar(select(Plan).where(Plan.run_id == run.id))
    if plan is None:
        raise ApiProblem(409, "plan_missing", "Run의 Plan을 찾을 수 없습니다.")
    steps = list(
        db.scalars(
            select(PlanStep)
            .where(PlanStep.plan_id == plan.id)
            .order_by(PlanStep.position, PlanStep.id)
        )
    )
    return plan, steps


def _step_by_key(db: Session, run: Run, step_key: str) -> PlanStep:
    plan, _steps = _plan_rows(db, run)
    step = db.scalar(
        select(PlanStep).where(
            PlanStep.plan_id == plan.id, PlanStep.step_key == step_key
        )
    )
    if step is None:
        raise ApiProblem(409, "plan_step_missing", "Plan Step을 찾을 수 없습니다.")
    return step


def _refresh_plan_status(plan: Plan, steps: list[PlanStep]) -> None:
    statuses = {step.status for step in steps}
    if steps and statuses == {PLAN_STEP_COMPLETED}:
        plan.status = "completed"
    elif PLAN_STEP_FAILED in statuses:
        plan.status = "failed"
    elif PLAN_STEP_BLOCKED in statuses:
        plan.status = "paused"
    elif statuses <= {PLAN_STEP_COMPLETED, PLAN_STEP_CANCELLED}:
        plan.status = "cancelled"
    else:
        plan.status = "active"
    plan.updated_at = utc_now()


def change_plan_step(
    db: Session,
    run: Run,
    step_key: str,
    *,
    status: str | None = None,
    result: dict[str, Any] | None = None,
    artifact_ids: Iterable[str] = (),
    error_code: str | None = None,
    error_message: str | None = None,
    changed_subtasks: Iterable[dict[str, Any]] = (),
    reason: str,
) -> PlanStep:
    plan, steps = _plan_rows(db, run)
    step = next((item for item in steps if item.step_key == step_key), None)
    if step is None:
        raise ApiProblem(409, "plan_step_missing", "Plan Step을 찾을 수 없습니다.")
    changed = False
    now = utc_now()
    if status is not None and status != step.status:
        allowed = _PLAN_STEP_TRANSITIONS.get(step.status, set())
        if status not in allowed:
            raise ApiProblem(
                409,
                "invalid_plan_step_transition",
                f"Plan Step을 {step.status}에서 {status}(으)로 변경할 수 없습니다.",
            )
        previous_status = step.status
        step.status = status
        changed = True
        if status == PLAN_STEP_RUNNING:
            if previous_status == PLAN_STEP_QUEUED:
                step.attempt += 1
                step.started_at = now
            elif step.started_at is None:
                step.started_at = now
            step.completed_at = None
            step.error_code = None
            step.error_message = None
        elif status in {
            PLAN_STEP_COMPLETED,
            PLAN_STEP_FAILED,
            PLAN_STEP_CANCELLED,
        }:
            step.completed_at = now
            if status == PLAN_STEP_COMPLETED:
                step.error_code = None
                step.error_message = None
        elif status == PLAN_STEP_QUEUED:
            step.started_at = None
            step.completed_at = None
            step.error_code = None
            step.error_message = None
    if result:
        step.result_json = {**step.result_json, **result}
        changed = True
    new_artifact_ids = list(dict.fromkeys((*step.artifact_ids_json, *artifact_ids)))
    if new_artifact_ids != step.artifact_ids_json:
        step.artifact_ids_json = new_artifact_ids
        changed = True
    if error_code is not None and error_code != step.error_code:
        step.error_code = error_code
        changed = True
    if error_message is not None and error_message != step.error_message:
        step.error_message = error_message
        changed = True
    if not changed:
        return step
    step.updated_at = now
    _refresh_plan_status(plan, steps)
    db.flush()
    changed_subtask_payloads = list(changed_subtasks)
    append_event(
        db,
        run,
        "plan_step_changed",
        {
            "planId": plan.id,
            "planStatus": plan.status,
            "step": _plan_step_payload(db, step, include_subtasks=False),
            **(
                {"subtasks": changed_subtask_payloads}
                if changed_subtask_payloads
                else {}
            ),
            "reason": reason,
        },
    )
    return step


def start_plan_step(db: Session, run: Run, step_key: str, *, reason: str) -> PlanStep:
    step = _step_by_key(db, run, step_key)
    if step.status in {PLAN_STEP_RUNNING, PLAN_STEP_COMPLETED}:
        return step
    return change_plan_step(db, run, step_key, status=PLAN_STEP_RUNNING, reason=reason)


def complete_plan_step(
    db: Session,
    run: Run,
    step_key: str,
    *,
    result: dict[str, Any] | None = None,
    artifact_ids: Iterable[str] = (),
    reason: str,
) -> PlanStep:
    step = _step_by_key(db, run, step_key)
    target = None if step.status == PLAN_STEP_COMPLETED else PLAN_STEP_COMPLETED
    return change_plan_step(
        db,
        run,
        step_key,
        status=target,
        result=result,
        artifact_ids=artifact_ids,
        reason=reason,
    )


def pause_plan(db: Session, run: Run) -> None:
    if db.scalar(select(Plan.id).where(Plan.run_id == run.id)) is None:
        return
    _plan, steps = _plan_rows(db, run)
    step = next(
        (item for item in steps if item.status == PLAN_STEP_RUNNING),
        next((item for item in steps if item.status == PLAN_STEP_QUEUED), None),
    )
    if step is None:
        return
    previous_status = step.status
    run.snapshot_json = {
        **run.snapshot_json,
        "plan_pause": {"step_id": step.id, "previous_status": previous_status},
    }
    change_plan_step(
        db,
        run,
        step.step_key,
        status=PLAN_STEP_BLOCKED,
        reason="run_paused",
    )


def resume_plan(db: Session, run: Run, *, requeue: bool = False) -> None:
    if db.scalar(select(Plan.id).where(Plan.run_id == run.id)) is None:
        return
    marker = run.snapshot_json.get("plan_pause", {})
    _plan, steps = _plan_rows(db, run)
    step = next(
        (
            item
            for item in steps
            if item.status == PLAN_STEP_BLOCKED
            and (not marker or marker.get("step_id") == item.id)
        ),
        None,
    )
    if step is None:
        return
    target = (
        PLAN_STEP_QUEUED
        if requeue or marker.get("previous_status") == PLAN_STEP_QUEUED
        else PLAN_STEP_RUNNING
    )
    change_plan_step(db, run, step.step_key, status=target, reason="run_resumed")
    snapshot = dict(run.snapshot_json)
    snapshot.pop("plan_pause", None)
    run.snapshot_json = snapshot


def cancel_plan(db: Session, run: Run, *, reason: str = "run_cancelled") -> None:
    if db.scalar(select(Plan.id).where(Plan.run_id == run.id)) is None:
        return
    plan, steps = _plan_rows(db, run)
    for step in steps:
        if step.status in {
            PLAN_STEP_QUEUED,
            PLAN_STEP_RUNNING,
            PLAN_STEP_BLOCKED,
        }:
            change_plan_step(
                db,
                run,
                step.step_key,
                status=PLAN_STEP_CANCELLED,
                reason=reason,
            )
    plan.status = "cancelled"
    plan.updated_at = utc_now()
    db.flush()


def fail_plan(db: Session, run: Run, *, code: str, message: str) -> None:
    if db.scalar(select(Plan.id).where(Plan.run_id == run.id)) is None:
        return
    _plan, steps = _plan_rows(db, run)
    active = next(
        (
            item
            for item in steps
            if item.status in {PLAN_STEP_RUNNING, PLAN_STEP_BLOCKED}
        ),
        None,
    )
    if active is None:
        active = next((item for item in steps if item.status == PLAN_STEP_QUEUED), None)
        if active is not None:
            start_plan_step(db, run, active.step_key, reason="failure_boundary")
    if active is not None:
        change_plan_step(
            db,
            run,
            active.step_key,
            status=PLAN_STEP_FAILED,
            error_code=code,
            error_message=message,
            reason="run_failed",
        )
    _plan, steps = _plan_rows(db, run)
    for step in steps:
        if step.status == PLAN_STEP_QUEUED:
            change_plan_step(
                db,
                run,
                step.step_key,
                status=PLAN_STEP_CANCELLED,
                reason="blocked_by_failed_dependency",
            )


def _retryable_plan_step(
    db: Session, run: Run, step_id: str | None
) -> tuple[PlanStep, list[PlanStep]]:
    if not step_id:
        raise ApiProblem(422, "step_id_required", "재실행할 Plan Step을 선택해 주세요.")
    if run.status not in TERMINAL_STATUSES - {COMPLETED}:
        raise ApiProblem(
            409,
            "step_retry_run_not_terminal",
            "종료된 실패·취소 Run의 Step만 재실행할 수 있습니다.",
        )
    plan, steps = _plan_rows(db, run)
    step = next((item for item in steps if item.id == step_id), None)
    if step is None or step.plan_id != plan.id:
        raise ApiProblem(404, "plan_step_not_found", "Plan Step을 찾을 수 없습니다.")
    if step.status not in {PLAN_STEP_FAILED, PLAN_STEP_CANCELLED}:
        raise ApiProblem(
            409,
            "step_retry_invalid_status",
            "실패하거나 취소된 Plan Step만 재실행할 수 있습니다.",
        )
    if step.step_key == "tools":
        raise ApiProblem(
            409,
            "step_retry_checkpoint_unavailable",
            "Tool Step은 저장된 Tool Call checkpoint가 없어 직접 재실행할 수 없습니다.",
        )
    candidates = [item for item in steps if item.position >= step.position]
    for candidate in candidates:
        if (
            candidate.status != PLAN_STEP_COMPLETED
            and candidate.effect != "read_only"
            and candidate.attempt > 0
            and not candidate.idempotency_key
        ):
            raise ApiProblem(
                409,
                "step_retry_unsafe_side_effect",
                "완료 여부를 증명할 수 없는 부작용 Tool 단계가 있어 재실행을 거부했습니다.",
            )
    return step, candidates


def retry_plan_step(db: Session, run: Run, step_id: str | None) -> PlanStep:
    step, candidates = _retryable_plan_step(db, run, step_id)
    for candidate in candidates:
        if candidate.status in {
            PLAN_STEP_FAILED,
            PLAN_STEP_CANCELLED,
            PLAN_STEP_BLOCKED,
        }:
            change_plan_step(
                db,
                run,
                candidate.step_key,
                status=PLAN_STEP_QUEUED,
                reason="step_retry_queued",
            )
    plan, _steps = _plan_rows(db, run)
    plan.status = "active"
    plan.updated_at = utc_now()
    run.queued_at = utc_now()
    run.finished_at = None
    run.error_code = None
    run.error_message = None
    run.assistant_draft = ""
    current_attempt = run.snapshot_json.get("run_attempt", 1)
    if not isinstance(current_attempt, int) or isinstance(current_attempt, bool):
        current_attempt = 1
    run.snapshot_json = {
        **run.snapshot_json,
        "run_attempt": max(current_attempt, 1) + 1,
        "retry": {
            "step_id": step.id,
            "step_key": step.step_key,
            "next_attempt": step.attempt + 1,
            "scheduled_at": utc_now().isoformat(),
        },
    }
    transition_run(db, run, QUEUED)
    db.flush()
    append_event(
        db,
        run,
        "retry_scheduled",
        {"step": _plan_step_payload(db, step), "status": QUEUED},
    )
    return step
