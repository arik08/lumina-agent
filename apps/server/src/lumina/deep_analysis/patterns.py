from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..models import User, utc_now
from .models import (
    DeepAnalysisMission,
    DeepAnalysisWorkflowEdge,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowPattern,
    DeepAnalysisWorkflowPatternVersion,
    DeepAnalysisWorkflowRevision,
)
from .planning import graph_digest
from .service import active_workflow


_SAFE_CONFIG_KEYS = {
    "role",
    "inputContract",
    "outputContract",
    "validationRules",
    "adaptiveSlot",
    "conditional",
    "budget",
    "nodeProfile",
    "toolHints",
    "semanticInputRoles",
}
_UUID_OR_NUMBER = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b|(?<![A-Za-z])[-+]?\d[\d,.]*(?:%|원|달러|USD|KRW)?",
    re.IGNORECASE,
)


def _sanitize_value(value: Any, mission: DeepAnalysisMission) -> Any:
    if isinstance(value, str):
        clean = value
        for specific in (mission.title.strip(), mission.objective.strip()):
            if specific:
                clean = clean.replace(specific, "{Mission 입력}")
        return _UUID_OR_NUMBER.sub("{값}", clean)
    if isinstance(value, list):
        return [_sanitize_value(item, mission) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_value(item, mission) for key, item in value.items()}
    if isinstance(value, (int, float)):
        return "{값}"
    return value


