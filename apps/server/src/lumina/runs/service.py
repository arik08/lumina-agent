from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder

from ..api.errors import ApiProblem
from ..api.schemas import (
    ExecutionSelection,
    MessageReferenceInput,
    RunActionRequest,
    RunCreate,
)
from ..artifacts.service import artifact_summary, current_artifact_version
from ..config import Settings, get_settings
from ..audit import record_audit
from ..authorization import require_conversation
from ..extensions.service import resolve_skill_snapshot
from ..instructions import (
    resolve_instruction_stack_from_models,
    runtime_prompt_snapshot,
)
from ..mcp.service import resolve_mcp_snapshot
from ..models import (
    Artifact,
    ArtifactVersion,
    Attachment,
    CompactedContextEntry,
    Conversation,
    Message,
    MessageReference,
    Organization,
    Plan,
    PlanStep,
    Project,
    ProjectFile,
    ProjectFileVersion,
    ProjectSetting,
    ProviderModel,
    QueuedMessage,
    Run,
    RunCommand,
    RunEvent,
    ToolApproval,
    ToolExecution,
    User,
    UserSetting,
    new_uuid,
    utc_now,
)
from ..notifications import create_run_transition_notification
from ..project_files import get_project_file_version
from ..project_files.folders import build_project_folder_references
from ..project_memories import select_relevant_project_memories
from ..projects.memberships import effective_project_role
from ..providers.catalog import (
    catalog_model,
    estimate_model_cost_parts,
)
from ..providers.execution_defaults import initial_execution_selection
from .approvals import approval_payload, pending_approval_payloads
from .safety import run_limit_snapshot
from .subtasks import list_step_subtasks
from .state import (
    ACTIVE_STATUSES,
    AWAITING_APPROVAL,
    CANCELLED,
    COMPLETED,
    INTERRUPTED,
    MODEL_STREAMING,
    PAUSED,
    QUEUED,
    TERMINAL_STATUSES,
    ensure_transition,
)


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


UNTITLED_CONVERSATION_TITLES = {"제목 없음", "새 작업"}
CONVERSATION_TITLE_MAX_LENGTH = 60


def _conversation_title_from_message(message_text: str) -> str:
    normalized = " ".join(message_text.split())
    if len(normalized) <= CONVERSATION_TITLE_MAX_LENGTH:
        return normalized
    return normalized[: CONVERSATION_TITLE_MAX_LENGTH - 1].rstrip() + "…"


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


def resolve_execution(
    db: Session,
    payload: RunCreate,
    *,
    image_backend_model: str | None = None,
    user: User | None = None,
    project: Project | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    config = settings or get_settings()
    requested = payload.execution
    preference_messages: list[str] = []
    if requested is None:
        if user is None or project is None:
            raise ApiProblem(
                409,
                "execution_selection_unavailable",
                "Run 기본 실행 설정을 해석할 사용자와 Project가 필요합니다.",
            )
        requested, preference_messages = _default_execution_selection(
            db, user=user, project=project, settings=config
        )
    if requested.provider_id == "mock":
        if config.environment == "production":
            raise ApiProblem(
                409,
                "mock_provider_forbidden",
                "운영 환경에서는 Mock Provider를 사용할 수 없습니다.",
            )
        return {
            "provider_id": "mock",
            "model_key": "mock-agent",
            "runtime_model_id": "mock-agent",
            "model_display_name": "Lumina Mock Agent",
            "effort": requested.effort_id or "medium",
            "catalog_revision": "development",
            "capabilities": {"tools": True, "structured_output": True},
            "fallback_messages": preference_messages,
        }

    model = db.scalar(
        select(ProviderModel).where(
            ProviderModel.provider_id == requested.provider_id,
            ProviderModel.model_key == requested.model_key,
            ProviderModel.enabled.is_(True),
        )
    )
    fallback_messages = list(preference_messages)
    if model is None:
        model = db.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_id == requested.provider_id,
                ProviderModel.enabled.is_(True),
                ProviderModel.is_default.is_(True),
            )
        )
        if model:
            fallback_messages.append(
                f"선택한 모델을 사용할 수 없어 {model.display_name}(으)로 변경했습니다."
            )
    if model is None:
        raise ApiProblem(
            409, "provider_unavailable", "사용 가능한 Provider 모델이 없습니다."
        )
    resolved = {
        "provider_id": model.provider_id,
        "model_key": model.model_key,
        "runtime_model_id": model.runtime_model_id,
        "model_display_name": model.display_name,
        "effort": requested.effort_id,
        "catalog_revision": model.catalog_revision,
        "capabilities": _model_capabilities_snapshot(model),
        "fallback_messages": fallback_messages,
    }
    if model.provider_id == "codex" and bool(
        model.capabilities_json.get("image_generation")
    ):
        resolved["image_backend_model"] = (
            image_backend_model or config.codex_image_model
        )
    return resolved


def _model_capabilities_snapshot(model: ProviderModel) -> dict[str, Any]:
    """Pin reviewed hard limits and the admin-selected operating limit to a Run."""
    capabilities = dict(model.capabilities_json)
    catalog_entry = catalog_model(model.provider_id, model.model_key)
    if catalog_entry is None:
        return capabilities
    hard_max = catalog_entry.capabilities.max_output_tokens
    if hard_max is not None:
        capabilities["max_output_tokens"] = hard_max
    if catalog_entry.context_compaction_threshold is not None:
        capabilities["context_compaction_threshold"] = (
            catalog_entry.context_compaction_threshold
        )
    configured_max = capabilities.get(
        "configured_max_output_tokens",
        capabilities.get("configuredMaxOutputTokens"),
    )
    if (
        not isinstance(configured_max, int)
        or isinstance(configured_max, bool)
        or configured_max < 1
        or (hard_max is not None and configured_max > hard_max)
    ):
        configured_max = catalog_entry.default_max_output_tokens
    if configured_max is not None:
        capabilities["configured_max_output_tokens"] = configured_max
    capabilities.pop("configuredMaxOutputTokens", None)
    return capabilities


def _default_execution_selection(
    db: Session,
    *,
    user: User,
    project: Project,
    settings: Settings,
) -> tuple[ExecutionSelection, list[str]]:
    project_setting = db.scalar(
        select(ProjectSetting).where(
            ProjectSetting.project_id == project.id,
            ProjectSetting.key == "execution.default",
        )
    )
    user_setting = db.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user.id,
            UserSetting.key == "execution.default",
        )
    )
    setting = project_setting if project.project_type == "shared" else user_setting
    value = setting.value_json if setting is not None else None
    if isinstance(value, dict):
        provider_id = value.get("providerId", value.get("provider_id"))
        model_key = value.get("modelKey", value.get("model_key"))
        effort_id = value.get("effortId", value.get("effort_id"))
        if isinstance(provider_id, str) and isinstance(model_key, str):
            if settings.environment != "production" or provider_id != "mock":
                return (
                    ExecutionSelection(
                        provider_id=provider_id,
                        model_key=model_key,
                        effort_id=effort_id if isinstance(effort_id, str) else None,
                    ),
                    [],
                )
            warning = "저장된 Mock 기본값은 운영 환경에서 허용되지 않아 운영 기본값으로 변경했습니다."
        else:
            warning = "저장된 실행 기본값이 올바르지 않아 애플리케이션 기본값으로 변경했습니다."
    else:
        warning = ""

    fallback_value, _fallback_source = initial_execution_selection(
        db,
        organization_id=user.organization_id,
        environment=settings.environment,
    )
    fallback = ExecutionSelection(
        provider_id=str(fallback_value["providerId"]),
        model_key=str(fallback_value["modelKey"]),
        effort_id=(
            str(fallback_value["effortId"])
            if fallback_value["effortId"] is not None
            else None
        ),
    )
    return fallback, [warning] if warning else []


