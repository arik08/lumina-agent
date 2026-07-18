from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...authorization import require_project
from ...agent.executor import local_run_executor
from ...api.schemas import RunActionRequest
from ...config import Settings, get_settings
from ...db import get_db
from ...deep_analysis.execution import create_node_run
from ...deep_analysis.exports import create_mission_export
from ...deep_analysis.models import (
    DeepAnalysisClaim,
    DeepAnalysisClaimEvidenceLink,
    DeepAnalysisDecision,
    DeepAnalysisDecisionResponse,
    DeepAnalysisEvidenceReference,
    DeepAnalysisMission,
    DeepAnalysisMissionExport,
    DeepAnalysisOpenIssue,
    DeepAnalysisQualityGateResult,
    DeepAnalysisWorkflowRevision,
    DeepAnalysisWorkflowPattern,
    DeepAnalysisWorkflowPatternVersion,
)
from ...deep_analysis.ledger import list_claims, list_evidence, list_open_issues
from ...deep_analysis.patterns import (
    create_pattern,
    create_pattern_version,
    list_patterns,
    publish_pattern_version,
)
from ...deep_analysis.schemas import (
    DecisionAnswer,
    DecisionResponse,
    ClaimResponse,
    EvidenceResponse,
    MissionCancel,
    MissionCreate,
    MissionDetailResponse,
    MissionExportCreate,
    MissionExportResponse,
    MissionPatch,
    MissionQualityGate,
    MissionRetry,
    MissionStart,
    MissionSummaryResponse,
    OpenIssueResponse,
    PatternCreate,
    PatternResponse,
    PatternVersionCreate,
    PatternVersionResponse,
    WorkflowDraftCreate,
    WorkflowDraftPatch,
    WorkflowRevisionResponse,
)
from ...deep_analysis.service import (
    active_workflow,
    activate_workflow_draft,
    answer_decision,
    cancel_mission,
    create_mission,
    create_workflow_draft,
    delete_mission,
    execution_engine_available,
    list_decisions,
    list_missions,
    require_mission,
    retry_mission_node,
    run_quality_gate,
    start_mission,
    update_mission,
    update_workflow_draft,
    upgrade_legacy_draft_workflow,
    workflow_revision,
)
from ...deep_analysis.quality import list_quality_gates
from ...models import Run, User
from ...storage import ManagedLocalStorage, StorageError
from ...runs.broker import event_broker
from ...runs.service import apply_run_action
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem


router = APIRouter(tags=["deep-analysis"])


def _storage(settings: Settings) -> ManagedLocalStorage:
    if settings.files_dir is None:
        raise RuntimeError("LUMINA_FILES_DIR is not configured")
    return ManagedLocalStorage(settings.files_dir)