def _digest(definition: dict[str, Any]) -> str:
    canonical = json.dumps(
        definition, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def definition_from_mission(
    db: Session,
    mission: DeepAnalysisMission,
    *,
    intent: str,
) -> dict[str, Any]:
    _revision, nodes, edges = active_workflow(db, mission.id)
    return {
        "kind": "workflow_pattern",
        "schemaVersion": 1,
        "intent": _sanitize_value(intent, mission),
        "expectedOutputs": _sanitize_value(
            list(mission.charter_json.get("deliverables") or []), mission
        ),
        "requiredQuestions": _sanitize_value(
            list(mission.charter_json.get("keyQuestions") or []), mission
        ),
        "nodes": [
            {
                "nodeKey": node.node_key,
                "nodeType": node.node_type,
                "title": _sanitize_value(node.title, mission),
                "purpose": _sanitize_value(node.purpose, mission),
                "positionX": node.position_x,
                "positionY": node.position_y,
                "estimatedCostMicrousd": node.estimated_cost_microusd,
                "config": {
                    key: _sanitize_value(value, mission)
                    for key, value in node.config_json.items()
                    if key in _SAFE_CONFIG_KEYS
                },
            }
            for node in nodes
        ],
        "edges": [
            {
                "sourceNodeKey": edge.source_node_key,
                "targetNodeKey": edge.target_node_key,
                "edgeType": edge.edge_type,
            }
            for edge in edges
        ],
        "policies": {
            "autonomyCeiling": mission.autonomy_mode,
            "budgetMicrousd": None,
        },
    }


def list_patterns(
    db: Session, project_id: str
) -> list[tuple[DeepAnalysisWorkflowPattern, DeepAnalysisWorkflowPatternVersion | None]]:
    patterns = list(
        db.scalars(
            select(DeepAnalysisWorkflowPattern)
            .where(
                DeepAnalysisWorkflowPattern.project_id == project_id,
                DeepAnalysisWorkflowPattern.status == "active",
            )
            .order_by(DeepAnalysisWorkflowPattern.updated_at.desc())
        )
    )
    result = []
    for pattern in patterns:
        latest = db.scalar(
            select(DeepAnalysisWorkflowPatternVersion)
            .where(
                DeepAnalysisWorkflowPatternVersion.pattern_id == pattern.id,
                DeepAnalysisWorkflowPatternVersion.status == "published",
            )
            .order_by(DeepAnalysisWorkflowPatternVersion.version_number.desc())
        )
        result.append((pattern, latest))
    return result


def create_pattern(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    user: User,
    name: str,
    description: str,
) -> tuple[DeepAnalysisWorkflowPattern, DeepAnalysisWorkflowPatternVersion]:
    clean_name = name.strip()
    if not clean_name:
        raise ApiProblem(422, "pattern_name_required", "Pattern 이름을 입력해 주세요.")
    pattern = DeepAnalysisWorkflowPattern(
        organization_id=mission.organization_id,
        project_id=mission.project_id,
        created_by_user_id=user.id,
        scope="project",
        name=clean_name,
        description=description.strip(),
    )
    db.add(pattern)
    db.flush()
    definition = definition_from_mission(
        db, mission, intent=description.strip() or clean_name
    )
    version = DeepAnalysisWorkflowPatternVersion(
        pattern_id=pattern.id,
        version_number=1,
        status="draft",
        definition_json=definition,
        definition_digest=_digest(definition),
        change_summary="Mission Workflow에서 검토용 Pattern 초안을 생성했습니다.",
        source_mission_id=mission.id,
    )
    db.add(version)
    db.flush()
    return pattern, version


def create_pattern_version(
    db: Session,
    *,
    pattern: DeepAnalysisWorkflowPattern,
    mission: DeepAnalysisMission,
    change_summary: str,
) -> DeepAnalysisWorkflowPatternVersion:
    number = db.scalar(
        select(DeepAnalysisWorkflowPatternVersion.version_number)
        .where(DeepAnalysisWorkflowPatternVersion.pattern_id == pattern.id)
        .order_by(DeepAnalysisWorkflowPatternVersion.version_number.desc())
    ) or 0
    definition = definition_from_mission(
        db, mission, intent=pattern.description or pattern.name
    )
    version = DeepAnalysisWorkflowPatternVersion(
        pattern_id=pattern.id,
        version_number=number + 1,
        status="draft",
        definition_json=definition,
        definition_digest=_digest(definition),
        change_summary=change_summary.strip(),
        source_mission_id=mission.id,
    )
    db.add(version)
    db.flush()
    return version


def publish_pattern_version(
    db: Session,
    *,
    pattern: DeepAnalysisWorkflowPattern,
    version: DeepAnalysisWorkflowPatternVersion,
    user: User,
) -> None:
    if version.pattern_id != pattern.id:
        raise ApiProblem(404, "pattern_version_not_found", "Pattern version을 찾을 수 없습니다.")
    if version.status == "published":
        return
    if version.status != "draft":
        raise ApiProblem(409, "pattern_version_not_publishable", "Draft version만 publish할 수 있습니다.")
    version.status = "published"
    version.published_by_user_id = user.id
    version.published_at = utc_now()
    db.flush()


def apply_pattern_version(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    revision: DeepAnalysisWorkflowRevision,
    version: DeepAnalysisWorkflowPatternVersion,
    pattern: DeepAnalysisWorkflowPattern,
) -> None:
    if version.status != "published" or version.pattern_id != pattern.id:
        raise ApiProblem(409, "pattern_version_not_published", "게시된 Pattern version만 사용할 수 있습니다.")
    if pattern.project_id != mission.project_id or pattern.organization_id != mission.organization_id:
        raise ApiProblem(403, "pattern_access_denied", "이 Project에서 사용할 수 없는 Pattern입니다.")
    definition = version.definition_json
    db.execute(delete(DeepAnalysisWorkflowEdge).where(DeepAnalysisWorkflowEdge.workflow_revision_id == revision.id))
    db.execute(delete(DeepAnalysisWorkflowNode).where(DeepAnalysisWorkflowNode.workflow_revision_id == revision.id))
    for sequence, item in enumerate(definition.get("nodes", []), start=1):
        db.add(
            DeepAnalysisWorkflowNode(
                workflow_revision_id=revision.id,
                node_key=str(item["nodeKey"]),
                node_type=str(item["nodeType"]),
                title=str(item["title"]),
                purpose=str(item.get("purpose") or ""),
                status="planned",
                sequence=sequence,
                position_x=int(item.get("positionX") or 0),
                position_y=int(item.get("positionY") or 0),
                config_json={
                    **dict(item.get("config") or {}),
                    "patternVersionId": version.id,
                },
                estimated_cost_microusd=int(item.get("estimatedCostMicrousd") or 0),
            )
        )
    for item in definition.get("edges", []):
        db.add(
            DeepAnalysisWorkflowEdge(
                workflow_revision_id=revision.id,
                source_node_key=str(item["sourceNodeKey"]),
                target_node_key=str(item["targetNodeKey"]),
                edge_type=str(item.get("edgeType") or "sequence"),
            )
        )
    db.flush()
    nodes = list(db.scalars(select(DeepAnalysisWorkflowNode).where(DeepAnalysisWorkflowNode.workflow_revision_id == revision.id)))
    edges = list(db.scalars(select(DeepAnalysisWorkflowEdge).where(DeepAnalysisWorkflowEdge.workflow_revision_id == revision.id)))
    revision.source = "pattern"
    revision.reason = f"published_pattern_v{version.version_number}_adapted_to_mission"
    revision.graph_digest = graph_digest(nodes, edges)
    revision.change_log_json = [{
        "revision": revision.revision_number,
        "action": "pattern_applied",
        "reason": revision.reason,
        "patternId": pattern.id,
        "patternVersionId": version.id,
        "graphChanged": True,
        "createdAt": utc_now().isoformat(),
    }]
    mission.start_mode = "pattern_based"
    mission.pattern_version_id = version.id
    db.flush()