def create_run(
    db: Session,
    *,
    user: User,
    conversation_id: str,
    payload: RunCreate,
    idempotency_key: str,
    extension_snapshot_override: list[dict[str, Any]] | None = None,
    apply_extension_snapshot: bool = False,
    image_backend_model: str | None = None,
    settings: Settings | None = None,
) -> tuple[Run, Message, bool]:
    config = settings or get_settings()
    conversation = require_conversation(db, user, conversation_id, write=True)
    existing = db.scalar(
        select(Run).where(
            Run.conversation_id == conversation.id,
            Run.user_id == user.id,
            Run.idempotency_key == idempotency_key,
        )
    )
    if existing:
        message = db.scalar(
            select(Message).where(Message.run_id == existing.id, Message.role == "user")
        )
        if message is None:
            raise ApiProblem(
                409, "run_incomplete", "기존 Run의 사용자 메시지를 찾을 수 없습니다."
            )
        return existing, message, False

    attachment_ids = _validate_attachments(
        db, user, conversation.project_id, payload.message.attachment_ids
    )
    references = _validate_references(
        db,
        user,
        conversation.id,
        payload.message.prompt_references,
        message_text=payload.message.text,
    )
    target_output_tokens = (
        payload.message.target_output_tokens
        if payload.message.output_mode != "chat"
        else None
    )
    project_file_snapshots = [
        {
            "reference_id": reference["reference_id"],
            "version_or_digest": reference["version_or_digest"],
            "display_snapshot": reference["display_snapshot"],
        }
        for reference in references
        if reference.get("kind") == "file"
        and isinstance(reference.get("display_snapshot"), dict)
        and reference["display_snapshot"].get("targetType") == "project_file"
    ]
    project = db.get(Project, conversation.project_id)
    if project is None:
        raise ApiProblem(409, "project_missing", "대화의 Project를 찾을 수 없습니다.")
    execution = resolve_execution(
        db,
        payload,
        image_backend_model=image_backend_model,
        user=user,
        project=project,
        settings=config,
    )
    memory_learning_mode = _memory_learning_mode(db, user.id)
    from ..memories.service import select_relevant_memories

    user_memories = select_relevant_memories(
        db,
        user_id=user.id,
        query=payload.message.text,
        limit=8,
        character_budget=8_000,
    )
    user_memory_snapshots = [
        {
            "id": memory.id,
            "category": memory.category,
            "display_text": memory.display_text,
            "confidence": memory.confidence,
            "evidence_count": memory.evidence_count,
            "last_confirmed_at": memory.last_confirmed_at.isoformat(),
        }
        for memory in user_memories
    ]
    project_memories = select_relevant_project_memories(
        db,
        project_id=project.id,
        query=payload.message.text,
        limit=6,
        character_budget=6_000,
    )
    project_memory_snapshots = [
        {
            "id": memory.id,
            "memory_key": memory.memory_key,
            "revision": memory.revision,
            "content_hash": memory.content_hash,
            "category": memory.category,
            "display_text": memory.display_text,
        }
        for memory in project_memories
    ]
    organization = db.get(Organization, user.organization_id)
    if organization is None:
        raise ApiProblem(
            409, "organization_missing", "사용자의 조직을 찾을 수 없습니다."
        )
    limits = run_limit_snapshot(organization.run_safety_settings_json)
    runtime_prompts = runtime_prompt_snapshot(db, organization)
    instruction_stack = resolve_instruction_stack_from_models(
        organization=organization,
        project=project,
        user=user,
        agent_default=str(runtime_prompts["agent_default"]["content"]),
    )
    instruction_snapshot = {
        "prompt_text": instruction_stack.prompt_text,
        "layers": [
            {
                "scope": layer.scope,
                "scope_id": layer.scope_id,
                "revision": layer.revision,
                "digest": layer.digest,
                "updated_at": (
                    layer.updated_at.isoformat()
                    if layer.updated_at is not None
                    else None
                ),
            }
            for layer in instruction_stack.layers
        ],
        "excluded_scopes": list(instruction_stack.excluded_scopes),
    }
    normalized_login_id = user.login_id.strip().casefold()
    prompt_cache_scope = (
        "lumina:user:v1:"
        + hashlib.sha256(normalized_login_id.encode("utf-8")).hexdigest()[:48]
    )
    extensions = (
        [dict(item) for item in extension_snapshot_override]
        if extension_snapshot_override is not None
        else resolve_skill_snapshot(db, user=user, project_id=project.id)
    )
    mcp_servers = _selected_mcp_snapshots(
        db,
        user=user,
        project_id=project.id,
        references=references,
    )
    extension_application = (
        "all_snapshot" if apply_extension_snapshot else "explicit_references"
    )
    stable_prefix = {
        "contract_version": "lumina-run-v1",
        "agent": {"id": conversation.agent_id, "version": conversation.agent_version},
        "project": {
            "id": project.id,
            "concept": project.concept,
            "concept_revision": project.concept_revision,
            "concept_hash": project.concept_hash,
            "updated_at": project.updated_at.isoformat(),
        },
        "execution": execution,
        "output_mode": payload.message.output_mode,
        "instructions": instruction_snapshot,
        "runtime_prompts": runtime_prompts,
        "extensions": extensions,
        "extension_application": extension_application,
        "environment_type": "local_worker",
        "approval_mode": "on_risk",
        "prompt_cache_scope": prompt_cache_scope,
    }
    if mcp_servers:
        stable_prefix["mcp_servers"] = mcp_servers
    prefix_hash = hashlib.sha256(
        json.dumps(
            stable_prefix,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    assistant_message_id = new_uuid()
    run = Run(
        organization_id=user.organization_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        user_id=user.id,
        status=QUEUED,
        provider_id=execution["provider_id"],
        model_key=execution["model_key"],
        runtime_model_id=execution["runtime_model_id"],
        model_display_name=execution["model_display_name"],
        effort=execution["effort"],
        approval_mode="on_risk",
        environment_type="local_worker",
        # Retained only for compatibility with the existing database column.
        # Runtime termination no longer depends on a model-turn count.
        max_turns=0,
        snapshot_json={
            "execution": execution,
            "attachments": attachment_ids,
            "prompt_references": references,
            "project_files": project_file_snapshots,
            "user_memories": user_memory_snapshots,
            "project_memories": project_memory_snapshots,
            "assistant_message_id": assistant_message_id,
            "user_message_text": payload.message.text,
            "output_mode": payload.message.output_mode,
            "target_output_tokens": target_output_tokens,
            "agent": {
                "id": conversation.agent_id,
                "version": conversation.agent_version,
            },
            "project": stable_prefix["project"],
            "instructions": instruction_snapshot,
            "runtime_prompts": runtime_prompts,
            "extensions": extensions,
            "extension_application": extension_application,
            "prompt_prefix_hash": prefix_hash,
            "prompt_cache_scope": prompt_cache_scope,
            "contract_version": stable_prefix["contract_version"],
            "environment_type": "local_worker",
            "approval_mode": "on_risk",
            "limits": limits,
            "memory_learning_mode": memory_learning_mode,
            **({"mcp_servers": mcp_servers} if mcp_servers else {}),
        },
        idempotency_key=idempotency_key,
    )
    db.add(run)
    db.flush()
    create_run_plan(db, run, goal=payload.message.text)
    turn_index = (
        db.scalar(
            select(func.max(Message.turn_index)).where(
                Message.conversation_id == conversation.id
            )
        )
        or 0
    ) + 1
    message = Message(
        conversation_id=conversation.id,
        run_id=run.id,
        author_user_id=user.id,
        role="user",
        status="completed",
        canonical_text=payload.message.text,
        turn_index=turn_index,
        metadata_json={
            "attachment_ids": attachment_ids,
            "prompt_references": references,
            "output_mode": payload.message.output_mode,
            "target_output_tokens": target_output_tokens,
        },
    )
    db.add(message)
    db.flush()
    _persist_message_references(db, message, references)
    automatic_title_assigned = (
        turn_index == 1 and conversation.title in UNTITLED_CONVERSATION_TITLES
    )
    if automatic_title_assigned:
        conversation.title = _conversation_title_from_message(payload.message.text)
    conversation.last_activity_at = utc_now()
    conversation.revision += 1
    if automatic_title_assigned:
        run.snapshot_json = {
            **run.snapshot_json,
            "conversation_title": {
                "status": "generated",
                "value": conversation.title,
                "revision": conversation.revision,
            },
        }
    db.flush()
    append_event(
        db,
        run,
        "run_started",
        {"status": QUEUED, "plan": plan_snapshot(db, run)},
    )
    return run, message, True


def _validate_attachments(
    db: Session, user: User, project_id: str, attachment_ids: Iterable[str]
) -> list[str]:
    validated: list[str] = []
    for attachment_id in dict.fromkeys(attachment_ids):
        attachment = db.get(Attachment, attachment_id)
        if (
            attachment is None
            or attachment.deleted_at is not None
            or attachment.project_id != project_id
            or attachment.status not in {"ready", "completed"}
        ):
            raise ApiProblem(
                404, "attachment_not_found", "첨부 파일을 사용할 수 없습니다."
            )
        validated.append(attachment.id)
    return validated


def _memory_learning_mode(db: Session, user_id: str) -> str:
    setting = db.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user_id,
            UserSetting.key == "memory_learning",
        )
    )
    if setting is None or not isinstance(setting.value_json, dict):
        return "auto"
    mode = setting.value_json.get("mode")
    return mode if mode in {"auto", "confirm", "off"} else "auto"


