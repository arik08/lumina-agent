from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...agent.executor import local_run_executor
from ...api.schemas import RunActionRequest
from ...config import Settings, get_settings
from ...db import get_db
from ...deep_analysis.execution import create_node_run
from ...deep_analysis.models import DeepAnalysisMission
from ...deep_analysis.schemas import (
    MissionCancel,
    MissionCreate,
    MissionDetailResponse,
    MissionPatch,
    MissionRetry,
    MissionStart,
    MissionSummaryResponse,
)
from ...deep_analysis.service import (
    active_workflow,
    cancel_mission,
    create_mission,
    delete_mission,
    execution_engine_available,
    list_missions,
    require_mission,
    retry_mission_node,
    start_mission,
    update_mission,
    upgrade_legacy_draft_workflow,
)
from ...models import Run, User
from ...runs.broker import event_broker
from ...runs.service import apply_run_action
from ..dependencies import AuthContext, get_current_user, require_csrf


router = APIRouter(tags=["deep-analysis"])


def _summary_payload(mission: DeepAnalysisMission) -> dict[str, object]:
    return {
        "id": mission.id,
        "project_id": mission.project_id,
        "title": mission.title,
        "objective": mission.objective,
        "status": mission.status,
        "start_mode": mission.start_mode,
        "autonomy_mode": mission.autonomy_mode,
        "budget_microusd": mission.budget_microusd,
        "spent_microusd": mission.spent_microusd,
        "revision": mission.revision,
        "created_at": mission.created_at,
        "updated_at": mission.updated_at,
    }


def _detail_payload(db: Session, mission: DeepAnalysisMission) -> dict[str, object]:
    revision, nodes, edges = active_workflow(db, mission.id)
    runs = {
        run.id: run
        for run in db.query(Run).filter(
            Run.id.in_([node.run_id for node in nodes if node.run_id])
        )
    }
    return {
        **_summary_payload(mission),
        "execution_available": execution_engine_available(),
        "charter": mission.charter_json,
        "completion_contract": mission.completion_contract_json,
        "source_manifest": mission.source_manifest_json,
        "workflow": {
            "id": revision.id,
            "revision_number": revision.revision_number,
            "state": revision.state,
            "source": revision.source,
            "reason": revision.reason,
            "graph_digest": revision.graph_digest,
            "change_log": revision.change_log_json,
            "nodes": [
                {
                    "id": node.id,
                    "node_key": node.node_key,
                    "node_type": node.node_type,
                    "title": node.title,
                    "purpose": node.purpose,
                    "status": node.status,
                    "sequence": node.sequence,
                    "position_x": node.position_x,
                    "position_y": node.position_y,
                    "config": node.config_json,
                    "run_id": node.run_id,
                    "output_project_file_id": node.output_project_file_id,
                    "output_logical_path": node.output_logical_path,
                    "output_summary": node.output_summary,
                    "output_markdown": node.output_markdown,
                    "generated_files": node.generated_files_json,
                    "run_history": node.run_history_json,
                    "run_status": (
                        runs[node.run_id].status
                        if node.run_id and node.run_id in runs
                        else None
                    ),
                    "live_output": (
                        runs[node.run_id].assistant_draft[-6_000:]
                        if node.run_id
                        and node.run_id in runs
                        and node.status == "running"
                        else ""
                    ),
                    "error_message": node.error_message,
                    "estimated_cost_microusd": node.estimated_cost_microusd,
                    "actual_cost_microusd": node.actual_cost_microusd,
                    "started_at": node.started_at,
                    "finished_at": node.finished_at,
                }
                for node in nodes
            ],
            "edges": [
                {
                    "id": edge.id,
                    "source_node_key": edge.source_node_key,
                    "target_node_key": edge.target_node_key,
                    "edge_type": edge.edge_type,
                }
                for edge in edges
            ],
            "created_at": revision.created_at,
            "updated_at": revision.updated_at,
        },
    }


