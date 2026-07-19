from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent_frontends import DEFAULT_AGENT_FRONTEND
from ..api.schemas import RunCreate, RunMessageInput
from ..config import Settings
from ..models import (
    Conversation,
    ProjectFile,
    ProjectFileVersion,
    Run,
    ToolExecution,
    User,
    utc_now,
)
from ..project_files.service import (
    create_project_file,
    logical_path_key,
)
from ..runs.service import create_run
from ..runs.state import CANCELLED, COMPLETED, TERMINAL_STATUSES
from ..storage import ManagedStorage
from .models import (
    DeepAnalysisMission,
    DeepAnalysisWorkflowEdge,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowRevision,
)
from .events import emit_event
from .context_manifest import (
    current_file_version,
    link_file,
    persist_context_manifest,
)
from .planning import next_runnable_node


@dataclass(frozen=True, slots=True)
class TerminalSyncResult:
    next_run_id: str | None = None
    changed: bool = False


def pending_terminal_run_ids(db: Session) -> tuple[str, ...]:
    return tuple(
        db.scalars(
            select(DeepAnalysisWorkflowNode.run_id)
            .join(
                Run,
                Run.id == DeepAnalysisWorkflowNode.run_id,
            )
            .where(
                DeepAnalysisWorkflowNode.status == "running",
                DeepAnalysisWorkflowNode.run_id.is_not(None),
                Run.status.in_(TERMINAL_STATUSES),
            )
        )
    )


def record_recovered_run_ids(db: Session, run_ids: tuple[str, ...]) -> None:
    if not run_ids:
        return
    rows = db.execute(
        select(DeepAnalysisWorkflowNode, DeepAnalysisWorkflowRevision, DeepAnalysisMission)
        .join(
            DeepAnalysisWorkflowRevision,
            DeepAnalysisWorkflowRevision.id
            == DeepAnalysisWorkflowNode.workflow_revision_id,
        )
        .join(
            DeepAnalysisMission,
            DeepAnalysisMission.id == DeepAnalysisWorkflowRevision.mission_id,
        )
        .where(DeepAnalysisWorkflowNode.run_id.in_(run_ids))
    ).all()
    for node, revision, mission in rows:
        emit_event(
            db,
            mission,
            "node_queued",
            {
                "nodeId": node.id,
                "nodeKey": node.node_key,
                "runId": node.run_id,
                "status": "queued",
                "recovered": True,
                "workflowRevisionId": revision.id,
            },
        )


def _run_context(
    db: Session, run_id: str
) -> tuple[
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowRevision,
    DeepAnalysisMission,
] | None:
    return db.execute(
        select(
            DeepAnalysisWorkflowNode, DeepAnalysisWorkflowRevision, DeepAnalysisMission
        )
        .join(
            DeepAnalysisWorkflowRevision,
            DeepAnalysisWorkflowRevision.id
            == DeepAnalysisWorkflowNode.workflow_revision_id,
        )
        .join(
            DeepAnalysisMission,
            DeepAnalysisMission.id == DeepAnalysisWorkflowRevision.mission_id,
        )
        .where(DeepAnalysisWorkflowNode.run_id == run_id)
    ).one_or_none()


def record_node_started(db: Session, run: Run) -> None:
    deep_analysis = run.snapshot_json.get("deep_analysis")
    if not isinstance(deep_analysis, dict) or deep_analysis.get("nodeStartedEvent"):
        return
    context = _run_context(db, run.id)
    if context is None:
        return
    node, revision, mission = context
    emit_event(
        db,
        mission,
        "node_started",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "runId": run.id,
            "status": run.status,
            "workflowRevisionId": revision.id,
            "attempt": len(node.run_history_json) + 1,
        },
    )
    run.snapshot_json = {
        **run.snapshot_json,
        "deep_analysis": {**deep_analysis, "nodeStartedEvent": True},
    }


def record_output_progress(db: Session, run: Run) -> None:
    """Persist bounded progress markers without copying model text into Mission events."""
    deep_analysis = run.snapshot_json.get("deep_analysis")
    if not isinstance(deep_analysis, dict) or not run.assistant_draft:
        return
    output_characters = len(run.assistant_draft)
    bucket = ((output_characters - 1) // 2000) + 1
    if int(deep_analysis.get("outputEventBucket") or 0) >= bucket:
        return
    context = _run_context(db, run.id)
    if context is None:
        return
    node, _revision, mission = context
    emit_event(
        db,
        mission,
        "node_output_delta",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "runId": run.id,
            "outputCharacters": output_characters,
            "progressBucket": bucket,
        },
    )
    run.snapshot_json = {
        **run.snapshot_json,
        "deep_analysis": {**deep_analysis, "outputEventBucket": bucket},
    }


