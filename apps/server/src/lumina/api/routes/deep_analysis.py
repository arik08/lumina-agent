from __future__ import annotations

from datetime import timedelta
import logging
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...authorization import require_project
from ...agent.executor import local_run_executor
from ...api.schemas import RunActionRequest, RunCreate, RunMessageInput
from ...config import Settings, get_settings
from ...db import SessionLocal, get_db
from ...auth import resolve_server_session
from ...deep_analysis.execution import (
    create_node_run,
    create_runnable_node_runs,
    preserve_partial_output,
)
from ...deep_analysis.ai_planner import design_initial_workflow
from ...deep_analysis.costs import mission_costs
from ...deep_analysis.events import (
    claim_command,
    complete_command,
    emit_event,
    event_payload,
    list_events,
)
from ...deep_analysis.exports import create_mission_export
from ...deep_analysis.models import (
    DeepAnalysisClaim,
    DeepAnalysisClaimEvidenceLink,
    DeepAnalysisDecision,
    DeepAnalysisDecisionResponse,
    DeepAnalysisEvidenceReference,
    DeepAnalysisMission,
    DeepAnalysisContextManifest,
    DeepAnalysisMissionFileLink,
    DeepAnalysisMissionExport,
    DeepAnalysisOpenIssue,
    DeepAnalysisQualityGateResult,
    DeepAnalysisWorkflowRevision,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowPattern,
    DeepAnalysisWorkflowPatternVersion,
)
from ...deep_analysis.ledger import list_claims, list_evidence, list_open_issues
from ...deep_analysis.patterns import (
    archive_pattern,
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
    MissionEventResponse,
    MissionCostResponse,
    MissionFileResponse,
    MissionPatch,
    MissionMove,
    MissionPause,
    MissionQualityGate,
    MissionRetry,
    MissionRestart,
    MissionStart,
    MissionSummaryResponse,
    OpenIssueResponse,
    PatternCreate,
    PatternResponse,
    PatternVersionCreate,
    PatternVersionResponse,
    WorkflowDraftCreate,
    WorkflowDraftPatch,
    WorkflowRegenerate,
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
    move_mission,
    pause_mission,
    regenerate_workflow,
    require_mission,
    retry_mission_node,
    restart_mission,
    resume_mission,
    run_quality_gate,
    start_mission,
    update_mission,
    update_workflow_draft,
    workflow_revision,
)
from ...deep_analysis.quality import list_quality_gates
from ...deep_analysis.planning import initial_workflow_plan
from ...models import Message, ProjectFile, ProjectFileVersion, Run, User, utc_now
from ...runs.service import resolve_execution, validate_project_references
from ...providers.execution_defaults import initial_execution_selection
from ...storage import ManagedLocalStorage
from ...runs.broker import event_broker
from ...runs.service import apply_run_action
from ..dependencies import (
    AuthContext,
    get_current_user,
    get_stream_auth_context,
    require_csrf,
)
from ..errors import ApiProblem


router = APIRouter(tags=["deep-analysis"])
stream_router = APIRouter(tags=["deep-analysis-stream"])
logger = logging.getLogger(__name__)


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
        "applied_workflow_revision_number": (decision.applied_workflow_revision_number),
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
    execution_settings = mission.execution_settings_json or {}
    prompt_references = [
        {
            "kind": reference.get("kind"),
            "referenceId": reference.get("reference_id"),
            "versionOrDigest": reference.get("version_or_digest"),
            "displaySnapshot": reference.get("display_snapshot", {}),
            "tokenStart": reference.get("token_start"),
            "tokenEnd": reference.get("token_end"),
        }
        for reference in execution_settings.get("promptReferences", [])
        if isinstance(reference, dict)
    ]
    return {
        "id": mission.id,
        "project_id": mission.project_id,
        "title": mission.title,
        "is_favorite": mission.is_favorite,
        "is_liked": mission.is_liked,
        "objective": mission.objective,
        "status": mission.status,
        "start_mode": mission.start_mode,
        "pattern_version_id": mission.pattern_version_id,
        "autonomy_mode": mission.autonomy_mode,
        "analysis_depth": execution_settings.get("analysisDepth", "auto"),
        "answer_length": execution_settings.get("answerLength", "auto"),
        "output_mode": execution_settings.get("outputMode", "auto"),
        "output_format": execution_settings.get("outputFormat", "markdown"),
        "target_output_tokens": execution_settings.get("targetOutputTokens", 10_000),
        "execution": execution_settings.get("execution"),
        "prompt_references": prompt_references,
        "budget_microusd": mission.budget_microusd,
        "spent_microusd": mission.spent_microusd,
        "completion_outcome": mission.completion_outcome,
        "revision": mission.revision,
        "created_at": mission.created_at,
        "updated_at": mission.updated_at,
    }