def _validate_references(
    db: Session,
    user: User,
    conversation_id: str,
    references: Iterable[MessageReferenceInput],
    *,
    message_text: str,
) -> list[dict[str, Any]]:
    conversation = require_conversation(db, user, conversation_id)
    skill_snapshots = {
        str(item["extension_id"]): item
        for item in resolve_skill_snapshot(
            db, user=user, project_id=conversation.project_id
        )
    }
    mcp_snapshots = {
        str(item["definition_id"]): item
        for item in resolve_mcp_snapshot(
            db, user=user, project_id=conversation.project_id
        )
    }
    validated: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for reference in references:
        _validate_reference_shape(reference, message_text=message_text)
        payload = reference.model_dump(mode="json", by_alias=False)
        if reference.kind == "artifact":
            artifact = db.get(Artifact, reference.reference_id)
            if (
                artifact is None
                or artifact.deleted_at is not None
                or artifact.project_id != conversation.project_id
            ):
                raise ApiProblem(
                    404, "reference_not_found", "Artifact 참조를 찾을 수 없습니다."
                )
            version: ArtifactVersion | None = None
            selector_value = reference.version_or_digest
            if selector_value:
                selector = selector_value.removeprefix("v")
                version = (
                    db.scalar(
                        select(ArtifactVersion).where(
                            ArtifactVersion.artifact_id == artifact.id,
                            ArtifactVersion.version_number == int(selector),
                        )
                    )
                    if selector.isdigit()
                    else db.scalar(
                        select(ArtifactVersion)
                        .where(
                            ArtifactVersion.artifact_id == artifact.id,
                            ArtifactVersion.content_hash == selector_value,
                        )
                        .order_by(ArtifactVersion.version_number.desc())
                        .limit(1)
                    )
                )
            elif artifact.current_version_number is not None:
                version = db.scalar(
                    select(ArtifactVersion).where(
                        ArtifactVersion.artifact_id == artifact.id,
                        ArtifactVersion.version_number
                        == artifact.current_version_number,
                    )
                )
            if version is None:
                raise ApiProblem(
                    409,
                    "reference_version_unavailable",
                    "Artifact의 지정 버전을 사용할 수 없습니다.",
                )
            payload["version_or_digest"] = version.content_hash
            payload["display_snapshot"] = {
                "name": artifact.display_name,
                "kind": artifact.kind,
                "version": version.version_number,
                "contentHash": version.content_hash,
            }
        elif reference.kind == "folder":
            workspace_rows = list(
                db.execute(
                    select(ProjectFile, ProjectFileVersion)
                    .join(
                        ProjectFileVersion,
                        (ProjectFileVersion.project_file_id == ProjectFile.id)
                        & (
                            ProjectFileVersion.version_number
                            == ProjectFile.current_version_number
                        ),
                    )
                    .where(
                        ProjectFile.project_id == conversation.project_id,
                        ProjectFile.deleted_at.is_(None),
                        ProjectFile.status == "active",
                    )
                    .order_by(ProjectFile.logical_path, ProjectFile.id)
                )
            )
            folder = next(
                (
                    item
                    for item in build_project_folder_references(
                        conversation.project_id, workspace_rows
                    )
                    if item.id == reference.reference_id
                ),
                None,
            )
            if folder is None:
                raise ApiProblem(
                    404, "reference_not_found", "폴더 참조를 찾을 수 없습니다."
                )
            if (
                reference.version_or_digest
                and reference.version_or_digest != folder.content_hash
            ):
                raise ApiProblem(
                    409,
                    "reference_version_unavailable",
                    "폴더 내용이 선택 이후 변경되었습니다.",
                )
            payload["version_or_digest"] = folder.content_hash
            payload["display_snapshot"] = {
                "name": folder.name,
                "targetType": "project_folder",
                "logicalPath": folder.logical_path,
                "fileCount": len(folder.file_versions),
                "fileVersions": list(folder.file_versions),
                "contentHash": folder.content_hash,
            }
        elif reference.kind == "file":
            project_file = db.get(ProjectFile, reference.reference_id)
            if project_file is not None:
                if (
                    project_file.deleted_at is not None
                    or project_file.project_id != conversation.project_id
                    or project_file.status != "active"
                ):
                    raise ApiProblem(
                        404, "reference_not_found", "파일 참조를 찾을 수 없습니다."
                    )
                project_file_version = get_project_file_version(
                    db, project_file, reference.version_or_digest
                )
                payload["version_or_digest"] = project_file_version.content_hash
                payload["display_snapshot"] = {
                    "name": project_file.logical_path.rsplit("/", 1)[-1],
                    "targetType": "project_file",
                    "logicalPath": project_file.logical_path,
                    "mimeType": project_file_version.mime_type,
                    "version": project_file_version.version_number,
                    "versionId": project_file_version.id,
                    "contentHash": project_file_version.content_hash,
                }
            else:
                attachment = db.get(Attachment, reference.reference_id)
                if (
                    attachment is None
                    or attachment.deleted_at is not None
                    or attachment.project_id != conversation.project_id
                    or attachment.status not in {"ready", "completed"}
                ):
                    raise ApiProblem(
                        404, "reference_not_found", "파일 참조를 찾을 수 없습니다."
                    )
                if (
                    reference.version_or_digest
                    and reference.version_or_digest != attachment.content_hash
                ):
                    raise ApiProblem(
                        409,
                        "reference_version_unavailable",
                        "파일 내용이 선택 이후 변경되었습니다.",
                    )
                payload["version_or_digest"] = attachment.content_hash
                payload["display_snapshot"] = {
                    "name": attachment.original_filename,
                    "targetType": "attachment",
                    "mimeType": attachment.sniffed_mime_type,
                    "contentHash": attachment.content_hash,
                }
        elif reference.kind == "skill":
            snapshot = skill_snapshots.get(reference.reference_id)
            if snapshot is None:
                raise ApiProblem(
                    409,
                    "extension_not_installed",
                    "선택한 Skill이 현재 범위에 활성화되어 있지 않습니다.",
                )
            accepted_versions = {str(snapshot["digest"])}
            if snapshot.get("version") is not None:
                accepted_versions.update(
                    {str(snapshot["version"]), f"v{snapshot['version']}"}
                )
            if snapshot.get("draft_revision") is not None:
                accepted_versions.update(
                    {
                        str(snapshot["draft_revision"]),
                        f"r{snapshot['draft_revision']}",
                    }
                )
            if (
                reference.version_or_digest
                and reference.version_or_digest not in accepted_versions
            ):
                raise ApiProblem(
                    409,
                    "reference_version_unavailable",
                    "Skill의 선택한 revision을 사용할 수 없습니다.",
                )
            payload["version_or_digest"] = str(snapshot["digest"])
            payload["display_snapshot"] = {
                "name": snapshot["name"],
                "kind": snapshot.get("kind", "skill"),
                "slug": snapshot.get("slug"),
                "source": snapshot["source"],
                "version": snapshot.get("version"),
                "versionId": snapshot.get("version_id"),
                "draftRevision": snapshot.get("draft_revision"),
                "draftId": snapshot.get("draft_id"),
                "digest": snapshot["digest"],
            }
        else:
            snapshot = mcp_snapshots.get(reference.reference_id)
            if snapshot is None:
                raise ApiProblem(
                    409,
                    "extension_not_installed",
                    "선택한 MCP가 현재 범위에서 준비되어 있지 않습니다.",
                )
            accepted_versions = {
                str(snapshot["digest"]),
                str(snapshot["configuration_revision_id"]),
                str(snapshot["configuration_revision"]),
                f"r{snapshot['configuration_revision']}",
            }
            if (
                reference.version_or_digest
                and reference.version_or_digest not in accepted_versions
            ):
                raise ApiProblem(
                    409,
                    "reference_version_unavailable",
                    "MCP의 선택한 configuration revision을 사용할 수 없습니다.",
                )
            payload["version_or_digest"] = str(snapshot["digest"])
            payload["display_snapshot"] = {
                "name": snapshot["name"],
                "kind": "mcp",
                "slug": snapshot["slug"],
                "installationId": snapshot["installation_id"],
                "configurationRevisionId": snapshot["configuration_revision_id"],
                "configurationRevision": snapshot["configuration_revision"],
                "digest": snapshot["digest"],
                "toolAllowlist": snapshot["tool_allowlist"],
                "healthStatus": snapshot["health_status"],
                "schemaStatus": snapshot["schema_status"],
            }
        payload["validation_status"] = "valid"
        canonical_key = (
            str(payload["kind"]),
            str(payload["reference_id"]),
            str(payload.get("version_or_digest"))
            if payload.get("version_or_digest") is not None
            else None,
        )
        if canonical_key in seen:
            continue
        seen.add(canonical_key)
        validated.append(payload)
    return validated