_UNSAFE_PATH = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MARKDOWN_MARKERS = re.compile(r"(?m)^#{1,6}\s+|\*\*|__|`+|^[-*+]\s+")


def _path_segment(value: str, *, fallback: str, limit: int = 90) -> str:
    clean = _UNSAFE_PATH.sub("_", value).strip().strip(".")
    clean = re.sub(r"\s+", " ", clean)
    return (clean or fallback)[:limit].rstrip()


def _output_path(mission: DeepAnalysisMission, node: DeepAnalysisWorkflowNode) -> str:
    mission_name = _path_segment(mission.title, fallback="심층분석")
    node_name = _path_segment(node.title, fallback=node.node_key)
    return f"심층분석/{mission_name}_{mission.id[:8]}/{node.node_key}_{node_name}.md"


def _partial_output_path(
    mission: DeepAnalysisMission, node: DeepAnalysisWorkflowNode
) -> str:
    return _output_path(mission, node).removesuffix(".md") + "_partial.md"


def output_directory(mission: DeepAnalysisMission) -> str:
    mission_name = _path_segment(mission.title, fallback="심층분석")
    return f"심층분석/{mission_name}_{mission.id[:8]}"


def capture_source_manifest(
    db: Session, mission: DeepAnalysisMission
) -> list[dict[str, Any]]:
    """Freeze the exact Project-file revisions visible when a Mission starts."""
    rows = db.execute(
        select(ProjectFile, ProjectFileVersion)
        .join(
            ProjectFileVersion,
            (ProjectFileVersion.project_file_id == ProjectFile.id)
            & (ProjectFileVersion.version_number == ProjectFile.current_version_number),
        )
        .where(
            ProjectFile.project_id == mission.project_id,
            ProjectFile.deleted_at.is_(None),
            ProjectFile.status == "active",
            # Mission 산출물은 다음 Mission의 원본 입력으로 자동 승계하지 않습니다.
            # 필요한 경우 사용자가 Project 파일 영역으로 복사해 명시적으로 포함합니다.
            ~ProjectFile.logical_path.startswith("심층분석/"),
        )
        .order_by(ProjectFile.logical_path, ProjectFile.id)
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
    ]


def _run_manifest(
    db: Session,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
) -> list[dict[str, Any]]:
    manifest = [dict(item) for item in mission.source_manifest_json]
    known_ids = {
        str(item.get("projectFileId"))
        for item in manifest
        if item.get("projectFileId")
    }
    workflow_nodes = list(
        db.scalars(
            select(DeepAnalysisWorkflowNode).where(
                DeepAnalysisWorkflowNode.workflow_revision_id
                == node.workflow_revision_id
            )
        )
    )
    edges = list(
        db.scalars(
            select(DeepAnalysisWorkflowEdge).where(
                DeepAnalysisWorkflowEdge.workflow_revision_id
                == node.workflow_revision_id
            )
        )
    )
    incoming: dict[str, set[str]] = {}
    for edge in edges:
        incoming.setdefault(edge.target_node_key, set()).add(edge.source_node_key)
    ancestor_keys: set[str] = set()
    queue = list(incoming.get(node.node_key, set()))
    while queue:
        key = queue.pop(0)
        if key in ancestor_keys:
            continue
        ancestor_keys.add(key)
        queue.extend(incoming.get(key, set()))
    generated_ids: set[str] = set()
    for candidate in workflow_nodes:
        if candidate.node_key not in ancestor_keys:
            continue
        if candidate.output_project_file_id:
            generated_ids.add(candidate.output_project_file_id)
        for item in candidate.generated_files_json:
            if isinstance(item, dict) and item.get("projectFileId"):
                generated_ids.add(str(item["projectFileId"]))
    if not generated_ids:
        return manifest
    generated = db.execute(
        select(ProjectFile, ProjectFileVersion)
        .join(
            ProjectFileVersion,
            (ProjectFileVersion.project_file_id == ProjectFile.id)
            & (ProjectFileVersion.version_number == ProjectFile.current_version_number),
        )
        .where(
            ProjectFile.project_id == mission.project_id,
            ProjectFile.deleted_at.is_(None),
            ProjectFile.id.in_(generated_ids),
        )
        .order_by(ProjectFile.logical_path)
    ).tuples()
    for project_file, version in generated:
        if project_file.id in known_ids:
            continue
        manifest.append(
            {
                "projectFileId": project_file.id,
                "logicalPath": project_file.logical_path,
                "version": version.version_number,
                "versionId": version.id,
                "contentHash": version.content_hash,
                "mimeType": version.mime_type,
                "sizeBytes": version.size_bytes,
                "generated": True,
            }
        )
    return manifest


