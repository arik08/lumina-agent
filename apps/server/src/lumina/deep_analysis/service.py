from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..authorization import require_project
from ..models import Conversation, ProjectFile, User, utc_now
from .models import (
    DeepAnalysisClaim,
    DeepAnalysisDecision,
    DeepAnalysisDecisionResponse,
    DeepAnalysisMission,
    DeepAnalysisMissionFileLink,
    DeepAnalysisOpenIssue,
    DeepAnalysisWorkflowEdge,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowRevision,
)
from .planning import (
    InitialWorkflowPlan,
    descendant_node_keys,
    graph_digest,
    initial_change_log,
    initial_workflow_plan,
    next_runnable_node,
    plan_edges,
    planned_positions,
)


DEEP_ANALYSIS_EXECUTION_AVAILABLE = True


def default_charter(title: str, objective: str) -> dict[str, object]:
    purpose = objective.strip() or title.strip()
    return {
        "purpose": purpose,
        "keyQuestions": [purpose] if purpose else [],
        "deliverables": ["최종 Markdown 보고서"],
        "audience": "분석 요청자와 의사결정자",
        "inScope": [],
        "outOfScope": [],
        "comparisonBasis": "",
        "qualityStandards": ["확인하지 않은 사실이나 수치를 만들지 않음"],
        "confirmed": False,
    }


def default_completion_contract() -> dict[str, object]:
    return {
        "requiredSections": [],
        "requiredNodeTypes": ["report"],
        "requireReport": True,
        "requireNoFailedNodes": True,
        "requireNoStaleNodes": True,
        "minimumEvidenceCoverage": 0.0,
        "maximumOpenIssues": 0,
        "maximumUnexplainedResidualPercent": None,
        "requiresFinalReview": False,
        "allowWaiver": True,
        "qualityGate": "pending",
    }


def list_decisions(
    db: Session, mission_id: str
) -> list[
    tuple[
        DeepAnalysisDecision,
        DeepAnalysisDecisionResponse | None,
        str | None,
    ]
]:
    decisions = list(
        db.scalars(
            select(DeepAnalysisDecision)
            .where(DeepAnalysisDecision.mission_id == mission_id)
            .order_by(DeepAnalysisDecision.created_at, DeepAnalysisDecision.id)
        )
    )
    if not decisions:
        return []
    responses = {
        response.decision_id: response
        for response in db.scalars(
            select(DeepAnalysisDecisionResponse).where(
                DeepAnalysisDecisionResponse.decision_id.in_(
                    [decision.id for decision in decisions]
                )
            )
        )
    }
    requested_node_ids = [
        decision.requested_by_node_id
        for decision in decisions
        if decision.requested_by_node_id
    ]
    node_keys = (
        {
            node.id: node.node_key
            for node in db.scalars(
                select(DeepAnalysisWorkflowNode).where(
                    DeepAnalysisWorkflowNode.id.in_(requested_node_ids)
                )
            )
        }
        if requested_node_ids
        else {}
    )
    return [
        (
            decision,
            responses.get(decision.id),
            node_keys.get(decision.requested_by_node_id),
        )
        for decision in decisions
    ]