def _source_manifest(
    db: Session,
    *,
    project_id: str,
    references: list[dict[str, object]],
) -> list[dict[str, object]]:
    selected_file_versions: dict[str, str] = {}
    for reference in references:
        snapshot = reference.get("display_snapshot")
        if not isinstance(snapshot, dict):
            continue
        if snapshot.get("targetType") == "project_file":
            selected_file_versions[str(reference["reference_id"])] = str(
                snapshot.get("contentHash") or reference.get("version_or_digest") or ""
            )
        if snapshot.get("targetType") == "project_folder":
            for item in snapshot.get("fileVersions", []):
                if isinstance(item, dict) and item.get("id") and item.get("digest"):
                    selected_file_versions[str(item["id"])] = str(item["digest"])
    if not selected_file_versions:
        return []
    rows = db.execute(
        select(ProjectFile, ProjectFileVersion)
        .join(ProjectFileVersion, ProjectFileVersion.project_file_id == ProjectFile.id)
        .where(
            ProjectFile.project_id == project_id,
            ProjectFile.id.in_(selected_file_versions),
        )
    ).tuples()
    return [
        {
            "projectFileId": project_file.id,
            "logicalPath": project_file.logical_path,
            "version": version.version_number,
            "versionId": version.id,
            "contentHash": version.content_hash,
            "mimeType": version.mime_type,
            "sizeBytes": version.size_bytes,
        }
        for project_file, version in rows
        if selected_file_versions.get(project_file.id) == version.content_hash
    ]


def _workflow_revision_payload(
    db: Session, revision: DeepAnalysisWorkflowRevision
) -> dict[str, object]:
    nodes, edges = workflow_revision(db, revision)
    run_ids = [node.run_id for node in nodes if node.run_id]
    runs = {run.id: run for run in db.query(Run).filter(Run.id.in_(run_ids))}
    execution_prompts = (
        {
            run_id: prompt
            for run_id, prompt in db.execute(
                select(Message.run_id, Message.canonical_text).where(
                    Message.run_id.in_(run_ids), Message.role == "user"
                )
            ).all()
            if run_id is not None
        }
        if run_ids
        else {}
    )
    manifests = (
        {
            item.run_id: item
            for item in db.query(DeepAnalysisContextManifest).filter(
                DeepAnalysisContextManifest.run_id.in_(runs)
            )
        }
        if runs
        else {}
    )
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
                "conversation_id": node.conversation_id,
                "run_id": node.run_id,
                "output_project_file_id": node.output_project_file_id,
                "output_logical_path": node.output_logical_path,
                "output_summary": node.output_summary,
                "output_markdown": node.output_markdown,
                "generated_files": node.generated_files_json,
                "run_history": node.run_history_json,
                "run_status": runs[node.run_id].status
                if node.run_id and node.run_id in runs
                else None,
                "execution_prompt": execution_prompts.get(node.run_id),
                "context_manifest": (
                    _context_manifest_payload(manifests[node.run_id])
                    if node.run_id and node.run_id in manifests
                    else None
                ),
                "live_output": "",
                "error_message": node.error_message,
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
    }