def _selected_mcp_snapshots(
    db: Session,
    *,
    user: User,
    project_id: str,
    references: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    requested_ids = {
        str(reference.get("reference_id"))
        for reference in references
        if reference.get("kind") == "mcp"
    }
    if not requested_ids:
        return []
    available = {
        str(item["definition_id"]): item
        for item in resolve_mcp_snapshot(db, user=user, project_id=project_id)
    }
    return [
        dict(available[definition_id])
        for definition_id in sorted(requested_ids)
        if definition_id in available
    ]


def _validate_steer_mcp_references(
    run: Run, references: Iterable[dict[str, Any]]
) -> None:
    pinned = {
        str(item.get("definition_id")): str(item.get("digest"))
        for item in run.snapshot_json.get("mcp_servers", [])
        if isinstance(item, dict)
    }
    for reference in references:
        if reference.get("kind") != "mcp":
            continue
        definition_id = str(reference.get("reference_id"))
        digest = str(reference.get("version_or_digest"))
        if pinned.get(definition_id) != digest:
            raise ApiProblem(
                409,
                "mcp_not_in_run_snapshot",
                "진행 중 Run에는 시작할 때 고정된 MCP revision만 사용할 수 있습니다.",
            )


def _validate_reference_shape(
    reference: MessageReferenceInput, *, message_text: str
) -> None:
    if not reference.reference_id or len(reference.reference_id) > 80:
        raise ApiProblem(404, "reference_not_found", "참조 대상을 찾을 수 없습니다.")
    if (
        reference.version_or_digest is not None
        and len(reference.version_or_digest) > 160
    ):
        raise ApiProblem(
            409,
            "reference_version_unavailable",
            "참조 version 또는 digest가 올바르지 않습니다.",
        )
    start = reference.token_start
    end = reference.token_end
    if (start is None) != (end is None):
        raise ApiProblem(
            422,
            "invalid_reference_range",
            "참조 token 범위의 시작과 끝을 함께 지정해 주세요.",
        )
    if (
        start is not None
        and end is not None
        and not (0 <= start < end <= len(message_text))
    ):
        raise ApiProblem(
            422,
            "invalid_reference_range",
            "참조 token 범위가 메시지 본문을 벗어났습니다.",
        )


def _persist_message_references(
    db: Session,
    message: Message,
    references: Iterable[dict[str, Any]],
) -> None:
    actor = db.get(User, message.author_user_id) if message.author_user_id else None
    conversation = db.get(Conversation, message.conversation_id)
    for reference in references:
        token_start = reference.get("token_start")
        token_end = reference.get("token_end")
        display_snapshot = reference.get("display_snapshot")
        db.add(
            MessageReference(
                message_id=message.id,
                kind=str(reference["kind"]),
                reference_id=str(reference["reference_id"]),
                version_or_digest=(
                    str(reference["version_or_digest"])
                    if reference.get("version_or_digest") is not None
                    else None
                ),
                token_start=token_start if isinstance(token_start, int) else -1,
                token_end=token_end if isinstance(token_end, int) else None,
                display_snapshot_json=(
                    display_snapshot if isinstance(display_snapshot, dict) else {}
                ),
                validation_status="valid",
            )
        )
        if (
            actor is not None
            and conversation is not None
            and reference.get("kind") == "file"
            and isinstance(display_snapshot, dict)
            and display_snapshot.get("targetType") == "project_file"
        ):
            record_audit(
                db,
                action="project_file_referenced",
                target_type="project_file",
                target_id=str(reference["reference_id"]),
                result="success",
                actor=actor,
                metadata={
                    "project_id": conversation.project_id,
                    "message_id": message.id,
                    "version_or_digest": reference.get("version_or_digest"),
                },
            )
    db.flush()


def create_run_plan(db: Session, run: Run, *, goal: str) -> Plan:
    existing = db.scalar(select(Plan).where(Plan.run_id == run.id))
    if existing is not None:
        _sync_plan_snapshot(db, run)
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
    snapshot = _sync_plan_snapshot(db, run)
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


def update_work_plan(
    db: Session,
    run: Run,
    *,
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist the model-authored, user-visible work plan for a Run."""
    if not 1 <= len(steps) <= 8:
        raise ValueError("업무 계획은 1개 이상 8개 이하의 단계여야 합니다.")

    previous = run.snapshot_json.get("work_plan", [])
    previous_ids = {
        str(item.get("step", "")).strip().casefold(): str(item.get("id"))
        for item in previous
        if isinstance(item, dict) and item.get("id")
    }
    previous_ids_by_order = {
        int(item.get("order")): str(item.get("id"))
        for item in previous
        if isinstance(item, dict)
        and item.get("id")
        and isinstance(item.get("order"), int)
    }
    previous_phases_by_order = {
        int(item.get("order")): str(item.get("phase"))
        for item in previous
        if isinstance(item, dict)
        and isinstance(item.get("order"), int)
        and item.get("phase") in WORK_PLAN_PHASES
    }
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
            phase = previous_phases_by_order.get(order) or _infer_work_plan_phase(
                label
            )
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
    if active_index is not None and (
        steps[active_index].get("phase")
        or _infer_work_plan_phase(str(steps[active_index].get("step", "")))
    ) == target_phase:
        return None

    target_index = next(
        (
            index
            for index, item in enumerate(steps)
            if item.get("status") != "completed"
            and (
                item.get("phase")
                or _infer_work_plan_phase(str(item.get("step", "")))
            )
            == target_phase
            and (active_index is None or index > active_index)
        ),
        None,
    )
    if target_index is None:
        return None

    changed = False
    for index, item in enumerate(steps):
        current_status = item.get("status")
        if index < target_index:
            next_status = "completed"
        elif index == target_index:
            next_status = "in_progress"
        elif current_status == "in_progress":
            next_status = "pending"
        else:
            next_status = current_status
        if next_status != current_status:
            item["status"] = next_status
            changed = True
    if not changed:
        return None

    run.snapshot_json = {**run.snapshot_json, "work_plan": steps}
    append_event(db, run, "work_plan_updated", {"steps": steps})
    db.flush()
    return steps


def _plan_step_payload(db: Session, step: PlanStep) -> dict[str, Any]:
    return {
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
        "subtasks": list_step_subtasks(db, step.id),
    }


def _sync_plan_snapshot(db: Session, run: Run) -> dict[str, Any]:
    snapshot = plan_snapshot(db, run)
    if snapshot is None:
        raise ApiProblem(409, "plan_missing", "Run의 Plan을 찾을 수 없습니다.")
    encoded_snapshot = jsonable_encoder(snapshot)
    run.snapshot_json = {**run.snapshot_json, "plan": encoded_snapshot}
    return encoded_snapshot


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
    _sync_plan_snapshot(db, run)
    append_event(
        db,
        run,
        "plan_step_changed",
        {
            "planId": plan.id,
            "planStatus": plan.status,
            "step": _plan_step_payload(db, step),
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


def resume_plan(db: Session, run: Run) -> None:
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
        if marker.get("previous_status") == PLAN_STEP_QUEUED
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
    _sync_plan_snapshot(db, run)


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
    run.status = QUEUED
    run.queued_at = utc_now()
    run.finished_at = None
    run.error_code = None
    run.error_message = None
    run.assistant_draft = ""
    run.snapshot_json = {
        **run.snapshot_json,
        "retry": {
            "step_id": step.id,
            "step_key": step.step_key,
            "next_attempt": step.attempt + 1,
            "scheduled_at": utc_now().isoformat(),
        },
    }
    db.flush()
    _sync_plan_snapshot(db, run)
    append_event(
        db,
        run,
        "retry_scheduled",
        {"step": _plan_step_payload(db, step), "status": QUEUED},
    )
    return step


def append_event(
    db: Session, run: Run, event_type: str, payload: dict[str, Any]
) -> RunEvent:
    run.last_sequence += 1
    event = RunEvent(
        run_id=run.id,
        conversation_id=run.conversation_id,
        sequence=run.last_sequence,
        event_type=event_type,
        payload_json=jsonable_encoder(payload),
    )
    db.add(event)
    db.flush()
    return event


def transition_run(
    db: Session, run: Run, target: str, *, event_type: str = "run_status_changed"
) -> RunEvent:
    ensure_transition(run.status, target)
    run.status = target
    now = utc_now()
    if target == "preparing" and run.started_at is None:
        run.started_at = now
    if target in TERMINAL_STATUSES:
        run.finished_at = now
        run.snapshot_json = {**run.snapshot_json, "artifact_progress": None}
    event = append_event(
        db, run, event_type, {"status": target, "finishedAt": run.finished_at}
    )
    create_run_transition_notification(db, run, target)
    return event


def run_for_user(db: Session, user: User, run_id: str, *, write: bool = False) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise ApiProblem(404, "not_found", "Run을 찾을 수 없습니다.")
    require_conversation(db, user, run.conversation_id, write=write)
    return run


def event_response(event: RunEvent) -> dict[str, Any]:
    return {
        "runId": event.run_id,
        "conversationId": event.conversation_id,
        "sequence": event.sequence,
        "type": event.event_type,
        "payload": event.payload_json,
        "createdAt": event.created_at,
    }


def tool_response(tool: ToolExecution) -> dict[str, Any]:
    duration_ms = None
    if tool.started_at and tool.finished_at:
        duration_ms = int((tool.finished_at - tool.started_at).total_seconds() * 1000)
    progress = _write_file_progress(tool.validated_input_json)
    return {
        "id": tool.id,
        "callId": tool.tool_call_id,
        "artifactId": tool.artifact_id,
        "toolName": tool.tool_name,
        "label": tool.tool_name.replace("_", " "),
        "status": tool.status,
        "input": (
            {}
            if "__lumina_stream_tokens" in tool.validated_input_json
            else tool.validated_input_json
        ),
        "result": tool.result_json if tool.status == "completed" else None,
        "inputSummary": (
            ["파일 내용을 생성하고 있습니다."]
            if "__lumina_stream_tokens" in tool.validated_input_json
            else [f"{key}: {value}" for key, value in tool.validated_input_json.items()]
        ),
        "resultSummary": [tool.result_summary] if tool.result_summary else [],
        "startedAt": tool.started_at,
        "completedAt": tool.finished_at,
        "durationMs": duration_ms,
        "progress": progress,
        "error": tool.error_message,
    }


def _write_file_progress(
    arguments: Mapping[str, Any],
) -> dict[str, int | str] | None:
    if "__lumina_stream_tokens" in arguments:
        progress: dict[str, int | str] = {
            "tokens": max(0, int(arguments.get("__lumina_stream_tokens", 0))),
            "lines": max(0, int(arguments.get("__lumina_stream_lines", 0))),
        }
        file_name = arguments.get("__lumina_stream_file_name")
        if isinstance(file_name, str) and file_name.strip():
            progress["fileName"] = file_name.strip()
        return progress
    content = arguments.get("content")
    if not isinstance(content, str):
        return None
    character_count = len(content)
    if character_count == 0:
        return {"tokens": 0, "lines": 0}
    return {
        "tokens": max(1, math.ceil(character_count / 4)),
        "lines": max(1, content.count("\n") + 1),
        **(
            {"fileName": str(arguments["path"]).replace("\\", "/").rsplit("/", 1)[-1]}
            if arguments.get("path")
            else {}
        ),
    }


def message_response(message: Message, db: Session | None = None) -> dict[str, Any]:
    references = message.metadata_json.get("prompt_references", [])
    attachment_ids = message.metadata_json.get("attachment_ids", [])
    attachments = []
    if db is not None and isinstance(attachment_ids, list):
        for attachment_id in dict.fromkeys(attachment_ids):
            attachment = db.get(Attachment, attachment_id)
            if attachment is None or attachment.deleted_at is not None:
                continue
            attachments.append(
                {
                    "id": attachment.id,
                    "conversationId": attachment.conversation_id,
                    "projectId": attachment.project_id,
                    "kind": attachment.kind,
                    "fileName": attachment.original_filename,
                    "mimeType": attachment.sniffed_mime_type,
                    "size": attachment.size_bytes,
                    "status": attachment.status,
                    "extractionStatus": attachment.extraction_status,
                    "metadata": attachment.metadata_json,
                    "createdAt": attachment.created_at,
                }
            )
    return {
        "id": message.id,
        "conversationId": message.conversation_id,
        "runId": message.run_id,
        "role": message.role,
        "text": message.canonical_text,
        "status": message.status,
        "references": references,
        "attachments": attachments,
        "metadata": message.metadata_json,
        "createdAt": message.created_at,
        "completedAt": message.updated_at if message.status == "completed" else None,
    }


def _artifact_usage_snapshot(db: Session, run: Run) -> dict[str, Any] | None:
    usage: object = run.snapshot_json.get("artifact_usage")
    if not isinstance(usage, Mapping):
        latest_progress = db.scalar(
            select(RunEvent)
            .where(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "artifact_progress",
            )
            .order_by(RunEvent.sequence.desc())
            .limit(1)
        )
        usage = latest_progress.payload_json if latest_progress is not None else None
    if not isinstance(usage, Mapping):
        return None
    tokens = usage.get("tokens")
    lines = usage.get("lines")
    if (
        not isinstance(tokens, int)
        or isinstance(tokens, bool)
        or tokens < 0
        or not isinstance(lines, int)
        or isinstance(lines, bool)
        or lines < 0
    ):
        return None
    normalized: dict[str, Any] = {"tokens": tokens, "lines": lines}
    if isinstance(usage.get("estimated"), bool):
        normalized["estimated"] = usage["estimated"]
    target_tokens = usage.get("targetTokens")
    if (
        isinstance(target_tokens, int)
        and not isinstance(target_tokens, bool)
        and target_tokens > 0
    ):
        normalized["targetTokens"] = target_tokens
    return normalized


def run_snapshot(db: Session, run: Run) -> dict[str, Any]:
    conversation = db.get(Conversation, run.conversation_id)
    usage = _usage_snapshot(run)
    artifact_usage = _artifact_usage_snapshot(db, run)
    tools = list(
        db.scalars(
            select(ToolExecution)
            .where(ToolExecution.run_id == run.id)
            .order_by(ToolExecution.created_at, ToolExecution.id)
        )
    )
    tools_by_id = {tool.id: tool for tool in tools}
    activity_events = list(
        db.scalars(
            select(RunEvent)
            .where(
                RunEvent.run_id == run.id,
                RunEvent.event_type.in_(
                    ("progress_summary", "skill_selected", "tool_started")
                ),
            )
            .order_by(RunEvent.sequence)
        )
    )
    activities = _skill_activities(run)
    for event in activity_events:
        if event.event_type == "skill_selected":
            event_activity = event.payload_json.get("activity", {})
            event_activity_id = str(event_activity.get("id", ""))
            activities = [
                {**activity, "sequence": event.sequence}
                if activity.get("id") == event_activity_id
                else activity
                for activity in activities
            ]
            continue
        if event.event_type == "progress_summary":
            activities.append(
                {
                    "id": str(event.payload_json.get("id", event.id)),
                    "type": "progress_summary",
                    "sequence": event.sequence,
                    "text": str(event.payload_json.get("text", "")),
                    "phase": str(event.payload_json.get("phase", "working")),
                    "createdAt": event.created_at,
                }
            )
            continue
        execution = event.payload_json.get("execution", {})
        tool = tools_by_id.get(str(execution.get("id", "")))
        if tool is not None:
            activities.append(
                {
                    "id": f"tool:{tool.id}",
                    "type": "tool",
                    "sequence": event.sequence,
                    "execution": tool_response(tool),
                }
            )
    activities.sort(
        key=lambda activity: (
            int(activity.get("sequence", 0)),
            str(activity.get("id", "")),
        )
    )
    tool_artifact_ids = {
        tool.artifact_id for tool in tools if tool.artifact_id is not None
    }
    artifact_scope = Artifact.source_run_id == run.id
    if tool_artifact_ids:
        artifact_scope = or_(artifact_scope, Artifact.id.in_(tool_artifact_ids))
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(artifact_scope, Artifact.deleted_at.is_(None))
            .order_by(Artifact.created_at, Artifact.id)
        )
    )
    commands = list(
        db.scalars(
            select(RunCommand)
            .where(RunCommand.run_id == run.id)
            .order_by(RunCommand.created_at, RunCommand.id)
        )
    )
    context_compactions = list(
        db.scalars(
            select(CompactedContextEntry)
            .where(CompactedContextEntry.conversation_id == run.conversation_id)
            .order_by(
                CompactedContextEntry.version,
                CompactedContextEntry.compacted_at,
                CompactedContextEntry.id,
            )
        )
    )
    assistant_message_id = run.snapshot_json.get("assistant_message_id")
    execution = run.snapshot_json.get("execution", {})
    return {
        "runId": run.id,
        "conversationId": run.conversation_id,
        "conversationTitle": conversation.title if conversation is not None else None,
        "conversationRevision": conversation.revision
        if conversation is not None
        else None,
        "status": run.status,
        "errorCode": run.error_code,
        "errorMessage": run.error_message,
        "lastSequence": run.last_sequence,
        "startedAt": run.started_at,
        "finishedAt": run.finished_at,
        "assistantDraft": (
            {"messageId": assistant_message_id, "text": run.assistant_draft}
            if assistant_message_id and run.assistant_draft
            else None
        ),
        "artifactProgress": run.snapshot_json.get("artifact_progress"),
        "artifactUsage": artifact_usage,
        "outputIntent": run.snapshot_json.get("output_intent"),
        "workPlan": run.snapshot_json.get("work_plan", []),
        "plan": plan_snapshot(db, run),
        "activities": activities,
        "toolExecutions": [tool_response(tool) for tool in tools],
        "artifacts": [
            artifact_summary(artifact, current_artifact_version(db, artifact))
            for artifact in artifacts
        ],
        "pendingCommands": [
            command_payload(command)
            for command in commands
            if command.status not in {"applied", "cancelled", "failed", "promoted"}
        ],
        "pendingApprovals": pending_approval_payloads(db, run.id),
        "contextCompactions": [
            {
                "id": entry.id,
                "runId": entry.run_id,
                "parentCompactionId": entry.parent_compaction_id,
                "version": entry.version,
                "status": entry.status,
                "summary": entry.summary,
                "sourceMessageIds": entry.source_message_ids_json,
                "sourceMessageRange": entry.source_message_range_json,
                "sourceEventRange": entry.source_event_range_json,
                "sourceRefs": entry.source_refs_json,
                "sourceHash": entry.source_hash,
                "estimatedTokensBefore": entry.estimated_tokens_before,
                "estimatedTokensAfter": entry.estimated_tokens_after,
                "contextWindow": entry.context_window,
                "effectiveInputBudget": entry.effective_input_budget,
                "summaryModel": entry.summary_model,
                "promptVersion": entry.prompt_version,
                "retrievalPolicy": entry.retrieval_policy,
                "accessScope": entry.access_scope,
                "cooldownUntil": entry.cooldown_until,
                "ineffectiveCount": entry.ineffective_count,
                "compactedAt": entry.compacted_at,
            }
            for entry in context_compactions
        ],
        "execution": {
            "providerId": run.provider_id,
            "modelKey": run.model_key,
            "effortId": run.effort,
            "runtimeModelId": run.runtime_model_id,
            "catalogRevision": execution.get("catalog_revision", "unknown"),
        },
        "limits": run.snapshot_json.get("limits", {}),
        "usage": usage,
        "mcpServers": run.snapshot_json.get("mcp_servers", []),
    }


def _usage_snapshot(run: Run) -> dict[str, Any]:
    usage = dict(run.usage_json)
    if "estimated_cost_breakdown_usd" in usage:
        return usage
    breakdown = estimate_model_cost_parts(
        run.provider_id,
        run.model_key,
        input_tokens=_usage_token_count(usage.get("input_tokens")),
        cached_input_tokens=_usage_token_count(usage.get("cached_input_tokens")),
        cache_write_tokens=_usage_token_count(usage.get("cache_write_tokens")),
        output_tokens=_usage_token_count(usage.get("output_tokens")),
    )
    if breakdown is not None:
        usage["estimated_cost_breakdown_usd"] = breakdown
    return usage


def _usage_token_count(value: Any) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def activate_run_skill(
    run: Run,
    *,
    skill_id: str,
    reason: str,
) -> dict[str, Any]:
    """Persist a model-selected Skill in the immutable Run extension snapshot."""
    extensions = [
        item
        for item in run.snapshot_json.get("extensions", [])
        if isinstance(item, dict)
    ]
    selected = next(
        (
            extension
            for extension in extensions
            if str(extension.get("extension_id", "")) == skill_id
        ),
        None,
    )
    if selected is None:
        raise ApiProblem(
            422,
            "skill_not_in_run_snapshot",
            "현재 Run에서 사용할 수 없는 Skill입니다.",
        )

    explicit_ids = {
        str(reference.get("reference_id"))
        for reference in run.snapshot_json.get("prompt_references", [])
        if isinstance(reference, dict) and reference.get("kind") == "skill"
    }
    if (
        run.snapshot_json.get("extension_application") == "all_snapshot"
        or skill_id in explicit_ids
    ):
        return {**selected, "activation_reason": "", "already_active": True}

    selected_ids = [
        str(item)
        for item in run.snapshot_json.get("auto_selected_skill_ids", [])
        if str(item)
    ]
    already_active = skill_id in selected_ids
    if not already_active:
        selected_ids.append(skill_id)
    normalized_reason = " ".join(reason.split())[:160].rstrip()
    reasons = {
        str(key): str(value)
        for key, value in dict(
            run.snapshot_json.get("auto_selected_skill_reasons", {})
        ).items()
        if str(key) and str(value).strip()
    }
    if normalized_reason:
        reasons[skill_id] = normalized_reason
    run.snapshot_json = {
        **run.snapshot_json,
        "extension_application": "explicit_and_auto",
        "auto_selected_skill_ids": selected_ids,
        **({"auto_selected_skill_reasons": reasons} if reasons else {}),
    }
    return {
        **selected,
        "activation_reason": reasons.get(skill_id, ""),
        "already_active": already_active,
    }


def _skill_activities(run: Run) -> list[dict[str, Any]]:
    extensions = [
        item
        for item in run.snapshot_json.get("extensions", [])
        if isinstance(item, dict)
    ]
    application = run.snapshot_json.get("extension_application", "explicit_references")
    explicit_ids = {
        str(reference.get("reference_id"))
        for reference in run.snapshot_json.get("prompt_references", [])
        if isinstance(reference, dict) and reference.get("kind") == "skill"
    }
    auto_ids = {
        str(extension_id)
        for extension_id in run.snapshot_json.get("auto_selected_skill_ids", [])
    }
    auto_reasons = {
        str(key): " ".join(str(value).split())[:160].rstrip()
        for key, value in dict(
            run.snapshot_json.get("auto_selected_skill_reasons", {})
        ).items()
        if str(key) and str(value).strip()
    }
    activities: list[dict[str, Any]] = []
    for extension in extensions:
        extension_id = str(extension.get("extension_id", ""))
        if application == "all_snapshot":
            applied_by = "scheduled"
        elif extension_id in explicit_ids:
            applied_by = "explicit"
        elif extension_id in auto_ids:
            applied_by = "auto"
        else:
            continue
        version_label = (
            f"Draft r{extension['draft_revision']}"
            if extension.get("draft_revision") is not None
            else f"v{extension['version']}"
            if extension.get("version") is not None
            else str(extension.get("digest", ""))[:12]
        )
        if applied_by == "auto" and auto_reasons.get(extension_id):
            reason = auto_reasons[extension_id]
        elif extension.get("slug") == "visual-artifact":
            reason = "보고서 HTML 시각 산출물 제작"
        else:
            description = " ".join(str(extension.get("description", "")).split())
            reason = (
                description[:80].rstrip()
                if description
                else (
                    "예약 작업에 고정된 절차 적용"
                    if applied_by == "scheduled"
                    else "요청에 맞는 작업 절차 적용"
                )
            )
        activities.append(
            {
                "id": f"skill:{extension_id}:{extension.get('digest', '')}",
                "type": "skill",
                "sequence": len(activities) - len(extensions),
                "skillId": extension_id,
                "name": str(extension.get("name", "Skill")),
                "slug": str(extension.get("slug", extension.get("name", "Skill"))),
                "versionLabel": version_label,
                "appliedBy": applied_by,
                "reason": reason,
            }
        )
    return activities


def cancel_organization_work(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: str,
) -> tuple[list[str], int]:
    cancellable_statuses = {*ACTIVE_STATUSES, QUEUED, INTERRUPTED}
    runs = list(
        db.scalars(
            select(Run)
            .where(
                Run.organization_id == organization_id,
                Run.status.in_(cancellable_statuses),
            )
            .order_by(Run.queued_at, Run.id)
        )
    )
    for run in runs:
        _cancel_run_state(
            db,
            run,
            actor_user_id=actor_user_id,
            reason="admin_emergency_stop",
        )

    queued_messages = list(
        db.scalars(
            select(QueuedMessage)
            .join(Conversation, Conversation.id == QueuedMessage.conversation_id)
            .where(
                Conversation.organization_id == organization_id,
                QueuedMessage.status == "queued",
            )
        )
    )
    cancelled_at = utc_now()
    for queued in queued_messages:
        queued.status = "cancelled"
        queued.cancelled_at = cancelled_at
    db.flush()
    return [run.id for run in runs], len(queued_messages)


def _cancel_run_state(
    db: Session,
    run: Run,
    *,
    actor_user_id: str,
    reason: str = "user_cancelled",
) -> None:
    if run.status == CANCELLED:
        return
    pending_approvals = list(
        db.scalars(
            select(ToolApproval).where(
                ToolApproval.run_id == run.id,
                ToolApproval.status == "pending",
            )
        )
    )
    for pending in pending_approvals:
        pending.status = "cancelled"
        pending.resolved_by_user_id = actor_user_id
        pending.resolved_at = utc_now()
        append_event(
            db,
            run,
            "approval_resolved",
            {"approval": approval_payload(pending), "decision": "cancelled"},
        )

    running_tools = list(
        db.scalars(
            select(ToolExecution).where(
                ToolExecution.run_id == run.id,
                ToolExecution.status == "running",
            )
        )
    )
    for tool in running_tools:
        tool.status = "failed"
        tool.error_code = "run_cancelled"
        tool.error_message = "Run이 중단되어 Tool 실행을 종료했습니다."
        tool.finished_at = utc_now()
        append_event(db, run, "tool_completed", {"execution": tool_response(tool)})

    snapshot = dict(run.snapshot_json)
    snapshot.pop("tool_checkpoint", None)
    snapshot["cancelReason"] = reason
    run.snapshot_json = snapshot
    transition_run(db, run, CANCELLED, event_type="run_cancelled")
    cancel_plan(db, run)


def apply_run_action(
    db: Session,
    *,
    user: User,
    run_id: str,
    payload: RunActionRequest,
    idempotency_key: str,
) -> tuple[Run, RunCommand, Message | None, bool]:
    run = run_for_user(db, user, run_id, write=True)
    existing = db.scalar(
        select(RunCommand).where(
            RunCommand.run_id == run.id,
            RunCommand.idempotency_key == idempotency_key,
        )
    )
    if existing:
        message_id = existing.payload_json.get("message_id")
        return run, existing, db.get(Message, message_id) if message_id else None, False

    target_command: RunCommand | None = None
    target_message: Message | None = None
    target_queued_message: QueuedMessage | None = None
    if payload.type in {"steer_queued", "cancel_command"}:
        if payload.command_id is None:
            raise ApiProblem(
                422, "command_id_required", "처리할 대기 요청을 선택해 주세요."
            )
        target_command = db.get(RunCommand, payload.command_id)
        if target_command is None or target_command.run_id != run.id:
            raise ApiProblem(
                404, "run_command_not_found", "대기 요청을 찾을 수 없습니다."
            )
        if target_command.actor_user_id != user.id:
            _require_run_command_actor(db, run=run, user=user)
        if target_command.command_type not in {"steer", "queue_next"} or (
            target_command.status not in {"waiting_safe_boundary", "queued"}
        ):
            raise ApiProblem(
                409,
                "run_command_not_pending",
                "이미 적용되었거나 취소된 요청입니다.",
            )
        if payload.type == "steer_queued" and (
            target_command.command_type != "queue_next"
            or target_command.status != "queued"
        ):
            raise ApiProblem(
                409,
                "queued_command_required",
                "Queue에서 대기 중인 요청만 현재 작업에 반영할 수 있습니다.",
            )
        message_id = target_command.payload_json.get("message_id")
        target_message = db.get(Message, message_id) if message_id else None
        if target_message is None:
            raise ApiProblem(
                409, "run_command_message_missing", "대기 요청의 메시지를 찾을 수 없습니다."
            )
        queued_message_id = target_command.payload_json.get("queued_message_id")
        if queued_message_id:
            target_queued_message = db.get(QueuedMessage, queued_message_id)
        if target_command.command_type == "queue_next" and (
            target_queued_message is None or target_queued_message.status != "queued"
        ):
            raise ApiProblem(
                409, "queued_message_not_pending", "Queue 요청이 더 이상 대기 중이 아닙니다."
            )
        if payload.type == "steer_queued":
            attachment_ids = _validate_attachments(
                db,
                user,
                run.project_id,
                [
                    str(item)
                    for item in target_message.metadata_json.get("attachment_ids", [])
                ],
            )
            references = _validate_references(
                db,
                user,
                run.conversation_id,
                [
                    MessageReferenceInput.model_validate(item)
                    for item in target_message.metadata_json.get("prompt_references", [])
                    if isinstance(item, dict)
                ],
                message_text=target_message.canonical_text,
            )
            _validate_steer_mcp_references(run, references)
            target_message.metadata_json = {
                **target_message.metadata_json,
                "attachment_ids": attachment_ids,
                "prompt_references": references,
            }

    if payload.type == "retry_step":
        _retryable_plan_step(db, run, payload.step_id)
    approval: ToolApproval | None = None
    if payload.type in {"approve", "reject"}:
        if payload.approval_id is None:
            raise ApiProblem(
                422, "approval_id_required", "처리할 Tool 승인 요청을 선택해 주세요."
            )
        approval = db.get(ToolApproval, payload.approval_id)
        if approval is None or approval.run_id != run.id:
            raise ApiProblem(
                404, "approval_not_found", "Tool 승인 요청을 찾을 수 없습니다."
            )
        _require_approval_actor(db, run=run, user=user)
        if run.status != AWAITING_APPROVAL:
            raise ApiProblem(
                409, "approval_not_pending", "현재 Run은 승인 대기 상태가 아닙니다."
            )
        if approval.status != "pending":
            raise ApiProblem(
                409,
                "approval_already_resolved",
                "Tool 승인 요청이 이미 처리되었습니다.",
            )

    canonical_message: dict[str, Any] | None = None
    if payload.type in {"steer", "queue_next"}:
        if payload.message is None:
            raise ApiProblem(422, "message_required", "추가 요청 내용을 입력해 주세요.")
        attachment_ids = _validate_attachments(
            db, user, run.project_id, payload.message.attachment_ids
        )
        references = _validate_references(
            db,
            user,
            run.conversation_id,
            payload.message.prompt_references,
            message_text=payload.message.text,
        )
        if payload.type == "steer":
            _validate_steer_mcp_references(run, references)
        canonical_message = {
            "text": payload.message.text,
            "attachment_ids": attachment_ids,
            "prompt_references": references,
            "output_mode": payload.message.output_mode,
            "target_output_tokens": (
                payload.message.target_output_tokens
                if payload.message.output_mode != "chat"
                else None
            ),
        }

    command_payload_json = payload.model_dump(mode="json", by_alias=False)
    if canonical_message is not None:
        command_payload_json["message"] = canonical_message
    command = RunCommand(
        run_id=run.id,
        actor_user_id=user.id,
        command_type=payload.type,
        idempotency_key=idempotency_key,
        payload_json=command_payload_json,
        status="received",
    )
    db.add(command)
    db.flush()
    message: Message | None = None

    if payload.type in {"steer", "queue_next"}:
        assert payload.message is not None and canonical_message is not None
        attachment_ids = canonical_message["attachment_ids"]
        references = canonical_message["prompt_references"]
        message = Message(
            conversation_id=run.conversation_id,
            run_id=run.id if payload.type == "steer" else None,
            author_user_id=user.id,
            role="user",
            status="pending",
            canonical_text=payload.message.text,
            turn_index=run.current_turn + 1,
            metadata_json={
                "command_type": payload.type,
                "command_status": (
                    "waiting_safe_boundary" if payload.type == "steer" else "queued"
                ),
                "attachment_ids": attachment_ids,
                "prompt_references": references,
                "output_mode": payload.message.output_mode,
                "target_output_tokens": canonical_message["target_output_tokens"],
            },
        )
        db.add(message)
        db.flush()
        _persist_message_references(db, message, references)
        command.payload_json = {**command.payload_json, "message_id": message.id}
        if payload.type == "steer":
            run.snapshot_json = {
                **run.snapshot_json,
                "pending_steers": [
                    *run.snapshot_json.get("pending_steers", []),
                    {
                        "message_id": message.id,
                        "text": message.canonical_text,
                        "attachment_ids": attachment_ids,
                        "prompt_references": references,
                        "target_output_tokens": canonical_message[
                            "target_output_tokens"
                        ],
                    },
                ],
            }
            command.status = "waiting_safe_boundary"
            append_event(
                db, run, "steer_received", {"command": command_payload(command)}
            )
            append_event(
                db,
                run,
                "steer_waiting_safe_boundary",
                {"command": command_payload(command)},
            )
        else:
            position = (
                db.scalar(
                    select(func.max(QueuedMessage.position)).where(
                        QueuedMessage.conversation_id == run.conversation_id,
                        QueuedMessage.status == "queued",
                    )
                )
                or 0
            ) + 1
            queued = QueuedMessage(
                conversation_id=run.conversation_id,
                user_id=user.id,
                position=position,
                message_text=payload.message.text,
                prompt_references_json=references,
                attachment_ids_json=attachment_ids,
                execution_options_json={
                    **run.snapshot_json.get("execution", {}),
                    "output_mode": payload.message.output_mode,
                    "target_output_tokens": canonical_message["target_output_tokens"],
                },
                idempotency_key=idempotency_key,
            )
            db.add(queued)
            db.flush()
            command.status = "queued"
            command.payload_json = {
                **command.payload_json,
                "queue_position": position,
                "queued_message_id": queued.id,
            }
            append_event(
                db, run, "queued_message_added", {"command": command_payload(command)}
            )
    elif payload.type in {"steer_queued", "cancel_command"}:
        assert target_command is not None and target_message is not None
        now = utc_now()
        if payload.type == "steer_queued":
            assert target_queued_message is not None
            target_queued_message.status = "cancelled"
            target_queued_message.cancelled_at = now
            target_payload = {
                **target_command.payload_json,
                "type": "steer",
                "converted_from_queue": True,
                "source_queued_message_id": target_queued_message.id,
            }
            target_payload.pop("queue_position", None)
            target_payload.pop("queued_message_id", None)
            target_command.command_type = "steer"
            target_command.status = "waiting_safe_boundary"
            target_command.payload_json = target_payload
            target_command.cancelled_at = None
            target_message.run_id = run.id
            target_message.status = "pending"
            target_message.metadata_json = {
                **target_message.metadata_json,
                "command_type": "steer",
                "command_status": "waiting_safe_boundary",
            }
            pending_steers = [
                item
                for item in run.snapshot_json.get("pending_steers", [])
                if item.get("message_id") != target_message.id
            ]
            run.snapshot_json = {
                **run.snapshot_json,
                "pending_steers": [
                    *pending_steers,
                    {
                        "message_id": target_message.id,
                        "text": target_message.canonical_text,
                        "attachment_ids": target_message.metadata_json.get(
                            "attachment_ids", []
                        ),
                        "prompt_references": target_message.metadata_json.get(
                            "prompt_references", []
                        ),
                        "target_output_tokens": target_message.metadata_json.get(
                            "target_output_tokens"
                        ),
                    },
                ],
            }
            append_event(
                db,
                run,
                "steer_received",
                {"command": command_payload(target_command)},
            )
            append_event(
                db,
                run,
                "steer_waiting_safe_boundary",
                {"command": command_payload(target_command)},
            )
            message = target_message
        else:
            target_command.status = "cancelled"
            target_command.cancelled_at = now
            target_message.status = "interrupted"
            target_message.metadata_json = {
                **target_message.metadata_json,
                "command_status": "cancelled",
            }
            if target_command.command_type == "queue_next":
                assert target_queued_message is not None
                target_queued_message.status = "cancelled"
                target_queued_message.cancelled_at = now
                event_type = "queued_message_cancelled"
            else:
                run.snapshot_json = {
                    **run.snapshot_json,
                    "pending_steers": [
                        item
                        for item in run.snapshot_json.get("pending_steers", [])
                        if item.get("message_id") != target_message.id
                    ],
                }
                event_type = "steer_cancelled"
            append_event(
                db,
                run,
                event_type,
                {"command": command_payload(target_command)},
            )
        for repositioned in _resequence_queued_commands(db, run):
            append_event(
                db,
                run,
                "queued_message_added",
                {"command": command_payload(repositioned)},
            )
        command.status = "applied"
        command.applied_at = now
        command.payload_json = {
            **command.payload_json,
            "target_command_id": target_command.id,
        }
    elif payload.type == "pause":
        if run.status == AWAITING_APPROVAL:
            raise ApiProblem(
                409,
                "approval_waiting",
                "승인 대기 중인 Run은 이미 안전하게 정지되어 있습니다.",
            )
        if run.status not in ACTIVE_STATUSES - {PAUSED}:
            raise ApiProblem(
                409, "run_not_active", "현재 Run은 일시 정지할 수 없습니다."
            )
        run.snapshot_json = {**run.snapshot_json, "resume_status": run.status}
        transition_run(db, run, PAUSED)
        pause_plan(db, run)
        command.status = "applied"
        command.applied_at = utc_now()
    elif payload.type == "resume":
        if run.status != PAUSED:
            raise ApiProblem(
                409, "run_not_paused", "현재 Run은 일시 정지 상태가 아닙니다."
            )
        target = run.snapshot_json.get("resume_status", MODEL_STREAMING)
        transition_run(db, run, target)
        resume_plan(db, run)
        command.status = "applied"
        command.applied_at = utc_now()
    elif payload.type == "cancel":
        if run.status in TERMINAL_STATUSES:
            command.status = "applied"
        else:
            _cancel_run_state(db, run, actor_user_id=user.id)
            command.status = "applied"
        command.applied_at = utc_now()
    elif payload.type == "retry_step":
        step = retry_plan_step(db, run, payload.step_id)
        command.status = "applied"
        command.applied_at = utc_now()
        command.payload_json = {
            **command.payload_json,
            "step_id": step.id,
            "step_key": step.step_key,
        }
    elif payload.type in {"approve", "reject"}:
        assert approval is not None
        decision = "approved" if payload.type == "approve" else "rejected"
        resolved_at = utc_now()
        result = db.execute(
            update(ToolApproval)
            .where(ToolApproval.id == approval.id, ToolApproval.status == "pending")
            .values(
                status=decision,
                resolved_by_user_id=user.id,
                resolution_note=payload.note,
                resolved_at=resolved_at,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", 0) != 1:
            raise ApiProblem(
                409,
                "approval_already_resolved",
                "Tool 승인 요청이 이미 처리되었습니다.",
            )
        db.expire(approval)
        db.refresh(approval)
        command.status = "applied"
        command.applied_at = resolved_at
        command.payload_json = {
            **command.payload_json,
            "approval_id": approval.id,
            "decision": decision,
        }
        append_event(
            db,
            run,
            "approval_resolved",
            {
                "approval": approval_payload(approval),
                "decision": decision,
                "command": command_payload(command),
            },
        )
        record_audit(
            db,
            actor=user,
            action=f"tool_approval_{decision}",
            target_type="tool_approval",
            target_id=approval.id,
            result="success",
            reason=decision,
            metadata={
                "run_id": run.id,
                "tool_name": approval.tool_name,
                "effect": approval.effect,
                "risk_level": approval.risk_level,
                "argument_digest": approval.argument_digest,
            },
        )
        remaining = (
            db.scalar(
                select(func.count(ToolApproval.id)).where(
                    ToolApproval.run_id == run.id,
                    ToolApproval.status == "pending",
                )
            )
            or 0
        )
        if remaining == 0:
            change_plan_step(
                db,
                run,
                "tools",
                status=PLAN_STEP_QUEUED,
                reason="tool_approvals_resolved",
            )
            run.queued_at = resolved_at
            transition_run(db, run, QUEUED)
    else:
        raise ApiProblem(
            409, "step_retry_unavailable", "재실행할 Plan Step이 없습니다."
        )

    db.flush()
    return run, command, message, True


def command_payload(command: RunCommand) -> dict[str, Any]:
    message = command.payload_json.get("message")
    return {
        "id": command.id,
        "type": command.command_type,
        "status": command.status,
        "messageId": command.payload_json.get("message_id"),
        "messageText": message.get("text") if isinstance(message, dict) else None,
        "queuePosition": command.payload_json.get("queue_position"),
        "stepId": command.payload_json.get("step_id"),
        "approvalId": command.payload_json.get("approval_id"),
        "createdAt": command.created_at,
    }


def _resequence_queued_commands(db: Session, run: Run) -> list[RunCommand]:
    queued_messages = list(
        db.scalars(
            select(QueuedMessage)
            .where(
                QueuedMessage.conversation_id == run.conversation_id,
                QueuedMessage.status == "queued",
            )
            .order_by(
                QueuedMessage.position,
                QueuedMessage.created_at,
                QueuedMessage.id,
            )
        )
    )
    positions: dict[str, int] = {}
    for position, queued_message in enumerate(queued_messages, start=1):
        queued_message.position = position
        positions[queued_message.id] = position
    changed: list[RunCommand] = []
    commands = list(
        db.scalars(
            select(RunCommand).where(
                RunCommand.run_id == run.id,
                RunCommand.command_type == "queue_next",
                RunCommand.status == "queued",
            )
        )
    )
    for queued_command in commands:
        queued_message_id = queued_command.payload_json.get("queued_message_id")
        position = positions.get(str(queued_message_id))
        if position is None or queued_command.payload_json.get("queue_position") == position:
            continue
        queued_command.payload_json = {
            **queued_command.payload_json,
            "queue_position": position,
        }
        changed.append(queued_command)
    return changed


def _require_run_command_actor(db: Session, *, run: Run, user: User) -> None:
    if user.id == run.user_id or user.role == "admin":
        return
    project = db.get(Project, run.project_id)
    if project is None:
        raise ApiProblem(404, "not_found", "프로젝트를 찾을 수 없습니다.")
    if effective_project_role(db, user=user, project=project) not in {"owner", "admin"}:
        raise ApiProblem(
            403,
            "run_command_forbidden",
            "다른 사용자의 요청은 Project owner/admin만 변경할 수 있습니다.",
        )


def _require_approval_actor(db: Session, *, run: Run, user: User) -> None:
    if user.id == run.user_id or user.role == "admin":
        return
    project = db.get(Project, run.project_id)
    if project is None:
        raise ApiProblem(404, "not_found", "프로젝트를 찾을 수 없습니다.")
    if effective_project_role(db, user=user, project=project) not in {"owner", "admin"}:
        raise ApiProblem(
            403,
            "approval_forbidden",
            "Run 소유자 또는 Project owner/admin만 위험 작업을 승인할 수 있습니다.",
        )