def answer_decision(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    user: User,
    decision_id: str,
    expected_revision: int,
    selected_option_id: str,
    answer_text: str,
) -> tuple[
    DeepAnalysisDecision,
    DeepAnalysisDecisionResponse,
    DeepAnalysisWorkflowNode | None,
    bool,
]:
    decision = db.scalar(
        select(DeepAnalysisDecision).where(
            DeepAnalysisDecision.id == decision_id,
            DeepAnalysisDecision.mission_id == mission.id,
        )
    )
    if decision is None:
        raise ApiProblem(404, "decision_not_found", "판단 요청을 찾을 수 없습니다.")
    existing = db.scalar(
        select(DeepAnalysisDecisionResponse).where(
            DeepAnalysisDecisionResponse.decision_id == decision.id
        )
    )
    clean_text = answer_text.strip()
    if existing is not None:
        if (
            existing.selected_option_id == selected_option_id
            and existing.answer_text == clean_text
        ):
            return decision, existing, None, False
        raise ApiProblem(
            409,
            "decision_already_resolved",
            "이미 확정된 판단은 다른 답으로 덮어쓸 수 없습니다.",
        )
    option_ids = {
        str(option.get("id"))
        for option in decision.options_json
        if isinstance(option, dict) and option.get("id")
    }
    if selected_option_id not in option_ids:
        raise ApiProblem(
            422,
            "invalid_decision_option",
            "판단 요청에 포함된 선택지를 골라 주세요.",
            field="selectedOptionId",
        )
    if mission.status != "awaiting_input" or decision.status != "pending":
        raise ApiProblem(
            409,
            "decision_not_pending",
            "현재 답변을 기다리는 판단 요청이 아닙니다.",
            details={
                "missionStatus": mission.status,
                "decisionStatus": decision.status,
            },
        )
    result = db.execute(
        update(DeepAnalysisMission)
        .where(
            DeepAnalysisMission.id == mission.id,
            DeepAnalysisMission.revision == expected_revision,
            DeepAnalysisMission.status == "awaiting_input",
        )
        .values(status="running", revision=expected_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.refresh(mission)
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러와 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )

    response = DeepAnalysisDecisionResponse(
        decision_id=decision.id,
        selected_option_id=selected_option_id,
        answer_text=clean_text,
        decided_by_user_id=user.id,
    )
    db.add(response)
    decision.status = "resolved"
    decision.resolved_at = utc_now()
    revision, nodes, edges = active_workflow(db, mission.id)
    decision.applied_workflow_revision_number = revision.revision_number
    if decision.requested_by_node_id:
        requesting_node = next(
            (node for node in nodes if node.id == decision.requested_by_node_id),
            None,
        )
        if requesting_node is not None:
            requesting_node.config_json = {
                **requesting_node.config_json,
                "resolvedDecision": {
                    "decisionId": decision.id,
                    "selectedOptionId": selected_option_id,
                },
            }
    if decision.impact_json.get("kind") == "quality_gate_waiver":
        from .quality import resolve_quality_gate_decision

        resolve_quality_gate_decision(
            db,
            mission=mission,
            decision=decision,
            selected_option_id=selected_option_id,
        )
        db.flush()
        db.refresh(mission)
        return decision, response, None, True
    next_node = next_runnable_node(nodes, edges)
    if next_node is None:
        mission.status = "completed"
        mission.completion_contract_json = {
            **mission.completion_contract_json,
            "qualityGate": "completed",
        }
    else:
        next_node.status = "running"
        next_node.started_at = next_node.started_at or utc_now()
    db.flush()
    db.refresh(mission)
    return decision, response, next_node, True


def execution_engine_available() -> bool:
    return DEEP_ANALYSIS_EXECUTION_AVAILABLE


def _populate_initial_workflow(
    db: Session,
    *,
    revision: DeepAnalysisWorkflowRevision,
    title: str,
    objective: str,
    plan: InitialWorkflowPlan | None = None,
) -> None:
    plan = plan or initial_workflow_plan(title, objective)
    positions = planned_positions(plan)
    for index, planned in enumerate(plan.nodes):
        position_x, position_y, sequence = positions[planned.key]
        db.add(
            DeepAnalysisWorkflowNode(
                workflow_revision_id=revision.id,
                node_key=planned.key,
                node_type=planned.node_type,
                title=planned.title,
                purpose=planned.purpose,
                status="ready" if index == 0 else "planned",
                sequence=sequence,
                position_x=position_x,
                position_y=position_y,
                config_json={
                    "origin": "question_hypothesis",
                    "planKind": plan.kind,
                    "reason": plan.reason,
                    "dependsOn": list(planned.depends_on),
                },
            )
        )
    for source, target in plan_edges(plan):
        db.add(
            DeepAnalysisWorkflowEdge(
                workflow_revision_id=revision.id,
                source_node_key=source,
                target_node_key=target,
            )
        )


def _rebuild_draft_workflow(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    workflow: tuple[
        DeepAnalysisWorkflowRevision,
        list[DeepAnalysisWorkflowNode],
        list[DeepAnalysisWorkflowEdge],
    ]
    | None = None,
    action: str = "question_updated",
) -> None:
    revision, nodes, _edges = workflow or active_workflow(db, mission.id)
    if any(node.run_id for node in nodes):
        return
    plan = initial_workflow_plan(mission.title, mission.objective)
    previous = (
        revision.change_log_json[-1].get("after")
        if revision.change_log_json and isinstance(revision.change_log_json[-1], dict)
        else None
    )
    db.execute(
        delete(DeepAnalysisWorkflowEdge).where(
            DeepAnalysisWorkflowEdge.workflow_revision_id == revision.id
        )
    )
    db.execute(
        delete(DeepAnalysisWorkflowNode).where(
            DeepAnalysisWorkflowNode.workflow_revision_id == revision.id
        )
    )
    revision.revision_number += 1
    revision.source = "question_replan"
    revision.reason = plan.reason
    revision.graph_digest = graph_digest(plan.nodes, plan_edges(plan))
    next_log = initial_change_log(plan)[0]
    revision.change_log_json = [
        *revision.change_log_json,
        {
            **next_log,
            "revision": revision.revision_number,
            "action": action,
            "before": previous,
        },
    ]
    _populate_initial_workflow(
        db,
        revision=revision,
        title=mission.title,
        objective=mission.objective,
    )
    db.flush()


def create_mission(
    db: Session,
    user: User,
    *,
    project_id: str,
    title: str,
    objective: str,
    autonomy_mode: str,
    budget_microusd: int | None,
    execution_settings: dict[str, object] | None = None,
    source_manifest: list[dict[str, object]] | None = None,
    pattern_version_id: str | None = None,
    initial_plan: InitialWorkflowPlan | None = None,
    start_mode: str = "ai_fallback",
    planning_metadata: dict[str, object] | None = None,
) -> DeepAnalysisMission:
    project = require_project(db, user, project_id, write=True)
    clean_title = title.strip()
    if not clean_title:
        raise ApiProblem(
            422, "validation_failed", "분석 이름을 입력해 주세요.", field="title"
        )

    mission = DeepAnalysisMission(
        organization_id=project.organization_id,
        project_id=project.id,
        created_by_user_id=user.id,
        title=clean_title,
        objective=objective.strip(),
        start_mode=start_mode,
        autonomy_mode=autonomy_mode,
        budget_microusd=budget_microusd,
        execution_settings_json=execution_settings or {},
        source_manifest_json=source_manifest or [],
        charter_json=default_charter(clean_title, objective),
        completion_contract_json=default_completion_contract(),
    )
    db.add(mission)
    db.flush()

    plan = initial_plan or initial_workflow_plan(clean_title, objective.strip())
    change_log = initial_change_log(plan)
    if planning_metadata:
        change_log[0] = {**change_log[0], "planner": planning_metadata}
    revision = DeepAnalysisWorkflowRevision(
        mission_id=mission.id,
        revision_number=1,
        source="generated",
        reason=plan.reason,
        graph_digest=graph_digest(plan.nodes, plan_edges(plan)),
        change_log_json=change_log,
    )
    db.add(revision)
    db.flush()
    _populate_initial_workflow(
        db,
        revision=revision,
        title=clean_title,
        objective=objective.strip(),
        plan=plan,
    )
    if pattern_version_id:
        from .models import (
            DeepAnalysisWorkflowPattern,
            DeepAnalysisWorkflowPatternVersion,
        )
        from .patterns import apply_pattern_version

        pattern_version = db.get(
            DeepAnalysisWorkflowPatternVersion, pattern_version_id
        )
        pattern = (
            db.get(DeepAnalysisWorkflowPattern, pattern_version.pattern_id)
            if pattern_version is not None
            else None
        )
        if pattern_version is None or pattern is None:
            raise ApiProblem(
                404,
                "pattern_version_not_found",
                "Pattern version을 찾을 수 없습니다.",
            )
        apply_pattern_version(
            db,
            mission=mission,
            revision=revision,
            version=pattern_version,
            pattern=pattern,
        )
    db.flush()
    return mission


def list_missions(
    db: Session, user: User, project_id: str
) -> list[DeepAnalysisMission]:
    project = require_project(db, user, project_id)
    return list(
        db.scalars(
            select(DeepAnalysisMission)
            .where(DeepAnalysisMission.project_id == project.id)
            .order_by(
                DeepAnalysisMission.is_favorite.desc(),
                DeepAnalysisMission.updated_at.desc(), DeepAnalysisMission.id.desc()
            )
        )
    )


def require_mission(
    db: Session, user: User, mission_id: str, *, write: bool = False
) -> DeepAnalysisMission:
    mission = db.get(DeepAnalysisMission, mission_id)
    if mission is None:
        raise ApiProblem(404, "not_found", "심층분석을 찾을 수 없습니다.")
    require_project(db, user, mission.project_id, write=write)
    return mission


def update_mission(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
    title: str | None,
    objective: str | None,
    autonomy_mode: str | None,
    budget_microusd: int | None,
    is_favorite: bool | None,
    is_liked: bool | None,
    charter: dict[str, object] | None = None,
    completion_contract: dict[str, object] | None = None,
) -> DeepAnalysisMission:
    if (
        (charter is not None or completion_contract is not None)
        and mission.status not in {"draft", "ready"}
    ):
        raise ApiProblem(
            409,
            "mission_contract_locked",
            "실행을 시작한 Mission의 계약은 덮어쓸 수 없습니다.",
        )
    values: dict[str, object] = {}
    if title is not None:
        clean_title = title.strip()
        if not clean_title:
            raise ApiProblem(
                422, "validation_failed", "분석 이름을 입력해 주세요.", field="title"
            )
        values["title"] = clean_title
    if objective is not None:
        clean_objective = objective.strip()
        values["objective"] = clean_objective
        values["charter_json"] = {
            **mission.charter_json,
            "purpose": clean_objective,
            "keyQuestions": [clean_objective] if clean_objective else [],
            "confirmed": False,
        }
    if autonomy_mode is not None:
        values["autonomy_mode"] = autonomy_mode
    if budget_microusd is not None:
        values["budget_microusd"] = budget_microusd
    if is_favorite is not None:
        values["is_favorite"] = is_favorite
    if is_liked is not None:
        values["is_liked"] = is_liked
    if charter is not None:
        values["charter_json"] = {
            **charter,
            "confirmed": False,
        }
    if completion_contract is not None:
        values["completion_contract_json"] = {
            **completion_contract,
            "qualityGate": "pending",
        }
    values["revision"] = expected_revision + 1

    result = db.execute(
        update(DeepAnalysisMission)
        .where(
            DeepAnalysisMission.id == mission.id,
            DeepAnalysisMission.revision == expected_revision,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.refresh(mission)
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러와 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )
    db.refresh(mission)
    if mission.status == "draft" and (title is not None or objective is not None):
        _rebuild_draft_workflow(db, mission)
    return mission


def move_mission(
    db: Session,
    user: User,
    mission: DeepAnalysisMission,
    destination_project_id: str,
) -> DeepAnalysisMission:
    destination = require_project(db, user, destination_project_id, write=True)
    if mission.project_id == destination.id:
        return mission
    if mission.status in {"running", "paused", "awaiting_input"}:
        raise ApiProblem(
            409,
            "mission_running",
            "진행 중인 심층분석은 중단한 뒤 프로젝트를 이동해 주세요.",
        )
    linked_file = db.scalar(
        select(DeepAnalysisMissionFileLink.id).where(
            DeepAnalysisMissionFileLink.mission_id == mission.id
        )
    )
    if linked_file is not None:
        raise ApiProblem(
            409,
            "mission_has_project_files",
            "프로젝트 파일을 사용하는 심층분석은 현재 프로젝트에서 유지해 주세요.",
        )
    from ..conversations.service import move_conversation

    revision, nodes, _edges = active_workflow(db, mission.id)
    for node in nodes:
        if node.conversation_id:
            move_conversation(db, user, node.conversation_id, destination.id)
    mission.project_id = destination.id
    mission.revision += 1
    db.flush()
    return mission


def delete_mission(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
) -> int:
    if mission.status in {"running", "paused", "awaiting_input"}:
        raise ApiProblem(
            409,
            "mission_running",
            "진행 중인 심층분석은 중단한 뒤 삭제해 주세요.",
        )
    _workflow_revision, nodes, _edges = active_workflow(db, mission.id)
    conversations = [
        conversation
        for node in nodes
        if node.conversation_id
        and (conversation := db.get(Conversation, node.conversation_id)) is not None
    ]
    result = db.execute(
        delete(DeepAnalysisMission).where(
            DeepAnalysisMission.id == mission.id,
            DeepAnalysisMission.revision == expected_revision,
        )
    )
    if result.rowcount != 1:
        db.refresh(mission)
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러와 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )
    for conversation in conversations:
        db.delete(conversation)
    from .execution import output_directory

    now = utc_now()
    deleted_files = db.execute(
        update(ProjectFile)
        .where(
            ProjectFile.project_id == mission.project_id,
            ProjectFile.deleted_at.is_(None),
            ProjectFile.logical_path.startswith(f"{output_directory(mission)}/"),
        )
        .values(
            active_path_key=None,
            status="deleted",
            deleted_at=now,
            revision=ProjectFile.revision + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    return int(getattr(deleted_files, "rowcount", 0) or 0)


def start_mission(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
) -> DeepAnalysisMission:
    if mission.status == "running":
        return mission
    if not execution_engine_available():
        raise ApiProblem(
            503,
            "deep_analysis_execution_unavailable",
            "심층분석 실행 엔진이 아직 연결되지 않았습니다.",
        )
    if mission.status not in {"draft", "ready"}:
        raise ApiProblem(
            409,
            "mission_not_startable",
            "현재 상태에서는 심층분석을 시작할 수 없습니다.",
            details={"status": mission.status},
        )
    if (
        mission.budget_microusd is not None
        and mission.spent_microusd >= mission.budget_microusd
    ):
        raise ApiProblem(
            409,
            "budget_exhausted",
            "설정한 비용 한도가 남아 있지 않습니다. 예산을 늘린 뒤 다시 시작해 주세요.",
        )

    if not mission.source_manifest_json:
        from .execution import capture_source_manifest

        mission.source_manifest_json = capture_source_manifest(db, mission)

    result = db.execute(
        update(DeepAnalysisMission)
        .where(
            DeepAnalysisMission.id == mission.id,
            DeepAnalysisMission.revision == expected_revision,
        )
        .values(
            status="running",
            completion_outcome=None,
            revision=expected_revision + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.refresh(mission)
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러와 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )

    _revision, nodes, edges = active_workflow(db, mission.id)
    first_runnable_node = next_runnable_node(nodes, edges)
    if first_runnable_node is not None:
        first_runnable_node.status = "running"
        first_runnable_node.started_at = utc_now()
    db.flush()
    db.refresh(mission)
    return mission


def retry_mission_node(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
    node_key: str,
) -> DeepAnalysisWorkflowNode:
    if mission.status not in {"failed", "cancelled", "blocked"}:
        raise ApiProblem(
            409,
            "mission_not_retryable",
            "실패, 중단 또는 확인 필요 상태의 심층분석만 다시 실행할 수 있습니다.",
            details={"status": mission.status},
        )
    revision, nodes, edges = active_workflow(db, mission.id)
    target = next((item for item in nodes if item.node_key == node_key), None)
    if target is None:
        raise ApiProblem(404, "node_not_found", "다시 실행할 Node를 찾을 수 없습니다.")
    retryable_statuses = (
        {"failed", "cancelled", "planned"}
        if mission.status == "blocked"
        else {"failed", "cancelled"}
    )
    if target.status not in retryable_statuses:
        raise ApiProblem(
            409,
            "node_not_retryable",
            "실패·중단된 Node 또는 비용 확인 후 대기 중인 Node만 다시 실행할 수 있습니다.",
            details={"status": target.status},
        )
    if (
        mission.budget_microusd is not None
        and mission.spent_microusd >= mission.budget_microusd
    ):
        raise ApiProblem(
            409,
            "budget_exhausted",
            "설정한 비용 한도가 남아 있지 않습니다. 예산을 늘린 뒤 다시 실행해 주세요.",
        )

    result = db.execute(
        update(DeepAnalysisMission)
        .where(
            DeepAnalysisMission.id == mission.id,
            DeepAnalysisMission.revision == expected_revision,
        )
        .values(
            status="running",
            completion_outcome=None,
            revision=expected_revision + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.refresh(mission)
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러와 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )

    from .execution import archive_current_attempt

    archive_current_attempt(db, target)
    reset_keys = descendant_node_keys(target.node_key, edges)
    reset_node_ids = {node.id for node in nodes if node.node_key in reset_keys}
    if reset_node_ids:
        db.execute(
            update(DeepAnalysisMissionFileLink)
            .where(
                DeepAnalysisMissionFileLink.producing_node_id.in_(reset_node_ids)
            )
            .values(stale_status="review_required")
            .execution_options(synchronize_session=False)
        )
    for node in nodes:
        if node.node_key not in reset_keys:
            continue
        node.status = "running" if node.id == target.id else "planned"
        node.run_id = None
        node.output_project_file_id = None
        node.output_logical_path = None
        node.output_summary = ""
        node.output_markdown = ""
        node.generated_files_json = []
        node.error_message = None
        node.actual_cost_microusd = 0
        node.started_at = utc_now() if node.id == target.id else None
        node.finished_at = None
    db.flush()
    db.refresh(mission)
    return target


def run_quality_gate(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
) -> None:
    if mission.status == "awaiting_input":
        raise ApiProblem(
            409,
            "mission_awaiting_input",
            "먼저 대기 중인 판단 요청에 답해 주세요.",
        )
    workflow_revision, nodes, _edges = active_workflow(db, mission.id)
    report = next(
        (
            node
            for node in reversed(nodes)
            if node.node_type == "report" and node.status == "completed"
        ),
        None,
    )
    if report is None:
        raise ApiProblem(
            409,
            "report_not_ready",
            "완료된 최종 보고서 Node가 있어야 Quality Gate를 실행할 수 있습니다.",
        )
    result = db.execute(
        update(DeepAnalysisMission)
        .where(
            DeepAnalysisMission.id == mission.id,
            DeepAnalysisMission.revision == expected_revision,
        )
        .values(revision=expected_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.refresh(mission)
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러와 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )
    db.refresh(mission)
    from .quality import evaluate_quality_gate

    evaluate_quality_gate(
        db,
        mission=mission,
        revision=workflow_revision,
        report_node=report,
        nodes=nodes,
    )
    db.flush()


def cancel_mission(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
) -> DeepAnalysisMission:
    if mission.status == "cancelled":
        return mission
    if mission.status not in {"running", "paused", "awaiting_input"}:
        raise ApiProblem(
            409,
            "mission_not_cancellable",
            "진행 중인 심층분석만 중단할 수 있습니다.",
            details={"status": mission.status},
        )

    result = db.execute(
        update(DeepAnalysisMission)
        .where(
            DeepAnalysisMission.id == mission.id,
            DeepAnalysisMission.revision == expected_revision,
        )
        .values(status="cancelled", revision=expected_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.refresh(mission)
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러와 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )

    _revision, nodes, _edges = active_workflow(db, mission.id)
    for node in nodes:
        if node.status == "running":
            node.status = "cancelled"
    db.flush()
    db.refresh(mission)
    return mission


def pause_mission(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
) -> DeepAnalysisMission:
    if mission.status == "paused":
        return mission
    if mission.status != "running":
        raise ApiProblem(
            409,
            "mission_not_pausable",
            "진행 중인 심층분석만 일시 정지할 수 있습니다.",
            details={"status": mission.status},
        )
    result = db.execute(
        update(DeepAnalysisMission)
        .where(
            DeepAnalysisMission.id == mission.id,
            DeepAnalysisMission.revision == expected_revision,
        )
        .values(status="paused", revision=expected_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.refresh(mission)
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러와 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )
    db.flush()
    db.refresh(mission)
    return mission


def resume_mission(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
) -> DeepAnalysisMission:
    if mission.status == "running":
        return mission
    if mission.status != "paused":
        raise ApiProblem(
            409,
            "mission_not_resumable",
            "일시 정지된 심층분석만 재개할 수 있습니다.",
            details={"status": mission.status},
        )
    result = db.execute(
        update(DeepAnalysisMission)
        .where(
            DeepAnalysisMission.id == mission.id,
            DeepAnalysisMission.revision == expected_revision,
        )
        .values(status="running", revision=expected_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.refresh(mission)
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러와 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )
    db.flush()
    db.refresh(mission)
    return mission


def active_workflow(
    db: Session, mission_id: str
) -> tuple[
    DeepAnalysisWorkflowRevision,
    list[DeepAnalysisWorkflowNode],
    list[DeepAnalysisWorkflowEdge],
]:
    revision = db.scalar(
        select(DeepAnalysisWorkflowRevision)
        .where(
            DeepAnalysisWorkflowRevision.mission_id == mission_id,
            DeepAnalysisWorkflowRevision.state == "active",
        )
        .order_by(DeepAnalysisWorkflowRevision.revision_number.desc())
    )
    if revision is None:
        raise ApiProblem(409, "workflow_missing", "활성 Workflow가 없습니다.")
    nodes = list(
        db.scalars(
            select(DeepAnalysisWorkflowNode)
            .where(DeepAnalysisWorkflowNode.workflow_revision_id == revision.id)
            .order_by(DeepAnalysisWorkflowNode.sequence)
        )
    )
    edges = list(
        db.scalars(
            select(DeepAnalysisWorkflowEdge)
            .where(DeepAnalysisWorkflowEdge.workflow_revision_id == revision.id)
            .order_by(DeepAnalysisWorkflowEdge.source_node_key)
        )
    )
    return revision, nodes, edges


def workflow_revision(
    db: Session, revision: DeepAnalysisWorkflowRevision
) -> tuple[list[DeepAnalysisWorkflowNode], list[DeepAnalysisWorkflowEdge]]:
    nodes = list(
        db.scalars(
            select(DeepAnalysisWorkflowNode)
            .where(DeepAnalysisWorkflowNode.workflow_revision_id == revision.id)
            .order_by(DeepAnalysisWorkflowNode.sequence)
        )
    )
    edges = list(
        db.scalars(
            select(DeepAnalysisWorkflowEdge)
            .where(DeepAnalysisWorkflowEdge.workflow_revision_id == revision.id)
            .order_by(DeepAnalysisWorkflowEdge.source_node_key, DeepAnalysisWorkflowEdge.target_node_key)
        )
    )
    return nodes, edges


def create_workflow_draft(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
) -> DeepAnalysisWorkflowRevision:
    if mission.revision != expected_revision:
        raise ApiProblem(409, "revision_conflict", "다른 변경사항이 먼저 저장되었습니다.", details={"currentRevision": mission.revision})
    if mission.status not in {"draft", "ready"}:
        raise ApiProblem(409, "workflow_edit_not_allowed", "실행 전 Mission만 Workflow를 편집할 수 있습니다.")
    existing = db.scalar(
        select(DeepAnalysisWorkflowRevision).where(
            DeepAnalysisWorkflowRevision.mission_id == mission.id,
            DeepAnalysisWorkflowRevision.state == "draft",
        )
    )
    if existing is not None:
        return existing
    source, nodes, edges = active_workflow(db, mission.id)
    number = db.scalar(
        select(DeepAnalysisWorkflowRevision.revision_number)
        .where(DeepAnalysisWorkflowRevision.mission_id == mission.id)
        .order_by(DeepAnalysisWorkflowRevision.revision_number.desc())
    ) or 0
    draft = DeepAnalysisWorkflowRevision(
        mission_id=mission.id,
        revision_number=number + 1,
        state="draft",
        source="manual",
        reason=f"active_revision_{source.revision_number}_edited",
        graph_digest=source.graph_digest,
        change_log_json=[*source.change_log_json, {"revision": number + 1, "action": "draft_created", "graphChanged": False, "createdAt": utc_now().isoformat()}],
    )
    db.add(draft)
    db.flush()
    for node in nodes:
        db.add(DeepAnalysisWorkflowNode(
            workflow_revision_id=draft.id, node_key=node.node_key, node_type=node.node_type,
            title=node.title, purpose=node.purpose, status="planned", sequence=node.sequence,
            position_x=node.position_x, position_y=node.position_y, config_json=node.config_json,
        ))
    for edge in edges:
        db.add(DeepAnalysisWorkflowEdge(
            workflow_revision_id=draft.id, source_node_key=edge.source_node_key,
            target_node_key=edge.target_node_key, edge_type=edge.edge_type,
        ))
    db.flush()
    return draft


def update_workflow_draft(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
    nodes_payload: list[dict[str, object]],
    edges_payload: list[dict[str, str]],
) -> DeepAnalysisWorkflowRevision:
    draft = create_workflow_draft(db, mission, expected_revision=expected_revision)
    keys = [str(item["nodeKey"]) for item in nodes_payload]
    if len(keys) != len(set(keys)) or not keys:
        raise ApiProblem(422, "invalid_workflow_nodes", "Node key는 비어 있지 않고 중복될 수 없습니다.")
    edge_pairs = [(item["sourceNodeKey"], item["targetNodeKey"]) for item in edges_payload]
    if len(edge_pairs) != len(set(edge_pairs)) or any(source not in keys or target not in keys or source == target for source, target in edge_pairs):
        raise ApiProblem(422, "invalid_workflow_edges", "연결은 존재하는 서로 다른 Node 사이에서 중복 없이 만들어야 합니다.")
    adjacency: dict[str, list[str]] = {key: [] for key in keys}
    indegree = {key: 0 for key in keys}
    for source, target in edge_pairs:
        adjacency[source].append(target)
        indegree[target] += 1
    queue = [key for key, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        key = queue.pop()
        visited += 1
        for target in adjacency[key]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(keys):
        raise ApiProblem(422, "workflow_cycle", "Workflow 연결에는 순환이 없어야 합니다.")
    db.execute(delete(DeepAnalysisWorkflowEdge).where(DeepAnalysisWorkflowEdge.workflow_revision_id == draft.id))
    db.execute(delete(DeepAnalysisWorkflowNode).where(DeepAnalysisWorkflowNode.workflow_revision_id == draft.id))
    for sequence, item in enumerate(nodes_payload, start=1):
        db.add(DeepAnalysisWorkflowNode(
            workflow_revision_id=draft.id, node_key=str(item["nodeKey"]), node_type=str(item["nodeType"]),
            title=str(item["title"]), purpose=str(item.get("purpose") or ""), status="planned", sequence=sequence,
            position_x=int(item["positionX"]), position_y=int(item["positionY"]),
            config_json=dict(item.get("config") or {}),
        ))
    for source, target in edge_pairs:
        db.add(DeepAnalysisWorkflowEdge(workflow_revision_id=draft.id, source_node_key=source, target_node_key=target, edge_type="sequence"))
    db.flush()
    nodes, edges = workflow_revision(db, draft)
    draft.graph_digest = graph_digest(nodes, edges)
    draft.change_log_json = [*draft.change_log_json, {"revision": draft.revision_number, "action": "manual_edit", "graphChanged": True, "createdAt": utc_now().isoformat()}]
    db.flush()
    return draft


def regenerate_workflow(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
    prompt: str,
    plan: InitialWorkflowPlan,
    planning_metadata: dict[str, object],
) -> DeepAnalysisWorkflowRevision:
    if mission.status in {"running", "paused", "awaiting_input"}:
        raise ApiProblem(
            409,
            "workflow_regeneration_not_allowed",
            "실행 중인 Mission의 Workflow는 재생성할 수 없습니다.",
            details={"status": mission.status},
        )
    result = db.execute(
        update(DeepAnalysisMission)
        .where(
            DeepAnalysisMission.id == mission.id,
            DeepAnalysisMission.revision == expected_revision,
        )
        .values(
            status="ready",
            completion_outcome=None,
            completion_contract_json={
                **mission.completion_contract_json,
                "qualityGate": "pending",
                "latestQualityGateResultId": None,
                "finalOutputFileId": None,
                "finalOutputPath": None,
            },
            revision=expected_revision + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.refresh(mission)
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러온 뒤 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )

    previous_revisions = list(
        db.scalars(
            select(DeepAnalysisWorkflowRevision).where(
                DeepAnalysisWorkflowRevision.mission_id == mission.id,
                DeepAnalysisWorkflowRevision.state.in_(("active", "draft")),
            )
        )
    )
    for previous in previous_revisions:
        previous.state = "archived"
    revision_number = db.scalar(
        select(DeepAnalysisWorkflowRevision.revision_number)
        .where(DeepAnalysisWorkflowRevision.mission_id == mission.id)
        .order_by(DeepAnalysisWorkflowRevision.revision_number.desc())
    ) or 0
    change_log = initial_change_log(plan)
    change_log[0] = {
        **change_log[0],
        "revision": revision_number + 1,
        "action": "workflow_regenerated",
        "regenerationPrompt": prompt.strip(),
        "planner": planning_metadata,
    }
    revision = DeepAnalysisWorkflowRevision(
        mission_id=mission.id,
        revision_number=revision_number + 1,
        state="active",
        source="ai_regenerated",
        reason=plan.reason,
        graph_digest=graph_digest(plan.nodes, plan_edges(plan)),
        change_log_json=change_log,
    )
    db.add(revision)
    db.flush()
    _populate_initial_workflow(
        db,
        revision=revision,
        title=mission.title,
        objective=mission.objective,
        plan=plan,
    )
    db.flush()
    db.refresh(mission)
    return revision


def activate_workflow_draft(
    db: Session, mission: DeepAnalysisMission, *, expected_revision: int
) -> DeepAnalysisWorkflowRevision:
    if mission.revision != expected_revision:
        raise ApiProblem(409, "revision_conflict", "다른 변경사항이 먼저 저장되었습니다.", details={"currentRevision": mission.revision})
    draft = db.scalar(select(DeepAnalysisWorkflowRevision).where(DeepAnalysisWorkflowRevision.mission_id == mission.id, DeepAnalysisWorkflowRevision.state == "draft"))
    if draft is None:
        raise ApiProblem(409, "workflow_draft_missing", "활성화할 Workflow Draft가 없습니다.")
    active, _nodes, _edges = active_workflow(db, mission.id)
    active.state = "archived"
    draft.state = "active"
    mission.revision += 1
    db.flush()
    return draft


def upgrade_legacy_draft_workflow(
    db: Session, mission: DeepAnalysisMission
) -> bool:
    workflow = active_workflow(db, mission.id)
    revision, nodes, _edges = workflow
    if (
        revision.change_log_json
        or mission.status != "draft"
        or any(node.run_id for node in nodes)
    ):
        return False
    _rebuild_draft_workflow(
        db,
        mission,
        workflow=workflow,
        action="legacy_upgraded",
        )
    if mission.status not in {"draft", "ready"}:
        raise ApiProblem(
            409,
            "workflow_edit_not_allowed",
            "실행 전 Mission만 Workflow Draft를 활성화할 수 있습니다.",
        )
    return True