def _manifest_prompt(manifest: list[dict[str, Any]]) -> str:
    if not manifest:
        return "- 시작 시점에 등록된 Project 파일이 없습니다. 자료 부재를 결과에 명시하십시오."
    lines = [
        (
            f"- {item['logicalPath']} (fileId:{item['projectFileId']}, "
            f"versionId:{item.get('versionId', 'unknown')}, v{item['version']}, "
            f"sha256:{item['contentHash']})"
        )
        for item in manifest[:200]
    ]
    if len(manifest) > 200:
        lines.append(f"- 외 {len(manifest) - 200}개 파일은 고정 manifest에 포함되어 있습니다.")
    return "\n".join(lines)


def _summary(markdown: str, limit: int = 420) -> str:
    text = _MARKDOWN_MARKERS.sub("", markdown)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _cost_microusd(usage: dict[str, Any]) -> int:
    value = usage.get("cost_usd")
    if value is None:
        breakdown = usage.get("estimated_cost_breakdown_usd")
        if isinstance(breakdown, dict):
            value = breakdown.get("total")
    try:
        return max(0, int(round(float(value or 0) * 1_000_000)))
    except (TypeError, ValueError):
        return 0


def _stage_instruction(node: DeepAnalysisWorkflowNode) -> str:
    instructions = {
        "scope": (
            "분석 질문을 검증 가능한 형태로 구체화하고, 포함·제외 범위, 핵심 정의, "
            "성공 기준과 필요한 가정을 명시하십시오."
        ),
        "data_check": (
            "Project 파일 목록과 관련 자료를 실제로 확인하십시오. 사용 가능한 근거, 기간·단위·누락·중복·정합성 "
            "문제를 구분하고, 자료가 부족하면 가능한 분석과 불가능한 분석을 명확히 나누십시오."
        ),
        "research": (
            "질문에 필요한 근거와 사례를 실제 자료에서 수집하고, 출처·시점·적용 범위와 빠진 근거를 구분하십시오. "
            "근거가 부족하면 확인된 사실과 추정 영역을 명확히 나누십시오."
        ),
        "analysis": (
            "확인된 자료와 앞 단계 정의를 사용해 핵심 원인과 기여도를 분석하십시오. 숫자 계산이 필요하면 "
            "직접 암산하지 말고 Python 등 실행 도구로 재현 가능한 계산을 수행하고 계산식·입력·결과를 남기십시오."
        ),
        "validation": (
            "앞 단계 결과를 독립적으로 교차검증하고, 반대 근거·대안 설명·자료 품질 문제가 결론을 바꾸는지 점검하십시오. "
            "통과한 주장과 추가 확인이 필요한 주장을 구분하십시오."
        ),
        "synthesis": (
            "앞 단계의 가설과 결과를 서로 교차 검증하고, 반대 근거와 대안 설명을 점검하십시오. "
            "확실한 결론, 조건부 결론, 미확인 항목을 분리하십시오."
        ),
        "report": (
            "의사결정자가 바로 사용할 수 있는 최종 보고서를 작성하십시오. 요약, 핵심 결론, 근거, "
            "정량 결과, 한계, 권고 조치와 후속 확인 항목을 포함하십시오."
        ),
    }
    return instructions.get(node.node_type, node.purpose)


def _run_profile(node: DeepAnalysisWorkflowNode) -> tuple[str, str]:
    return "standard", "standard"


