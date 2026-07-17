from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...db import get_db
from ...deep_analysis.models import DeepAnalysisMission
from ...deep_analysis.schemas import (
    MissionCreate,
    MissionDetailResponse,
    MissionPatch,
    MissionSummaryResponse,
)
from ...deep_analysis.service import (
    active_workflow,
    create_mission,
    list_missions,
    require_mission,
    update_mission,
)
from ...models import User
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
    return {
        **_summary_payload(mission),
        "charter": mission.charter_json,
        "completion_contract": mission.completion_contract_json,
        "workflow": {
            "id": revision.id,
            "revision_number": revision.revision_number,
            "state": revision.state,
            "source": revision.source,
            "reason": revision.reason,
            "graph_digest": revision.graph_digest,
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
                    "output_summary": node.output_summary,
                    "estimated_cost_microusd": node.estimated_cost_microusd,
                    "actual_cost_microusd": node.actual_cost_microusd,
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
    return [_summary_payload(mission) for mission in list_missions(db, user, project_id)]


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
    return _detail_payload(db, require_mission(db, user, mission_id))


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