def _detail_payload(db: Session, mission: DeepAnalysisMission) -> dict[str, object]:
    revision, nodes, edges = active_workflow(db, mission.id)
    run_ids = [node.run_id for node in nodes if node.run_id]
    runs = {run.id: run for run in db.query(Run).filter(Run.id.in_(run_ids))}
    execution_prompts = (
        {
            run_id: prompt
            for run_id, prompt in db.execute(
                select(Message.run_id, Message.canonical_text).where(
                    Message.run_id.in_(run_ids), Message.role == "user"
                )
            ).all()
            if run_id is not None
        }
        if run_ids
        else {}
    )
    manifests = (
        {
            item.run_id: item
            for item in db.query(DeepAnalysisContextManifest).filter(
                DeepAnalysisContextManifest.run_id.in_(runs)
            )
        }
        if runs
        else {}
    )
    return {
        **_summary_payload(mission),
        "execution_available": execution_engine_available(),
        "event_cursor": mission.event_sequence,
        "source_manifest": mission.source_manifest_json,
        "files": _mission_file_payloads(db, mission.id),
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
                    "conversation_id": node.conversation_id,
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
                    "execution_prompt": execution_prompts.get(node.run_id),
                    "context_manifest": (
                        _context_manifest_payload(manifests[node.run_id])
                        if node.run_id and node.run_id in manifests
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


def _context_manifest_payload(item: DeepAnalysisContextManifest) -> dict[str, object]:
    return {
        "id": item.id,
        "missionContextRevision": item.mission_context_revision,
        "prefixHash": item.prefix_hash,
        "toolProfile": item.tool_profile,
        "itemCount": item.item_count,
        "tokenEstimate": item.token_estimate,
        "items": item.items_json,
        "lineage": item.lineage_json,
        "createdAt": item.created_at,
    }


def _mission_file_payloads(db: Session, mission_id: str) -> list[dict[str, object]]:
    rows = db.execute(
        select(
            DeepAnalysisMissionFileLink,
            ProjectFile,
            ProjectFileVersion,
            DeepAnalysisWorkflowNode.node_key,
        )
        .join(
            ProjectFile, ProjectFile.id == DeepAnalysisMissionFileLink.project_file_id
        )
        .join(
            ProjectFileVersion,
            ProjectFileVersion.id
            == DeepAnalysisMissionFileLink.project_file_version_id,
        )
        .outerjoin(
            DeepAnalysisWorkflowNode,
            DeepAnalysisWorkflowNode.id
            == DeepAnalysisMissionFileLink.producing_node_id,
        )
        .where(DeepAnalysisMissionFileLink.mission_id == mission_id)
        .order_by(
            DeepAnalysisMissionFileLink.created_at, DeepAnalysisMissionFileLink.id
        )
    ).all()
    return [
        {
            "id": link.id,
            "projectFileId": project_file.id,
            "projectFileVersionId": version.id,
            "logicalPath": project_file.logical_path,
            "version": version.version_number,
            "contentHash": version.content_hash,
            "producingNodeKey": node_key,
            "producingRunId": link.producing_run_id,
            "purpose": link.purpose,
            "validationStatus": link.validation_status,
            "staleStatus": link.stale_status,
            "metadata": link.metadata_json,
            "createdAt": link.created_at,
        }
        for link, project_file, version, node_key in rows
    ]


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


@router.delete("/deep-analysis/patterns/{pattern_id}", status_code=204)
def remove_pattern(
    pattern_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    pattern = db.get(DeepAnalysisWorkflowPattern, pattern_id)
    if pattern is None or pattern.project_id is None or pattern.status != "active":
        raise ApiProblem(404, "pattern_not_found", "Pattern을 찾을 수 없습니다.")
    require_project(db, context.user, pattern.project_id, write=True)
    archive_pattern(db, pattern=pattern)
    record_audit(
        db,
        action="deep_analysis_pattern_archived",
        target_type="deep_analysis_workflow_pattern",
        target_id=pattern.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"project_id": pattern.project_id},
    )
    db.commit()
    return Response(status_code=204)


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
        raise ApiProblem(
            404, "mission_not_found", "Project에서 Mission을 찾을 수 없습니다."
        )
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
        raise ApiProblem(
            403,
            "pattern_scope_mismatch",
            "같은 Project의 Mission만 Pattern version 근거로 사용할 수 있습니다.",
        )
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
        raise ApiProblem(
            404, "pattern_version_not_found", "Pattern version을 찾을 수 없습니다."
        )
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
async def post_mission(
    project_id: str,
    payload: MissionCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    project = require_project(db, context.user, project_id, write=True)
    validated_references = validate_project_references(
        db,
        context.user,
        project.id,
        payload.prompt_references,
        message_text=payload.objective,
    )
    source_manifest = _source_manifest(
        db,
        project_id=project.id,
        references=validated_references,
    )
    execution, _source = initial_execution_selection(
        db,
        organization_id=project.organization_id,
        environment=settings.environment,
    )
    if payload.execution is not None:
        resolved_execution = resolve_execution(
            db,
            RunCreate(
                message=RunMessageInput(text=payload.objective or payload.title),
                execution=payload.execution,
            ),
            user=context.user,
            project=project,
            settings=settings,
        )
        execution = {
            "providerId": resolved_execution["provider_id"],
            "modelKey": resolved_execution["model_key"],
            "effortId": resolved_execution["effort"],
        }
    initial_plan = None
    start_mode = "ai_fallback"
    planning_metadata: dict[str, object] = {"mode": "fallback"}
    try:
        provider_id = str(execution["providerId"])
        model_key = str(execution["modelKey"])
        design = await design_initial_workflow(
            provider=local_run_executor.provider_for_probe(provider_id),
            model=model_key,
            title=payload.title,
            objective=payload.objective,
            effort=execution.get("effortId"),
        )
        initial_plan = design.plan
        start_mode = "ai_designed"
        planning_metadata = {
            "mode": "ai",
            "providerId": provider_id,
            "modelKey": model_key,
            "effortId": execution.get("effortId"),
        }
    except Exception as exc:
        logger.warning(
            "Deep Analysis initial workflow planning failed; using deterministic fallback: %s",
            type(exc).__name__,
        )
    mission = create_mission(
        db,
        context.user,
        project_id=project_id,
        title=payload.title,
        objective=payload.objective,
        autonomy_mode=payload.autonomy_mode,
        budget_microusd=payload.budget_microusd,
        execution_settings={
            "analysisDepth": payload.analysis_depth,
            "answerLength": payload.answer_length,
            "outputMode": payload.output_mode,
            "outputFormat": payload.output_format,
            "targetOutputTokens": payload.target_output_tokens
            if payload.output_mode != "chat"
            else None,
            "execution": execution,
            "promptReferences": validated_references,
        },
        source_manifest=source_manifest,
        initial_plan=initial_plan,
        start_mode=start_mode,
        planning_metadata=planning_metadata,
    )
    emit_event(
        db,
        mission,
        "mission_created",
        {
            "status": mission.status,
            "missionRevision": mission.revision,
            "workflowRevision": 1,
            "startMode": mission.start_mode,
        },
        actor_user_id=context.user.id,
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
    return _detail_payload(db, mission)


@router.get("/deep-analysis/missions/{mission_id}/projection")
def get_mission_projection(
    mission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, user, mission_id)
    _revision, nodes, _edges = active_workflow(db, mission.id)
    run_ids = [node.run_id for node in nodes if node.run_id]
    runs = (
        {run.id: run for run in db.scalars(select(Run).where(Run.id.in_(run_ids)))}
        if run_ids
        else {}
    )
    return {
        "missionId": mission.id,
        "eventCursor": mission.event_sequence,
        "status": mission.status,
        "spentMicrousd": mission.spent_microusd,
        "revision": mission.revision,
        "nodes": [
            {
                "id": node.id,
                "status": node.status,
                "runId": node.run_id,
                "runStatus": (
                    runs[node.run_id].status
                    if node.run_id and node.run_id in runs
                    else None
                ),
                "liveOutput": (
                    runs[node.run_id].assistant_draft[-6_000:]
                    if node.run_id and node.run_id in runs and node.status == "running"
                    else ""
                ),
                "errorMessage": node.error_message,
                "actualCostMicrousd": node.actual_cost_microusd,
                "startedAt": node.started_at,
                "finishedAt": node.finished_at,
            }
            for node in nodes
        ],
    }


@router.post(
    "/deep-analysis/missions/{mission_id}/workflow/regenerate",
    response_model=MissionDetailResponse,
)
async def post_workflow_regenerate(
    mission_id: str,
    payload: WorkflowRegenerate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    if mission.revision != payload.expected_revision:
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 변경사항이 먼저 저장되었습니다. 최신 상태를 불러온 뒤 다시 시도해 주세요.",
            details={"currentRevision": mission.revision},
        )
    if mission.status in {"running", "paused", "awaiting_input"}:
        raise ApiProblem(
            409,
            "workflow_regeneration_not_allowed",
            "실행 중인 Mission의 Workflow는 재생성할 수 없습니다.",
            details={"status": mission.status},
        )
    execution, _source = initial_execution_selection(
        db,
        organization_id=mission.organization_id,
        environment=settings.environment,
    )
    frozen_execution = (mission.execution_settings_json or {}).get("execution")
    if isinstance(frozen_execution, dict):
        execution = frozen_execution
    planning_metadata: dict[str, object] = {"mode": "fallback"}
    try:
        provider_id = str(execution["providerId"])
        model_key = str(execution["modelKey"])
        design = await design_initial_workflow(
            provider=local_run_executor.provider_for_probe(provider_id),
            model=model_key,
            title=mission.title,
            objective=mission.objective,
            effort=execution.get("effortId"),
            instruction=payload.prompt,
        )
        plan = design.plan
        planning_metadata = {
            "mode": "ai",
            "providerId": provider_id,
            "modelKey": model_key,
            "effortId": execution.get("effortId"),
        }
    except Exception as exc:
        logger.warning(
            "Deep Analysis workflow regeneration failed; using deterministic fallback: %s",
            type(exc).__name__,
        )
        plan = initial_workflow_plan(
            mission.title,
            f"{mission.objective}\n\nWorkflow 재설계 요청: {payload.prompt.strip()}",
        )
    revision = regenerate_workflow(
        db,
        mission,
        expected_revision=payload.expected_revision,
        prompt=payload.prompt,
        plan=plan,
        planning_metadata=planning_metadata,
    )
    emit_event(
        db,
        mission,
        "workflow_regenerated",
        {
            "missionRevision": mission.revision,
            "workflowRevision": revision.revision_number,
            "workflowRevisionId": revision.id,
            "nodeCount": len(plan.nodes),
        },
        actor_user_id=context.user.id,
    )
    record_audit(
        db,
        action="deep_analysis_workflow_regenerated",
        target_type="deep_analysis_mission",
        target_id=mission.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"workflow_revision": revision.revision_number},
    )
    db.commit()
    return _detail_payload(db, mission)


@router.get(
    "/deep-analysis/missions/{mission_id}/events",
    response_model=list[MissionEventResponse],
)
def get_mission_events(
    mission_id: str,
    after_sequence: int = Query(default=0, alias="afterSequence", ge=0),
    limit: int = Query(default=1000, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    mission = require_mission(db, user, mission_id)
    return [
        event_payload(item)
        for item in list_events(
            db, mission.id, after_sequence=after_sequence, limit=limit
        )
    ]


@stream_router.get(
    "/stream/deep-analysis/missions/{mission_id}", include_in_schema=False
)
async def stream_mission_events(
    mission_id: str,
    request: Request,
    after_sequence: int = 0,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    context: AuthContext = Depends(get_stream_auth_context),
    db: Session = Depends(get_db, scope="function"),
) -> StreamingResponse:
    require_mission(db, context.user, mission_id)
    cursor = max(0, after_sequence)
    if last_event_id:
        try:
            cursor = max(cursor, int(last_event_id))
        except ValueError as exc:
            raise ApiProblem(
                400,
                "invalid_event_cursor",
                "Mission event cursor가 올바르지 않습니다.",
            ) from exc

    async def events() -> AsyncIterator[str]:
        nonlocal cursor
        while True:
            if await request.is_disconnected():
                return
            with SessionLocal() as event_db:
                resolved = resolve_server_session(event_db, context.session_token)
                if resolved is None:
                    return
                try:
                    mission = require_mission(event_db, resolved.user, mission_id)
                except ApiProblem:
                    return
                rows = list_events(
                    event_db,
                    mission.id,
                    after_sequence=cursor,
                    limit=200,
                )
                encoded = [
                    jsonable_encoder(
                        MissionEventResponse.model_validate(event_payload(item)),
                        by_alias=True,
                    )
                    for item in rows
                ]
            if encoded:
                for event in encoded:
                    cursor = int(event["sequence"])
                    data = json.dumps(
                        event,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield (f"id: {cursor}\nevent: mission_event\ndata: {data}\n\n")
                continue
            yield ": keep-alive\n\n"
            await event_broker.wait(f"mission:{mission_id}", timeout=1.0)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/deep-analysis/missions/{mission_id}/costs",
    response_model=MissionCostResponse,
)
def get_mission_costs(
    mission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, user, mission_id)
    return mission_costs(db, mission)


@router.get(
    "/deep-analysis/missions/{mission_id}/files",
    response_model=list[MissionFileResponse],
)
def get_mission_files(
    mission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    mission = require_mission(db, user, mission_id)
    return _mission_file_payloads(db, mission.id)


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
    draft = create_workflow_draft(
        db, mission, expected_revision=payload.expected_revision
    )
    emit_event(
        db,
        mission,
        "workflow_draft_created",
        {
            "missionRevision": mission.revision,
            "workflowRevision": draft.revision_number,
            "workflowRevisionId": draft.id,
        },
        actor_user_id=context.user.id,
    )
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
    emit_event(
        db,
        mission,
        "workflow_draft_updated",
        {
            "missionRevision": mission.revision,
            "workflowRevision": draft.revision_number,
            "nodeCount": len(payload.nodes),
            "edgeCount": len(payload.edges),
        },
        actor_user_id=context.user.id,
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
    active_revision, active_nodes, active_edges = active_workflow(db, mission.id)
    emit_event(
        db,
        mission,
        "workflow_revision_activated",
        {
            "missionRevision": mission.revision,
            "workflowRevision": active_revision.revision_number,
            "workflowRevisionId": active_revision.id,
            "nodeCount": len(active_nodes),
            "edgeCount": len(active_edges),
        },
        actor_user_id=context.user.id,
    )
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
    command, should_apply = claim_command(
        db,
        mission=mission,
        user=context.user,
        command_type="decision_answer",
        idempotency_key=request.headers.get("Idempotency-Key"),
        payload=payload,
    )
    if not should_apply:
        return _detail_payload(db, mission)
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
        emit_event(
            db,
            mission,
            "decision_resolved",
            {
                "decisionId": decision.id,
                "selectedOptionId": payload.selected_option_id,
                "missionRevision": mission.revision,
                "workflowRevision": decision.applied_workflow_revision_number,
                "nextNodeKey": next_node.node_key if next_node is not None else None,
            },
            actor_user_id=context.user.id,
        )
        if mission.status == "completed":
            latest_gate_rows = list_quality_gates(db, mission.id)
            latest_gate = latest_gate_rows[-1][0] if latest_gate_rows else None
            if latest_gate is not None:
                emit_event(
                    db,
                    mission,
                    "quality_gate_completed",
                    {
                        "qualityGateId": latest_gate.id,
                        "result": latest_gate.result,
                        "completionOutcome": latest_gate.completion_outcome,
                    },
                    actor_user_id=context.user.id,
                )
            emit_event(
                db,
                mission,
                "mission_completed",
                {
                    "status": mission.status,
                    "completionOutcome": mission.completion_outcome,
                    "missionRevision": mission.revision,
                },
                actor_user_id=context.user.id,
            )
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
    complete_command(db, command, result={"decisionId": decision.id})
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
    command, should_apply = claim_command(
        db,
        mission=mission,
        user=context.user,
        command_type="quality_gate",
        idempotency_key=request.headers.get("Idempotency-Key"),
        payload=payload,
    )
    if not should_apply:
        return _detail_payload(db, mission)
    run_quality_gate(
        db,
        mission,
        expected_revision=payload.expected_revision,
    )
    latest_gate = list_quality_gates(db, mission.id)[-1][0]
    emit_event(
        db,
        mission,
        "quality_gate_completed",
        {
            "qualityGateId": latest_gate.id,
            "result": latest_gate.result,
            "completionOutcome": latest_gate.completion_outcome,
            "missionRevision": mission.revision,
        },
        actor_user_id=context.user.id,
    )
    if mission.status == "awaiting_input":
        pending = next(
            (
                item
                for item, _response, _node_key in list_decisions(db, mission.id)
                if item.status == "pending"
            ),
            None,
        )
        if pending is not None:
            emit_event(
                db,
                mission,
                "decision_requested",
                {
                    "decisionId": pending.id,
                    "requestedByNodeId": pending.requested_by_node_id,
                    "affectedNodeKeys": pending.affected_node_keys_json,
                },
                actor_user_id=context.user.id,
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
    complete_command(db, command, result={"qualityGateId": latest_gate.id})
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
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    project = require_project(db, context.user, mission.project_id, write=True)
    changed_fields = payload.model_fields_set - {"expected_revision"}
    execution_settings = dict(mission.execution_settings_json or {})
    field_mapping = {
        "analysis_depth": "analysisDepth",
        "answer_length": "answerLength",
        "output_mode": "outputMode",
        "output_format": "outputFormat",
        "target_output_tokens": "targetOutputTokens",
    }
    for field_name, stored_name in field_mapping.items():
        if field_name in changed_fields:
            execution_settings[stored_name] = getattr(payload, field_name)
    if "execution" in changed_fields and payload.execution is not None:
        resolved_execution = resolve_execution(
            db,
            RunCreate(
                message=RunMessageInput(
                    text=payload.objective or mission.objective or mission.title
                ),
                execution=payload.execution,
            ),
            user=context.user,
            project=project,
            settings=settings,
        )
        execution_settings["execution"] = {
            "providerId": resolved_execution["provider_id"],
            "modelKey": resolved_execution["model_key"],
            "effortId": resolved_execution["effort"],
        }
    source_manifest = None
    if "prompt_references" in changed_fields:
        validated_references = validate_project_references(
            db,
            context.user,
            project.id,
            payload.prompt_references or [],
            message_text=payload.objective
            if payload.objective is not None
            else mission.objective,
        )
        execution_settings["promptReferences"] = validated_references
        source_manifest = _source_manifest(
            db,
            project_id=project.id,
            references=validated_references,
        )
    update_mission(
        db,
        mission,
        expected_revision=payload.expected_revision,
        title=payload.title,
        objective=payload.objective,
        autonomy_mode=payload.autonomy_mode,
        budget_microusd=payload.budget_microusd,
        is_favorite=payload.is_favorite,
        is_liked=payload.is_liked,
        execution_settings=execution_settings
        if changed_fields & (set(field_mapping) | {"execution", "prompt_references"})
        else None,
        source_manifest=source_manifest,
    )
    emit_event(
        db,
        mission,
        "mission_updated",
        {
            "missionRevision": mission.revision,
            "status": mission.status,
            "changedFields": [
                {
                    "autonomy_mode": "autonomyMode",
                    "budget_microusd": "budgetMicrousd",
                    "analysis_depth": "analysisDepth",
                    "answer_length": "answerLength",
                    "output_mode": "outputMode",
                    "output_format": "outputFormat",
                    "target_output_tokens": "targetOutputTokens",
                    "prompt_references": "promptReferences",
                    "is_favorite": "isFavorite",
                    "is_liked": "isLiked",
                }.get(field_name, field_name)
                for field_name in changed_fields
            ],
        },
        actor_user_id=context.user.id,
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


@router.post(
    "/deep-analysis/missions/{mission_id}/move",
    response_model=MissionSummaryResponse,
)
def post_mission_move(
    mission_id: str,
    payload: MissionMove,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    move_mission(db, context.user, mission, payload.project_id)
    record_audit(
        db,
        action="deep_analysis_mission_moved",
        target_type="deep_analysis_mission",
        target_id=mission.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"project_id": payload.project_id},
    )
    db.commit()
    return _summary_payload(mission)


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
    command, should_apply = claim_command(
        db,
        mission=mission,
        user=context.user,
        command_type="start",
        idempotency_key=request.headers.get("Idempotency-Key"),
        payload=payload,
    )
    if not should_apply:
        return _detail_payload(db, mission)
    start_mission(db, mission, expected_revision=payload.expected_revision)
    _workflow_revision, nodes, edges = active_workflow(db, mission.id)
    runs = create_runnable_node_runs(
        db,
        user=context.user,
        mission=mission,
        nodes=nodes,
        edges=edges,
        settings=settings,
    )
    if not runs:
        raise RuntimeError("Deep-analysis Workflow has no runnable Node")
    run = runs[0]
    active_node = next(node for node in nodes if node.run_id == run.id)
    emit_event(
        db,
        mission,
        "mission_status_changed",
        {
            "status": mission.status,
            "missionRevision": mission.revision,
            "nodeKey": active_node.node_key,
            "runId": run.id,
            "runIds": [item.id for item in runs],
        },
        actor_user_id=context.user.id,
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
    complete_command(
        db,
        command,
        result={"runId": run.id, "runIds": [item.id for item in runs]},
    )
    db.commit()
    for queued_run in runs:
        local_run_executor.enqueue(queued_run.id)
        await event_broker.notify(queued_run.id)
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
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    command, should_apply = claim_command(
        db,
        mission=mission,
        user=context.user,
        command_type="cancel",
        idempotency_key=request.headers.get("Idempotency-Key"),
        payload=payload,
    )
    if not should_apply:
        return _detail_payload(db, mission)
    _workflow_revision, nodes, _edges = active_workflow(db, mission.id)
    active_node = next(
        (node for node in nodes if node.status == "running" and node.run_id),
        None,
    )
    active_run_id = active_node.run_id if active_node is not None else None
    active_run = db.get(Run, active_run_id) if active_run_id is not None else None
    if active_node is not None and active_run is not None:
        preserve_partial_output(
            db,
            user=context.user,
            mission=mission,
            node=active_node,
            run=active_run,
            storage=_storage(settings),
            settings=settings,
        )
    cancel_mission(db, mission, expected_revision=payload.expected_revision)
    emit_event(
        db,
        mission,
        "mission_status_changed",
        {
            "status": mission.status,
            "missionRevision": mission.revision,
            "runId": active_run_id,
        },
        actor_user_id=context.user.id,
    )
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
    complete_command(db, command, result={"runId": active_run_id})
    db.commit()
    if cancelled_run is not None:
        local_run_executor.cancel(cancelled_run.id)
        await event_broker.notify(cancelled_run.id)
    return _detail_payload(db, mission)


@router.post(
    "/deep-analysis/missions/{mission_id}/pause",
    response_model=MissionDetailResponse,
)
async def post_mission_pause(
    mission_id: str,
    payload: MissionPause,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    command, should_apply = claim_command(
        db,
        mission=mission,
        user=context.user,
        command_type="pause",
        idempotency_key=request.headers.get("Idempotency-Key"),
        payload=payload,
    )
    if not should_apply:
        return _detail_payload(db, mission)
    _revision, nodes, _edges = active_workflow(db, mission.id)
    active_run_id = next(
        (node.run_id for node in nodes if node.status == "running" and node.run_id),
        None,
    )
    if active_run_id is None:
        raise ApiProblem(
            409, "mission_run_missing", "일시 정지할 활성 Run을 찾을 수 없습니다."
        )
    run, _command, _message, _changed = apply_run_action(
        db,
        user=context.user,
        run_id=active_run_id,
        payload=RunActionRequest(type="pause"),
        idempotency_key=(
            request.headers.get("Idempotency-Key")
            or f"deep-analysis-pause:{mission.id}:{payload.expected_revision}"
        ),
    )
    pause_mission(db, mission, expected_revision=payload.expected_revision)
    emit_event(
        db,
        mission,
        "mission_status_changed",
        {
            "status": "paused",
            "missionRevision": mission.revision,
            "runId": run.id,
        },
        actor_user_id=context.user.id,
    )
    complete_command(db, command, result={"runId": run.id})
    db.commit()
    await event_broker.notify(run.id)
    return _detail_payload(db, mission)


@router.post(
    "/deep-analysis/missions/{mission_id}/resume",
    response_model=MissionDetailResponse,
)
async def post_mission_resume(
    mission_id: str,
    payload: MissionPause,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    command, should_apply = claim_command(
        db,
        mission=mission,
        user=context.user,
        command_type="resume",
        idempotency_key=request.headers.get("Idempotency-Key"),
        payload=payload,
    )
    if not should_apply:
        return _detail_payload(db, mission)
    _revision, nodes, _edges = active_workflow(db, mission.id)
    active_run_id = next(
        (node.run_id for node in nodes if node.status == "running" and node.run_id),
        None,
    )
    if active_run_id is None:
        raise ApiProblem(
            409, "mission_run_missing", "재개할 활성 Run을 찾을 수 없습니다."
        )
    run, _command, _message, _changed = apply_run_action(
        db,
        user=context.user,
        run_id=active_run_id,
        payload=RunActionRequest(type="resume"),
        idempotency_key=(
            request.headers.get("Idempotency-Key")
            or f"deep-analysis-resume:{mission.id}:{payload.expected_revision}"
        ),
    )
    resume_mission(db, mission, expected_revision=payload.expected_revision)
    emit_event(
        db,
        mission,
        "mission_status_changed",
        {
            "status": "running",
            "missionRevision": mission.revision,
            "runId": run.id,
        },
        actor_user_id=context.user.id,
    )
    complete_command(db, command, result={"runId": run.id})
    db.commit()
    local_run_executor.enqueue(run.id)
    await event_broker.notify(run.id)
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
    command, should_apply = claim_command(
        db,
        mission=mission,
        user=context.user,
        command_type="retry",
        idempotency_key=request.headers.get("Idempotency-Key"),
        payload=payload,
    )
    if not should_apply:
        return _detail_payload(db, mission)
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
    emit_event(
        db,
        mission,
        "node_retried",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "runId": run.id,
            "missionRevision": mission.revision,
        },
        actor_user_id=context.user.id,
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
    complete_command(db, command, result={"runId": run.id, "nodeKey": node.node_key})
    db.commit()
    if created:
        local_run_executor.enqueue(run.id)
        await event_broker.notify(run.id)
    return _detail_payload(db, mission)


@router.post(
    "/deep-analysis/missions/{mission_id}/restart",
    response_model=MissionDetailResponse,
)
async def post_mission_restart(
    mission_id: str,
    payload: MissionRestart,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    mission = require_mission(db, context.user, mission_id, write=True)
    command, should_apply = claim_command(
        db,
        mission=mission,
        user=context.user,
        command_type="restart",
        idempotency_key=request.headers.get("Idempotency-Key"),
        payload=payload,
    )
    if not should_apply:
        return _detail_payload(db, mission)
    node = restart_mission(
        db,
        mission,
        expected_revision=payload.expected_revision,
    )
    run, created = create_node_run(
        db,
        user=context.user,
        mission=mission,
        node=node,
        settings=settings,
    )
    emit_event(
        db,
        mission,
        "mission_restarted",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "runId": run.id,
            "missionRevision": mission.revision,
        },
        actor_user_id=context.user.id,
    )
    record_audit(
        db,
        action="deep_analysis_mission_restarted",
        target_type="deep_analysis_mission",
        target_id=mission.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"node_key": node.node_key, "run_id": run.id},
    )
    complete_command(db, command, result={"runId": run.id, "nodeKey": node.node_key})
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
    command, should_apply = claim_command(
        db,
        mission=mission,
        user=context.user,
        command_type="export",
        idempotency_key=request.headers.get("Idempotency-Key"),
        payload=payload,
    )
    if not should_apply and command is not None:
        existing_id = command.result_json.get("exportId")
        existing = (
            db.get(DeepAnalysisMissionExport, existing_id) if existing_id else None
        )
        if existing is not None and existing.mission_id == mission.id:
            return _export_payload(existing)
        raise ApiProblem(
            409, "idempotent_result_missing", "기존 내보내기 결과를 복원할 수 없습니다."
        )
    requested_at = utc_now()
    cooldown_boundary = requested_at - timedelta(seconds=1)
    claimed = db.execute(
        update(DeepAnalysisMission)
        .where(
            DeepAnalysisMission.id == mission.id,
            or_(
                DeepAnalysisMission.last_export_requested_at.is_(None),
                DeepAnalysisMission.last_export_requested_at <= cooldown_boundary,
            ),
        )
        .values(last_export_requested_at=requested_at)
    )
    if claimed.rowcount != 1:
        raise ApiProblem(
            429,
            "mission_export_cooldown",
            "Mission은 1초에 한 번만 저장할 수 있습니다.",
        )
    item = create_mission_export(
        db,
        _storage(settings),
        mission=mission,
        user=context.user,
        max_upload_bytes=settings.max_upload_bytes,
        requested_at=requested_at,
    )
    emit_event(
        db,
        mission,
        "mission_file_created",
        {
            "exportId": item.id,
            "scope": item.scope,
            "status": item.status,
            "folderPath": item.manifest_json.get("folderPath"),
            "fileCount": item.manifest_json.get("fileCount"),
        },
        actor_user_id=context.user.id,
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
            "folder_path": item.manifest_json.get("folderPath"),
            "file_count": item.manifest_json.get("fileCount"),
        },
    )
    complete_command(db, command, result={"exportId": item.id})
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
        raise ApiProblem(
            404,
            "deep_analysis_export_not_found",
            "Mission 내보내기를 찾을 수 없습니다.",
        )
    return _export_payload(item)
