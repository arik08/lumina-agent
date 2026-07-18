from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..authorization import require_project
from ..models import Conversation, ProjectFile, User, utc_now
from .models import (
    DeepAnalysisMission,
    DeepAnalysisWorkflowEdge,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowRevision,
)
from .planning import (
    descendant_node_keys,
    graph_digest,
    initial_change_log,
    initial_workflow_plan,
    plan_edges,
    planned_positions,
)


DEEP_ANALYSIS_EXECUTION_AVAILABLE = True


def execution_engine_available() -> bool:
    return DEEP_ANALYSIS_EXECUTION_AVAILABLE


def _populate_initial_workflow(
    db: Session,
    *,
    revision: DeepAnalysisWorkflowRevision,
    title: str,
    objective: str,
) -> None:
    plan = initial_workflow_plan(title, objective)
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
        autonomy_mode=autonomy_mode,
        budget_microusd=budget_microusd,
        charter_json={"question": objective.strip(), "confirmed": False},
        completion_contract_json={
            "requiredSections": ["결론", "근거", "한계"],
            "qualityGate": "pending",
        },
    )
    db.add(mission)
    db.flush()

    plan = initial_workflow_plan(clean_title, objective.strip())
    revision = DeepAnalysisWorkflowRevision(
        mission_id=mission.id,
        revision_number=1,
        source="generated",
        reason=plan.reason,
        graph_digest=graph_digest(plan.nodes, plan_edges(plan)),
        change_log_json=initial_change_log(plan),
    )
    db.add(revision)
    db.flush()
    _populate_initial_workflow(
        db,
        revision=revision,
        title=clean_title,
        objective=objective.strip(),
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
) -> DeepAnalysisMission:
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
            "question": clean_objective,
        }
    if autonomy_mode is not None:
        values["autonomy_mode"] = autonomy_mode
    if budget_microusd is not None:
        values["budget_microusd"] = budget_microusd
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


def delete_mission(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
) -> int:
    if mission.status == "running":
        raise ApiProblem(
            409,
            "mission_running",
            "진행 중인 심층분석은 중단한 뒤 삭제해 주세요.",
        )
    hidden_conversation = (
        db.get(Conversation, mission.conversation_id)
        if mission.conversation_id
        else None
    )
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
    if hidden_conversation is not None:
        db.delete(hidden_conversation)
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
            revision=expected_revision + 1,
            charter_json={**mission.charter_json, "confirmed": True},
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

    _revision, nodes, _edges = active_workflow(db, mission.id)
    first_ready_node = next((node for node in nodes if node.status == "ready"), None)
    if first_ready_node is not None:
        first_ready_node.status = "running"
        first_ready_node.started_at = utc_now()
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
            revision=expected_revision + 1,
            completion_contract_json={
                **mission.completion_contract_json,
                "qualityGate": "pending",
            },
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


def cancel_mission(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    expected_revision: int,
) -> DeepAnalysisMission:
    if mission.status == "cancelled":
        return mission
    if mission.status != "running":
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
    return True
