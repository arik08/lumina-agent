from __future__ import annotations

import hashlib
import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..authorization import require_project
from ..models import User
from .models import (
    DeepAnalysisMission,
    DeepAnalysisWorkflowEdge,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowRevision,
)


DEFAULT_WORKFLOW_NODES = (
    ("N001", "scope", "목표·범위 확정", "분석 질문, 범위와 완료 조건을 확정합니다."),
    ("N010", "data_check", "자료·품질 확인", "필요 자료와 데이터 품질을 확인합니다."),
    ("N020", "analysis", "핵심 분석", "근거와 계산을 바탕으로 핵심 원인을 분석합니다."),
    ("N030", "synthesis", "검증·합성", "가설을 교차 검증하고 결론을 합성합니다."),
    ("N040", "report", "최종 보고서", "결론, 근거와 한계를 보고서로 정리합니다."),
)


def _graph_digest() -> str:
    canonical = json.dumps(DEFAULT_WORKFLOW_NODES, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
        raise ApiProblem(422, "validation_failed", "분석 이름을 입력해 주세요.", field="title")

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

    revision = DeepAnalysisWorkflowRevision(
        mission_id=mission.id,
        revision_number=1,
        source="generated",
        reason="mission_created",
        graph_digest=_graph_digest(),
    )
    db.add(revision)
    db.flush()

    for sequence, (node_key, node_type, node_title, purpose) in enumerate(
        DEFAULT_WORKFLOW_NODES
    ):
        db.add(
            DeepAnalysisWorkflowNode(
                workflow_revision_id=revision.id,
                node_key=node_key,
                node_type=node_type,
                title=node_title,
                purpose=purpose,
                status="ready" if sequence == 0 else "planned",
                sequence=sequence,
                position_x=80 + sequence * 220,
                position_y=180,
                config_json={},
            )
        )
        if sequence:
            db.add(
                DeepAnalysisWorkflowEdge(
                    workflow_revision_id=revision.id,
                    source_node_key=DEFAULT_WORKFLOW_NODES[sequence - 1][0],
                    target_node_key=node_key,
                )
            )
    db.flush()
    return mission


def list_missions(db: Session, user: User, project_id: str) -> list[DeepAnalysisMission]:
    project = require_project(db, user, project_id)
    return list(
        db.scalars(
            select(DeepAnalysisMission)
            .where(DeepAnalysisMission.project_id == project.id)
            .order_by(DeepAnalysisMission.updated_at.desc(), DeepAnalysisMission.id.desc())
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
    return mission


def active_workflow(
    db: Session, mission_id: str
) -> tuple[DeepAnalysisWorkflowRevision, list[DeepAnalysisWorkflowNode], list[DeepAnalysisWorkflowEdge]]:
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