def _run_prompt(
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    manifest: list[dict[str, Any]],
) -> str:
    return f"""당신은 Lumina Workflow에서 하나의 작업 세션을 실행하고 있습니다.

Mission: {mission.title}
Mission 설명: {mission.objective or mission.title}
작업 세션: {node.node_key} · {node.title}

선행 세션 출력과 Project 파일:
{_manifest_prompt(manifest)}

작업 프롬프트:
{node.purpose or node.title}

실행 규칙:
- 선행 세션 출력은 위 manifest에 고정된 버전을 사용하십시오.
- 필요한 경우 Project 파일과 도구를 실제로 확인·사용하십시오.
- 확인하지 않은 사실이나 수치를 만들어내지 마십시오.
- 다음 Node가 그대로 인계받을 수 있는 독립적인 Markdown 문서만 한국어로 작성하십시오.
- 채팅 인사말이나 작업 예고 없이 완성된 본문부터 출력하십시오.
"""


def _ensure_node_conversation(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
) -> Conversation:
    if node.conversation_id:
        existing = db.get(Conversation, node.conversation_id)
        if existing is not None:
            return existing
    conversation = Conversation(
        organization_id=mission.organization_id,
        project_id=mission.project_id,
        owner_user_id=user.id,
        title=f"{mission.title} · {node.node_key} {node.title}",
        surface="deep_analysis",
        agent_id=DEFAULT_AGENT_FRONTEND.agent_id,
        agent_version=DEFAULT_AGENT_FRONTEND.agent_version,
        revision=1,
    )
    db.add(conversation)
    db.flush()
    node.conversation_id = conversation.id
    return conversation


def create_node_run(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    settings: Settings,
) -> tuple[Run, bool]:
    if node.run_id:
        existing = db.get(Run, node.run_id)
        if existing is not None:
            return existing, False
    conversation = _ensure_node_conversation(
        db,
        user=user,
        mission=mission,
        node=node,
    )
    manifest = _run_manifest(db, mission, node)
    analysis_depth, answer_length = _run_profile(node)
    attempt = len(node.run_history_json) + 1
    prompt = _run_prompt(
        mission,
        node,
        manifest,
    )
    run, _message, created = create_run(
        db,
        user=user,
        conversation_id=conversation.id,
        payload=RunCreate(
            message=RunMessageInput(
                text=prompt,
                output_mode="chat",
                analysis_depth=analysis_depth,
                answer_length=answer_length,
            )
        ),
        idempotency_key=(
            f"deep-analysis:{mission.id}:{node.node_key}:attempt:{attempt}"
        ),
        extension_snapshot_override=[],
        image_backend_model=settings.codex_image_model,
        settings=settings,
    )
    run.snapshot_json = {
        **run.snapshot_json,
        "clarification_mode": "autonomous",
        "memory_learning_mode": "off",
        "deep_analysis": {
            "mission_id": mission.id,
            "node_id": node.id,
            "node_key": node.node_key,
            "attempt": attempt,
            "output_directory": output_directory(mission),
        },
        "project_file_manifest": manifest,
    }
    if mission.budget_microusd is not None:
        remaining_usd = max(
            0.0,
            (mission.budget_microusd - mission.spent_microusd) / 1_000_000,
        )
        limits = dict(run.snapshot_json.get("limits", {}))
        configured_limit = float(limits.get("maxCostUsd") or 0)
        if remaining_usd > 0 and (
            configured_limit <= 0 or remaining_usd < configured_limit
        ):
            limits["maxCostUsd"] = remaining_usd
            run.snapshot_json = {**run.snapshot_json, "limits": limits}
    node.run_id = run.id
    node.status = "running"
    node.started_at = node.started_at or utc_now()
    node.error_message = None
    db.flush()
    context_manifest = persist_context_manifest(
        db,
        mission=mission,
        node=node,
        run=run,
        files=manifest,
        tool_profile="deep-analysis-core-v1",
        dynamic_context_characters=len(prompt),
    )
    if created:
        emit_event(
            db,
            mission,
            "node_queued",
            {
                "nodeId": node.id,
                "nodeKey": node.node_key,
                "runId": run.id,
                "status": run.status,
                "attempt": attempt,
                "workflowRevisionId": node.workflow_revision_id,
                "contextManifestId": context_manifest.id,
                "prefixHash": context_manifest.prefix_hash,
            },
        )
    return run, created