@router.get(
    "/projects/{project_id}/deep-analysis/missions",
    response_model=list[MissionSummaryResponse],
)
def get_missions(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    return [
        _summary_payload(mission) for mission in list_missions(db, user, project_id)
    ]


@router.post(
    "/projects/{project_id}/deep-analysis/missions",
    response_model=MissionDetailResponse,
    status_code=201,
)
def post_mission(
    project_id: str,
    payload: MissionCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = create_mission(
        db,
        context.user,
        project_id=project_id,
        title=payload.title,
        objective=payload.objective,
        autonomy_mode=payload.autonomy_mode,
        budget_microusd=payload.budget_microusd,
    )
    record_audit(
        db,
        action="deep_analysis_mission_created",
        target_type="deep_analysis_mission",
        target_id=mission.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"project_id": mission.project_id},
    )
    db.commit()
    return _detail_payload(db, mission)


@router.get(
    "/deep-analysis/missions/{mission_id}",
    response_model=MissionDetailResponse,
)
def get_mission(
    mission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, user, mission_id)
    if upgrade_legacy_draft_workflow(db, mission):
        db.commit()
    return _detail_payload(db, mission)


@router.patch(
    "/deep-analysis/missions/{mission_id}",
    response_model=MissionDetailResponse,
)
def patch_mission(
    mission_id: str,
    payload: MissionPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    update_mission(
        db,
        mission,
        expected_revision=payload.expected_revision,
        title=payload.title,
        objective=payload.objective,
        autonomy_mode=payload.autonomy_mode,
        budget_microusd=payload.budget_microusd,
    )
    record_audit(
        db,
        action="deep_analysis_mission_updated",
        target_type="deep_analysis_mission",
        target_id=mission.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"revision": mission.revision},
    )
    db.commit()
    return _detail_payload(db, mission)


@router.delete("/deep-analysis/missions/{mission_id}", status_code=204)
def remove_mission(
    mission_id: str,
    request: Request,
    expected_revision: int = Query(ge=1),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    mission = require_mission(db, context.user, mission_id, write=True)
    project_id = mission.project_id
    revision = mission.revision
    deleted_file_count = delete_mission(
        db,
        mission,
        expected_revision=expected_revision,
    )
    record_audit(
        db,
        action="deep_analysis_mission_deleted",
        target_type="deep_analysis_mission",
        target_id=mission_id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "project_id": project_id,
            "revision": revision,
            "deleted_file_count": deleted_file_count,
        },
    )
    db.commit()
    return Response(status_code=204)


@router.post(
    "/deep-analysis/missions/{mission_id}/start",
    response_model=MissionDetailResponse,
)
async def post_mission_start(
    mission_id: str,
    payload: MissionStart,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    upgrade_legacy_draft_workflow(db, mission)
    start_mission(db, mission, expected_revision=payload.expected_revision)
    _workflow_revision, nodes, _edges = active_workflow(db, mission.id)
    active_node = next((node for node in nodes if node.status == "running"), None)
    if active_node is None:
        raise RuntimeError("Deep-analysis Workflow has no runnable Node")
    run, created = create_node_run(
        db,
        user=context.user,
        mission=mission,
        node=active_node,
        settings=settings,
    )
    record_audit(
        db,
        action="deep_analysis_mission_started",
        target_type="deep_analysis_mission",
        target_id=mission.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"revision": mission.revision},
    )
    db.commit()
    if created:
        local_run_executor.enqueue(run.id)
        await event_broker.notify(run.id)
    return _detail_payload(db, mission)


@router.post(
    "/deep-analysis/missions/{mission_id}/cancel",
    response_model=MissionDetailResponse,
)
async def post_mission_cancel(
    mission_id: str,
    payload: MissionCancel,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    _workflow_revision, nodes, _edges = active_workflow(db, mission.id)
    active_run_id = next(
        (node.run_id for node in nodes if node.status == "running" and node.run_id),
        None,
    )
    cancel_mission(db, mission, expected_revision=payload.expected_revision)
    cancelled_run = None
    if active_run_id is not None:
        cancelled_run, _command, _message, _changed = apply_run_action(
            db,
            user=context.user,
            run_id=active_run_id,
            payload=RunActionRequest(type="cancel"),
            idempotency_key=(
                f"deep-analysis-cancel:{mission.id}:{payload.expected_revision}"
            ),
        )
    record_audit(
        db,
        action="deep_analysis_mission_cancelled",
        target_type="deep_analysis_mission",
        target_id=mission.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"revision": mission.revision},
    )
    db.commit()
    if cancelled_run is not None:
        local_run_executor.cancel(cancelled_run.id)
        await event_broker.notify(cancelled_run.id)
    return _detail_payload(db, mission)


@router.post(
    "/deep-analysis/missions/{mission_id}/retry",
    response_model=MissionDetailResponse,
)
async def post_mission_retry(
    mission_id: str,
    payload: MissionRetry,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    node = retry_mission_node(
        db,
        mission,
        expected_revision=payload.expected_revision,
        node_key=payload.node_key,
    )
    run, created = create_node_run(
        db,
        user=context.user,
        mission=mission,
        node=node,
        settings=settings,
    )
    record_audit(
        db,
        action="deep_analysis_node_retried",
        target_type="deep_analysis_workflow_node",
        target_id=node.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "mission_id": mission.id,
            "node_key": node.node_key,
            "run_id": run.id,
        },
    )
    db.commit()
    if created:
        local_run_executor.enqueue(run.id)
        await event_broker.notify(run.id)
    return _detail_payload(db, mission)