def _export_payload(item: DeepAnalysisMissionExport) -> dict[str, object]:
    return {
        "id": item.id,
        "mission_id": item.mission_id,
        "scope": item.scope,
        "include_originals": item.include_originals,
        "status": item.status,
        "filename": item.filename,
        "content_hash": item.content_hash,
        "size_bytes": item.size_bytes,
        "manifest": item.manifest_json,
        "error_message": item.error_message,
        "completed_at": item.completed_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _pattern_version_payload(
    version: DeepAnalysisWorkflowPatternVersion,
) -> dict[str, object]:
    return {
        "id": version.id,
        "pattern_id": version.pattern_id,
        "version_number": version.version_number,
        "status": version.status,
        "definition_digest": version.definition_digest,
        "definition": version.definition_json,
        "change_summary": version.change_summary,
        "source_mission_id": version.source_mission_id,
        "published_by_user_id": version.published_by_user_id,
        "published_at": version.published_at,
        "created_at": version.created_at,
    }


def _pattern_payload(
    pattern: DeepAnalysisWorkflowPattern,
    latest: DeepAnalysisWorkflowPatternVersion | None,
) -> dict[str, object]:
    return {
        "id": pattern.id,
        "project_id": pattern.project_id,
        "scope": pattern.scope,
        "name": pattern.name,
        "description": pattern.description,
        "status": pattern.status,
        "latest_published_version": (
            _pattern_version_payload(latest) if latest is not None else None
        ),
        "created_at": pattern.created_at,
        "updated_at": pattern.updated_at,
    }


def _decision_payload(
    decision: DeepAnalysisDecision,
    response: DeepAnalysisDecisionResponse | None,
    requested_by_node_key: str | None,
) -> dict[str, object]:
    return {
        "id": decision.id,
        "mission_id": decision.mission_id,
        "workflow_revision_id": decision.workflow_revision_id,
        "requested_by_node_key": requested_by_node_key,
        "question": decision.question,
        "options": decision.options_json,
        "recommendation_option_id": decision.recommendation_option_id,
        "recommendation_rationale": decision.recommendation_rationale,
        "impact": decision.impact_json,
        "affected_node_keys": decision.affected_node_keys_json,
        "status": decision.status,
        "selected_option_id": (
            response.selected_option_id if response is not None else None
        ),
        "answer_text": response.answer_text if response is not None else "",
        "decided_by_user_id": (
            response.decided_by_user_id if response is not None else None
        ),
        "applied_workflow_revision_number": (
            decision.applied_workflow_revision_number
        ),
        "resolved_at": decision.resolved_at,
        "created_at": decision.created_at,
        "updated_at": decision.updated_at,
    }


def _quality_gate_payload(
    gate: DeepAnalysisQualityGateResult,
    report_node_key: str | None,
) -> dict[str, object]:
    return {
        "id": gate.id,
        "workflow_revision_id": gate.workflow_revision_id,
        "report_node_key": report_node_key,
        "parent_result_id": gate.parent_result_id,
        "waiver_decision_id": gate.waiver_decision_id,
        "result": gate.result,
        "completion_outcome": gate.completion_outcome,
        "checks": gate.checks_json,
        "failure_reasons": gate.failure_reasons_json,
        "evaluated_at": gate.evaluated_at,
        "created_at": gate.created_at,
    }


def _evidence_payload(
    evidence: DeepAnalysisEvidenceReference,
    source_node_key: str | None = None,
) -> dict[str, object]:
    return {
        "id": evidence.id,
        "source_node_key": source_node_key,
        "source_type": evidence.source_type,
        "stable_id": evidence.stable_id,
        "version_id": evidence.version_id,
        "content_digest": evidence.content_digest,
        "locator": evidence.locator,
        "title": evidence.title,
        "metadata": evidence.metadata_json,
        "created_at": evidence.created_at,
    }


def _claim_payload(
    claim: DeepAnalysisClaim,
    source_node_key: str | None,
    evidence_rows: list[
        tuple[DeepAnalysisClaimEvidenceLink, DeepAnalysisEvidenceReference]
    ],
) -> dict[str, object]:
    return {
        "id": claim.id,
        "source_node_key": source_node_key,
        "statement": claim.statement,
        "level": claim.level,
        "status": claim.status,
        "confidence": claim.confidence,
        "materiality": claim.materiality,
        "report_inclusion": claim.report_inclusion,
        "validation": claim.validation_json,
        "stale_status": claim.stale_status,
        "evidence": [
            {
                "evidence": _evidence_payload(evidence),
                "stance": link.stance,
                "rationale": link.rationale,
            }
            for link, evidence in evidence_rows
        ],
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
    }


def _open_issue_payload(
    issue: DeepAnalysisOpenIssue,
    source_node_key: str | None,
) -> dict[str, object]:
    return {
        "id": issue.id,
        "source_node_key": source_node_key,
        "issue_type": issue.issue_type,
        "statement": issue.statement,
        "status": issue.status,
        "materiality": issue.materiality,
        "residual_amount": issue.residual_amount,
        "residual_percent": issue.residual_percent,
        "required_action": issue.required_action,
        "report_inclusion": issue.report_inclusion,
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
    }


def _summary_payload(mission: DeepAnalysisMission) -> dict[str, object]:
    return {
        "id": mission.id,
        "project_id": mission.project_id,
        "title": mission.title,
        "objective": mission.objective,
        "status": mission.status,
        "start_mode": mission.start_mode,
        "pattern_version_id": mission.pattern_version_id,
        "autonomy_mode": mission.autonomy_mode,
        "budget_microusd": mission.budget_microusd,
        "spent_microusd": mission.spent_microusd,
        "completion_outcome": mission.completion_outcome,
        "revision": mission.revision,
        "created_at": mission.created_at,
        "updated_at": mission.updated_at,
    }


def _workflow_revision_payload(
    db: Session, revision: DeepAnalysisWorkflowRevision
) -> dict[str, object]:
    nodes, edges = workflow_revision(db, revision)
    runs = {
        run.id: run
        for run in db.query(Run).filter(Run.id.in_([node.run_id for node in nodes if node.run_id]))
    }
    return {
        "id": revision.id,
        "revision_number": revision.revision_number,
        "state": revision.state,
        "source": revision.source,
        "reason": revision.reason,
        "graph_digest": revision.graph_digest,
        "change_log": revision.change_log_json,
        "nodes": [
            {
                "id": node.id, "node_key": node.node_key, "node_type": node.node_type,
                "title": node.title, "purpose": node.purpose, "status": node.status,
                "sequence": node.sequence, "position_x": node.position_x, "position_y": node.position_y,
                "config": node.config_json, "run_id": node.run_id,
                "output_project_file_id": node.output_project_file_id, "output_logical_path": node.output_logical_path,
                "output_summary": node.output_summary, "output_markdown": node.output_markdown,
                "generated_files": node.generated_files_json, "run_history": node.run_history_json,
                "run_status": runs[node.run_id].status if node.run_id and node.run_id in runs else None,
                "live_output": "", "error_message": node.error_message,
                "estimated_cost_microusd": node.estimated_cost_microusd,
                "actual_cost_microusd": node.actual_cost_microusd,
                "started_at": node.started_at, "finished_at": node.finished_at,
            }
            for node in nodes
        ],
        "edges": [{"id": edge.id, "source_node_key": edge.source_node_key, "target_node_key": edge.target_node_key, "edge_type": edge.edge_type} for edge in edges],
        "created_at": revision.created_at,
        "updated_at": revision.updated_at,
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
        "decisions": [
            _decision_payload(decision, response, node_key)
            for decision, response, node_key in list_decisions(db, mission.id)
        ],
        "quality_gates": [
            _quality_gate_payload(gate, node_key)
            for gate, node_key in list_quality_gates(db, mission.id)
        ],
        "claims": [
            _claim_payload(claim, node_key, evidence_rows)
            for claim, node_key, evidence_rows in list_claims(db, mission.id)
        ],
        "evidence": [
            _evidence_payload(evidence)
            for evidence in list_evidence(db, mission.id)
        ],
        "open_issues": [
            _open_issue_payload(issue, node_key)
            for issue, node_key in list_open_issues(db, mission.id)
        ],
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


@router.get(
    "/projects/{project_id}/deep-analysis/patterns",
    response_model=list[PatternResponse],
)
def get_patterns(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    project = require_project(db, user, project_id)
    return [
        _pattern_payload(pattern, latest)
        for pattern, latest in list_patterns(db, project.id)
    ]


@router.post(
    "/projects/{project_id}/deep-analysis/patterns",
    response_model=PatternVersionResponse,
    status_code=201,
)
def post_pattern(
    project_id: str,
    payload: PatternCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_project(db, context.user, project_id, write=True)
    mission = require_mission(db, context.user, payload.mission_id, write=True)
    if mission.project_id != project_id:
        raise ApiProblem(404, "mission_not_found", "Project에서 Mission을 찾을 수 없습니다.")
    pattern, version = create_pattern(
        db,
        mission=mission,
        user=context.user,
        name=payload.name,
        description=payload.description,
    )
    record_audit(
        db,
        action="deep_analysis_pattern_draft_created",
        target_type="deep_analysis_workflow_pattern",
        target_id=pattern.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"mission_id": mission.id, "version_id": version.id},
    )
    db.commit()
    return _pattern_version_payload(version)


@router.post(
    "/deep-analysis/patterns/{pattern_id}/versions",
    response_model=PatternVersionResponse,
    status_code=201,
)
def post_pattern_version(
    pattern_id: str,
    payload: PatternVersionCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    pattern = db.get(DeepAnalysisWorkflowPattern, pattern_id)
    if pattern is None or pattern.project_id is None:
        raise ApiProblem(404, "pattern_not_found", "Pattern을 찾을 수 없습니다.")
    require_project(db, context.user, pattern.project_id, write=True)
    mission = require_mission(db, context.user, payload.mission_id, write=True)
    if mission.project_id != pattern.project_id:
        raise ApiProblem(403, "pattern_scope_mismatch", "같은 Project의 Mission만 Pattern version 근거로 사용할 수 있습니다.")
    version = create_pattern_version(
        db,
        pattern=pattern,
        mission=mission,
        change_summary=payload.change_summary,
    )
    db.commit()
    return _pattern_version_payload(version)


@router.post(
    "/deep-analysis/patterns/{pattern_id}/versions/{version_id}/publish",
    response_model=PatternVersionResponse,
)
def post_pattern_version_publish(
    pattern_id: str,
    version_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    pattern = db.get(DeepAnalysisWorkflowPattern, pattern_id)
    version = db.get(DeepAnalysisWorkflowPatternVersion, version_id)
    if pattern is None or version is None or pattern.project_id is None:
        raise ApiProblem(404, "pattern_version_not_found", "Pattern version을 찾을 수 없습니다.")
    require_project(db, context.user, pattern.project_id, write=True)
    publish_pattern_version(db, pattern=pattern, version=version, user=context.user)
    record_audit(
        db,
        action="deep_analysis_pattern_version_published",
        target_type="deep_analysis_workflow_pattern_version",
        target_id=version.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"pattern_id": pattern.id, "version": version.version_number},
    )
    db.commit()
    return _pattern_version_payload(version)


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
        pattern_version_id=payload.pattern_version_id,
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


@router.post(
    "/deep-analysis/missions/{mission_id}/revisions",
    response_model=WorkflowRevisionResponse,
    status_code=201,
)
def post_workflow_draft(
    mission_id: str,
    payload: WorkflowDraftCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    draft = create_workflow_draft(db, mission, expected_revision=payload.expected_revision)
    db.commit()
    return _workflow_revision_payload(db, draft)


@router.patch(
    "/deep-analysis/missions/{mission_id}/draft",
    response_model=WorkflowRevisionResponse,
)
def patch_workflow_draft(
    mission_id: str,
    payload: WorkflowDraftPatch,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    draft = update_workflow_draft(
        db,
        mission,
        expected_revision=payload.expected_revision,
        nodes_payload=[item.model_dump(by_alias=True) for item in payload.nodes],
        edges_payload=[item.model_dump(by_alias=True) for item in payload.edges],
    )
    db.commit()
    return _workflow_revision_payload(db, draft)


@router.post(
    "/deep-analysis/missions/{mission_id}/draft/activate",
    response_model=MissionDetailResponse,
)
def post_workflow_draft_activate(
    mission_id: str,
    payload: WorkflowDraftCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    activate_workflow_draft(db, mission, expected_revision=payload.expected_revision)
    db.commit()
    return _detail_payload(db, mission)


@router.get(
    "/deep-analysis/missions/{mission_id}/decisions",
    response_model=list[DecisionResponse],
)
def get_mission_decisions(
    mission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    mission = require_mission(db, user, mission_id)
    return [
        _decision_payload(decision, response, node_key)
        for decision, response, node_key in list_decisions(db, mission.id)
    ]


@router.get(
    "/deep-analysis/missions/{mission_id}/claims",
    response_model=list[ClaimResponse],
)
def get_mission_claims(
    mission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    mission = require_mission(db, user, mission_id)
    return [
        _claim_payload(claim, node_key, evidence_rows)
        for claim, node_key, evidence_rows in list_claims(db, mission.id)
    ]


@router.get(
    "/deep-analysis/missions/{mission_id}/evidence",
    response_model=list[EvidenceResponse],
)
def get_mission_evidence(
    mission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    mission = require_mission(db, user, mission_id)
    return [_evidence_payload(item) for item in list_evidence(db, mission.id)]


@router.get(
    "/deep-analysis/missions/{mission_id}/open-issues",
    response_model=list[OpenIssueResponse],
)
def get_mission_open_issues(
    mission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    mission = require_mission(db, user, mission_id)
    return [
        _open_issue_payload(issue, node_key)
        for issue, node_key in list_open_issues(db, mission.id)
    ]


@router.post(
    "/deep-analysis/missions/{mission_id}/decisions/{decision_id}/answer",
    response_model=MissionDetailResponse,
)
async def post_mission_decision_answer(
    mission_id: str,
    decision_id: str,
    payload: DecisionAnswer,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    decision, _response, next_node, changed = answer_decision(
        db,
        mission=mission,
        user=context.user,
        decision_id=decision_id,
        expected_revision=payload.expected_revision,
        selected_option_id=payload.selected_option_id,
        answer_text=payload.answer_text,
    )
    next_run = None
    created = False
    if changed and next_node is not None:
        next_run, created = create_node_run(
            db,
            user=context.user,
            mission=mission,
            node=next_node,
            settings=settings,
        )
    if changed:
        record_audit(
            db,
            action="deep_analysis_decision_resolved",
            target_type="deep_analysis_decision",
            target_id=decision.id,
            result="success",
            actor=context.user,
            request_id=getattr(request.state, "request_id", None),
            metadata={
                "mission_id": mission.id,
                "selected_option_id": payload.selected_option_id,
                "applied_workflow_revision_number": (
                    decision.applied_workflow_revision_number
                ),
            },
        )
    db.commit()
    if created and next_run is not None:
        local_run_executor.enqueue(next_run.id)
        await event_broker.notify(next_run.id)
    return _detail_payload(db, mission)


@router.post(
    "/deep-analysis/missions/{mission_id}/quality-gate",
    response_model=MissionDetailResponse,
)
def post_mission_quality_gate(
    mission_id: str,
    payload: MissionQualityGate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    run_quality_gate(
        db,
        mission,
        expected_revision=payload.expected_revision,
    )
    record_audit(
        db,
        action="deep_analysis_quality_gate_evaluated",
        target_type="deep_analysis_mission",
        target_id=mission.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"revision": mission.revision},
    )
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
        charter=(
            payload.charter.model_dump(mode="json", by_alias=True)
            if payload.charter is not None
            else None
        ),
        completion_contract=(
            payload.completion_contract.model_dump(mode="json", by_alias=True)
            if payload.completion_contract is not None
            else None
        ),
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


@router.post(
    "/deep-analysis/missions/{mission_id}/exports",
    response_model=MissionExportResponse,
    status_code=201,
)
def post_mission_export(
    mission_id: str,
    payload: MissionExportCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    item = create_mission_export(
        db,
        _storage(settings),
        mission=mission,
        user=context.user,
        scope=payload.scope,
        include_originals=payload.include_originals,
    )
    record_audit(
        db,
        action="deep_analysis_mission_exported",
        target_type="deep_analysis_mission_export",
        target_id=item.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "mission_id": mission.id,
            "scope": item.scope,
            "include_originals": item.include_originals,
            "entry_count": item.manifest_json.get("entryCount"),
        },
    )
    db.commit()
    return _export_payload(item)


@router.get(
    "/deep-analysis/missions/{mission_id}/exports/{export_id}",
    response_model=MissionExportResponse,
)
def get_mission_export(
    mission_id: str,
    export_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, user, mission_id)
    item = db.get(DeepAnalysisMissionExport, export_id)
    if item is None or item.mission_id != mission.id:
        raise ApiProblem(404, "deep_analysis_export_not_found", "Mission 내보내기를 찾을 수 없습니다.")
    return _export_payload(item)


@router.get("/deep-analysis/missions/{mission_id}/exports/{export_id}/download")
def download_mission_export(
    mission_id: str,
    export_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    mission = require_mission(db, user, mission_id)
    item = db.get(DeepAnalysisMissionExport, export_id)
    if item is None or item.mission_id != mission.id:
        raise ApiProblem(404, "deep_analysis_export_not_found", "Mission 내보내기를 찾을 수 없습니다.")
    if item.status != "completed" or not item.storage_key or not item.content_hash:
        raise ApiProblem(409, "deep_analysis_export_not_ready", "Mission 내보내기가 아직 준비되지 않았습니다.")
    try:
        content = _storage(settings).read_bytes(
            item.storage_key, expected_sha256=item.content_hash
        )
    except StorageError as exc:
        raise ApiProblem(503, "deep_analysis_export_content_missing", "Mission 내보내기 파일을 읽을 수 없습니다.") from exc
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=mission-export.zip; filename*=UTF-8''{quote(item.filename)}",
            "X-Content-SHA256": item.content_hash,
        },
    )