def archive_current_attempt(
    db: Session, node: DeepAnalysisWorkflowNode
) -> None:
    if not node.run_id:
        return
    run = db.get(Run, node.run_id)
    item = {
        "attempt": len(node.run_history_json) + 1,
        "runId": node.run_id,
        "status": run.status if run is not None else node.status,
        "costMicrousd": _cost_microusd(run.usage_json) if run is not None else 0,
        "errorMessage": (
            run.error_message if run is not None and run.error_message else node.error_message
        ),
        "startedAt": (
            run.started_at.isoformat()
            if run is not None and run.started_at is not None
            else node.started_at.isoformat() if node.started_at is not None else None
        ),
        "finishedAt": (
            run.finished_at.isoformat()
            if run is not None and run.finished_at is not None
            else node.finished_at.isoformat() if node.finished_at is not None else None
        ),
    }
    node.run_history_json = [*node.run_history_json, item]


def _generated_files(db: Session, run_id: str) -> list[dict[str, Any]]:
    tools = db.scalars(
        select(ToolExecution)
        .where(
            ToolExecution.run_id == run_id,
            ToolExecution.tool_name == "run_python_calculation",
            ToolExecution.status == "completed",
        )
        .order_by(ToolExecution.created_at, ToolExecution.id)
    )
    files: list[dict[str, Any]] = []
    for tool in tools:
        result = tool.result_json or {}
        for item in result.get("files", []):
            if isinstance(item, dict) and item.get("projectFileId"):
                files.append(dict(item))
    return files


def _mission_spent(db: Session, workflow_revision_id: str) -> int:
    total = 0
    for item in db.scalars(
        select(DeepAnalysisWorkflowNode).where(
            DeepAnalysisWorkflowNode.workflow_revision_id == workflow_revision_id
        )
    ):
        total += item.actual_cost_microusd
        total += sum(
            int(history.get("costMicrousd") or 0)
            for history in item.run_history_json
            if isinstance(history, dict)
        )
    return total


def _save_output(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    run: Run,
    markdown: str,
    storage: ManagedStorage,
    settings: Settings,
) -> None:
    if node.output_project_file_id:
        return
    logical_path = _output_path(mission, node)
    existing = db.scalar(
        select(ProjectFile).where(
            ProjectFile.project_id == mission.project_id,
            ProjectFile.active_path_key == logical_path_key(logical_path),
            ProjectFile.deleted_at.is_(None),
        )
    )
    if existing is not None:
        node.output_project_file_id = existing.id
        node.output_logical_path = existing.logical_path
        version_row = current_file_version(db, existing.id)
        if version_row is not None:
            _file, version = version_row
            link_file(
                db,
                mission=mission,
                project_file_id=existing.id,
                version_id=version.id,
                node=node,
                run=run,
                purpose="node_output",
                validation_status="completed",
                metadata={"logicalPath": existing.logical_path},
            )
        return
    project_file, version = create_project_file(
        db,
        user=user,
        project_id=mission.project_id,
        logical_path=logical_path,
        original_filename=PurePosixPath(logical_path).name,
        content=markdown.encode("utf-8"),
        change_reason=f"심층분석 {mission.id} {node.node_key} 출력",
        max_upload_bytes=settings.max_upload_bytes,
        storage=storage,
    )
    node.output_project_file_id = project_file.id
    node.output_logical_path = project_file.logical_path
    link_file(
        db,
        mission=mission,
        project_file_id=project_file.id,
        version_id=version.id,
        node=node,
        run=run,
        purpose="node_output",
        validation_status="completed",
        metadata={"logicalPath": project_file.logical_path},
    )


def _save_partial_output(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    run: Run,
    markdown: str,
    storage: ManagedStorage,
    settings: Settings,
) -> tuple[str, str] | None:
    content = markdown.strip()
    if not content:
        return None
    logical_path = _partial_output_path(mission, node)
    existing = db.scalar(
        select(ProjectFile).where(
            ProjectFile.project_id == mission.project_id,
            ProjectFile.active_path_key == logical_path_key(logical_path),
            ProjectFile.deleted_at.is_(None),
        )
    )
    if existing is not None:
        version_row = current_file_version(db, existing.id)
        if version_row is None:
            return None
        project_file, version = version_row
    else:
        project_file, version = create_project_file(
            db,
            user=user,
            project_id=mission.project_id,
            logical_path=logical_path,
            original_filename=PurePosixPath(logical_path).name,
            content=content.encode("utf-8"),
            change_reason=f"심층분석 {mission.id} {node.node_key} 중단 출력 보존",
            max_upload_bytes=settings.max_upload_bytes,
            storage=storage,
        )
    link_file(
        db,
        mission=mission,
        project_file_id=project_file.id,
        version_id=version.id,
        node=node,
        run=run,
        purpose="partial_output",
        validation_status="interrupted",
        metadata={
            "logicalPath": project_file.logical_path,
            "terminalRunStatus": run.status,
        },
    )
    return project_file.id, project_file.logical_path


def preserve_partial_output(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    run: Run,
    storage: ManagedStorage,
    settings: Settings,
) -> tuple[str, str] | None:
    saved = _save_partial_output(
        db,
        user=user,
        mission=mission,
        node=node,
        run=run,
        markdown=run.assistant_draft,
        storage=storage,
        settings=settings,
    )
    if saved is None:
        return None
    project_file_id, logical_path = saved
    emit_event(
        db,
        mission,
        "mission_file_created",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "projectFileId": project_file_id,
            "logicalPath": logical_path,
            "purpose": "partial_output",
            "validationStatus": "interrupted",
        },
    )
    return saved


def sync_terminal_run(
    db: Session,
    *,
    run_id: str,
    storage: ManagedStorage,
    settings: Settings,
) -> TerminalSyncResult:
    row = db.execute(
        select(
            DeepAnalysisWorkflowNode, DeepAnalysisWorkflowRevision, DeepAnalysisMission
        )
        .join(
            DeepAnalysisWorkflowRevision,
            DeepAnalysisWorkflowRevision.id
            == DeepAnalysisWorkflowNode.workflow_revision_id,
        )
        .join(
            DeepAnalysisMission,
            DeepAnalysisMission.id == DeepAnalysisWorkflowRevision.mission_id,
        )
        .where(DeepAnalysisWorkflowNode.run_id == run_id)
    ).one_or_none()
    if row is None:
        return TerminalSyncResult()
    node, workflow_revision, mission = row
    run = db.get(Run, run_id)
    if run is None or run.status not in TERMINAL_STATUSES:
        return TerminalSyncResult()
    if node.status in {"completed", "failed", "cancelled"}:
        return TerminalSyncResult()

    node.actual_cost_microusd = _cost_microusd(run.usage_json)
    node.generated_files_json = _generated_files(db, run_id)
    node.finished_at = run.finished_at or utc_now()
    user = db.get(User, mission.created_by_user_id)
    if user is None:
        node.status = "failed"
        node.error_message = "실행 사용자를 찾을 수 없습니다."
        mission.status = "failed"
        mission.revision += 1
        return TerminalSyncResult(changed=True)

    if run.status == COMPLETED:
        markdown = run.assistant_draft.strip()
        if not markdown:
            node.status = "failed"
            node.error_message = "모델이 비어 있는 출력을 반환했습니다."
            mission.status = "failed"
            mission.revision += 1
            return TerminalSyncResult(changed=True)
        _save_output(
            db,
            user=user,
            mission=mission,
            node=node,
            run=run,
            markdown=markdown,
            storage=storage,
            settings=settings,
        )
        node.output_markdown = markdown
        node.output_summary = _summary(markdown)
        node.status = "completed"
        node.error_message = None
        db.flush()
        for generated_file in node.generated_files_json:
            if not isinstance(generated_file, dict) or not generated_file.get("projectFileId"):
                continue
            version_row = current_file_version(db, str(generated_file["projectFileId"]))
            if version_row is None:
                continue
            project_file, version = version_row
            link_file(
                db,
                mission=mission,
                project_file_id=project_file.id,
                version_id=version.id,
                node=node,
                run=run,
                purpose="calculation_output",
                validation_status="tool_completed",
                metadata={
                    "logicalPath": project_file.logical_path,
                    "kind": generated_file.get("kind"),
                },
            )
        emit_event(
            db,
            mission,
            "node_completed",
            {
                "nodeId": node.id,
                "nodeKey": node.node_key,
                "runId": run.id,
                "status": node.status,
                "outputProjectFileId": node.output_project_file_id,
                "outputLogicalPath": node.output_logical_path,
                "actualCostMicrousd": node.actual_cost_microusd,
            },
        )
        if node.output_project_file_id:
            emit_event(
                db,
                mission,
                "mission_file_created",
                {
                    "nodeId": node.id,
                    "nodeKey": node.node_key,
                    "projectFileId": node.output_project_file_id,
                    "logicalPath": node.output_logical_path,
                },
            )
        mission.spent_microusd = _mission_spent(db, workflow_revision.id)
        emit_event(
            db,
            mission,
            "mission_cost_updated",
            {
                "spentMicrousd": mission.spent_microusd,
                "budgetMicrousd": mission.budget_microusd,
                "nodeId": node.id,
                "nodeKey": node.node_key,
            },
        )

        nodes = list(
            db.scalars(
                select(DeepAnalysisWorkflowNode)
                .where(
                    DeepAnalysisWorkflowNode.workflow_revision_id
                    == workflow_revision.id
                )
                .order_by(DeepAnalysisWorkflowNode.sequence)
            )
        )
        edges = list(
            db.scalars(
                select(DeepAnalysisWorkflowEdge).where(
                    DeepAnalysisWorkflowEdge.workflow_revision_id
                    == workflow_revision.id
                )
            )
        )
        next_node = next_runnable_node(nodes, edges)
        if next_node is None:
            unresolved = [
                item
                for item in nodes
                if item.status in {"planned", "ready", "running"}
            ]
            if unresolved:
                mission.status = "blocked"
                mission.revision += 1
                emit_event(
                    db,
                    mission,
                    "mission_status_changed",
                    {
                        "status": mission.status,
                        "missionRevision": mission.revision,
                        "blockedNodeKeys": [item.node_key for item in unresolved],
                    },
                )
                return TerminalSyncResult(changed=True)
            mission.status = "completed"
            mission.completion_outcome = "satisfied"
            mission.revision += 1
            emit_event(
                db,
                mission,
                "mission_completed",
                {
                    "status": mission.status,
                    "missionRevision": mission.revision,
                    "finalOutputFileId": node.output_project_file_id,
                },
            )
            return TerminalSyncResult(changed=True)

        if (
            mission.budget_microusd is not None
            and mission.spent_microusd >= mission.budget_microusd
        ):
            mission.status = "blocked"
            mission.revision += 1
            emit_event(
                db,
                mission,
                "mission_budget_warning",
                {
                    "status": mission.status,
                    "spentMicrousd": mission.spent_microusd,
                    "budgetMicrousd": mission.budget_microusd,
                    "missionRevision": mission.revision,
                },
            )
            return TerminalSyncResult(changed=True)

        next_run, created = create_node_run(
            db,
            user=user,
            mission=mission,
            node=next_node,
            settings=settings,
        )
        mission.revision += 1
        return TerminalSyncResult(
            next_run_id=next_run.id if created else None,
            changed=True,
        )

    preserve_partial_output(
        db,
        user=user,
        mission=mission,
        node=node,
        run=run,
        storage=storage,
        settings=settings,
    )
    node.status = "cancelled" if run.status == CANCELLED else "failed"
    node.error_message = (
        None
        if run.status == CANCELLED
        else (run.error_message or "Node 실행에 실패했습니다.")
    )
    mission.status = "cancelled" if run.status == CANCELLED else "failed"
    mission.spent_microusd = _mission_spent(db, workflow_revision.id)
    mission.revision += 1
    emit_event(
        db,
        mission,
        "node_failed" if node.status == "failed" else "node_cancelled",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "runId": run.id,
            "status": node.status,
            "missionStatus": mission.status,
            "missionRevision": mission.revision,
            "actualCostMicrousd": node.actual_cost_microusd,
        },
    )
    return TerminalSyncResult(changed=True)


def fail_terminal_sync(db: Session, *, run_id: str, message: str) -> bool:
    row = db.execute(
        select(DeepAnalysisWorkflowNode, DeepAnalysisMission)
        .join(
            DeepAnalysisWorkflowRevision,
            DeepAnalysisWorkflowRevision.id
            == DeepAnalysisWorkflowNode.workflow_revision_id,
        )
        .join(
            DeepAnalysisMission,
            DeepAnalysisMission.id == DeepAnalysisWorkflowRevision.mission_id,
        )
        .where(DeepAnalysisWorkflowNode.run_id == run_id)
    ).one_or_none()
    if row is None:
        return False
    node, mission = row
    if node.status != "running":
        return False
    node.status = "failed"
    node.error_message = message
    node.finished_at = utc_now()
    mission.status = "failed"
    mission.revision += 1
    emit_event(
        db,
        mission,
        "node_failed",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "runId": run_id,
            "status": node.status,
            "missionStatus": mission.status,
            "missionRevision": mission.revision,
        },
    )
    return True
