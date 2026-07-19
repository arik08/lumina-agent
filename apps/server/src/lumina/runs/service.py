from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..agent_frontends import agent_frontend_payload, normalize_agent_frontend_payload
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
from ..knowledge.context import build_project_knowledge_context_snapshot
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
from .events import append_event
from .plans import (
    PLAN_STEP_QUEUED,
    _retryable_plan_step,
    align_work_plan_for_tool_start,
    cancel_plan,
    change_plan_step,
    complete_plan_step,
    create_run_plan,
    fail_plan,
    pause_plan,
    plan_snapshot,
    resume_plan,
    retry_plan_step,
    start_plan_step,
    update_work_plan,
)
from .safety import run_limit_snapshot
from .state import (
    ACTIVE_STATUSES,
    AWAITING_APPROVAL,
    AWAITING_INPUT,
    CANCELLED,
    COMPLETED,
    INTERRUPTED,
    MODEL_STREAMING,
    PAUSED,
    QUEUED,
    TERMINAL_STATUSES,
    ensure_transition,
)


__all__ = (
    "align_work_plan_for_tool_start",
    "append_event",
    "cancel_plan",
    "change_plan_step",
    "complete_plan_step",
    "create_run_plan",
    "fail_plan",
    "pause_plan",
    "plan_snapshot",
    "resume_plan",
    "retry_plan_step",
    "start_plan_step",
    "update_work_plan",
)


UNTITLED_CONVERSATION_TITLES = {"제목 없음", "새 작업"}
CONVERSATION_TITLE_MAX_LENGTH = 60


def _conversation_title_from_message(message_text: str) -> str:
    normalized = " ".join(message_text.split())
    if len(normalized) <= CONVERSATION_TITLE_MAX_LENGTH:
        return normalized
    return normalized[: CONVERSATION_TITLE_MAX_LENGTH - 1].rstrip() + "…"


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
    use_extension_snapshot_candidates: bool = False,
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
    clarification_mode = _clarification_mode(db, user.id)
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
    knowledge_context = build_project_knowledge_context_snapshot(
        db,
        project=project,
        owner_user_id=user.id,
        query=payload.message.text,
    )
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
        "snapshot_candidates"
        if use_extension_snapshot_candidates
        else "explicit_references"
    )
    agent_snapshot = agent_frontend_payload(
        conversation.agent_id, conversation.agent_version
    )
    stable_prefix = {
        "contract_version": "lumina-run-v1",
        "agent": agent_snapshot,
        "project": {
            "id": project.id,
            "concept": project.concept,
            "concept_revision": project.concept_revision,
            "concept_hash": project.concept_hash,
            "updated_at": project.updated_at.isoformat(),
        },
        "execution": execution,
        "output_mode": payload.message.output_mode,
        "analysis_depth": payload.message.analysis_depth,
        "answer_length": payload.message.answer_length,
        "instructions": instruction_snapshot,
        **({"knowledge_context": knowledge_context} if knowledge_context else {}),
        "runtime_prompts": runtime_prompts,
        "extensions": extensions,
        "extension_application": extension_application,
        "environment_type": "local_worker",
        "approval_mode": "on_risk",
        "clarification_mode": clarification_mode,
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
            "analysis_depth": payload.message.analysis_depth,
            "answer_length": payload.message.answer_length,
            "target_output_tokens": target_output_tokens,
            "agent": agent_snapshot,
            "project": stable_prefix["project"],
            "instructions": instruction_snapshot,
            **({"knowledge_context": knowledge_context} if knowledge_context else {}),
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
            "clarification_mode": clarification_mode,
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
            "analysis_depth": payload.message.analysis_depth,
            "answer_length": payload.message.answer_length,
            "target_output_tokens": target_output_tokens,
        },
    )
    db.add(message)
    db.flush()
    run.snapshot_json = {**run.snapshot_json, "user_message_id": message.id}
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


def _clarification_mode(db: Session, user_id: str) -> str:
    setting = db.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user_id,
            UserSetting.key == "agent.clarification_mode",
        )
    )
    mode = setting.value_json if setting is not None else "balanced"
    return mode if mode in {"autonomous", "balanced", "confirming"} else "balanced"


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
                ).tuples()
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


def transition_run(
    db: Session, run: Run, target: str, *, event_type: str = "run_status_changed"
) -> RunEvent:
    ensure_transition(run.status, target)
    if target == COMPLETED:
        work_plan = run.snapshot_json.get("work_plan", [])
        if isinstance(work_plan, list) and any(
            isinstance(item, dict) and item.get("status") != "completed"
            for item in work_plan
        ):
            completed_work_plan = [
                {**item, "status": "completed"} if isinstance(item, dict) else item
                for item in work_plan
            ]
            run.snapshot_json = {
                **run.snapshot_json,
                "work_plan": completed_work_plan,
            }
            append_event(
                db,
                run,
                "work_plan_updated",
                {"steps": completed_work_plan},
            )
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


def tool_display_name(tool_name: str) -> str:
    """Keep the visible tool name identical across events and snapshots."""
    return tool_name


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
        "label": tool_display_name(tool.tool_name),
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
                    (
                        "progress_summary",
                        "skill_selected",
                        "tool_started",
                        "input_requested",
                    )
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
        if event.event_type == "input_requested":
            requested = event.payload_json.get("request", {})
            request_id = str(requested.get("id", ""))
            current_request = next(
                (
                    item
                    for item in run.snapshot_json.get("input_requests", [])
                    if isinstance(item, dict) and str(item.get("id", "")) == request_id
                ),
                requested,
            )
            activities.append(
                {
                    "id": f"input:{request_id or event.id}",
                    "type": "input_request",
                    "sequence": event.sequence,
                    "request": current_request,
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
    agent_snapshot = normalize_agent_frontend_payload(
        run.snapshot_json.get("agent"),
        agent_id=conversation.agent_id if conversation is not None else "general",
        agent_version=conversation.agent_version if conversation is not None else "1",
    )
    return {
        "runId": run.id,
        "conversationId": run.conversation_id,
        "conversationTitle": conversation.title if conversation is not None else None,
        "conversationRevision": conversation.revision
        if conversation is not None
        else None,
        "agent": agent_snapshot,
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
        "inputRequests": run.snapshot_json.get("input_requests", []),
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
        "modelTurnMetrics": run.snapshot_json.get("model_turn_metrics", []),
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
    snapshot["input_requests"] = [
        {
            **item,
            "status": "cancelled" if item.get("status") == "pending" else item.get("status"),
            "cancelledAt": utc_now().isoformat() if item.get("status") == "pending" else item.get("cancelledAt"),
        }
        for item in snapshot.get("input_requests", [])
        if isinstance(item, dict)
    ]
    snapshot.pop("tool_checkpoint", None)
    snapshot["cancelReason"] = reason
    run.snapshot_json = snapshot
    transition_run(db, run, CANCELLED, event_type="run_cancelled")
    cancel_plan(db, run)


def _input_request(run: Run, request_id: str | None) -> dict[str, Any]:
    if not request_id:
        raise ApiProblem(422, "input_request_id_required", "답변할 확인 질문을 선택해 주세요.")
    request = next(
        (
            item
            for item in run.snapshot_json.get("input_requests", [])
            if isinstance(item, dict) and item.get("id") == request_id
        ),
        None,
    )
    if request is None:
        raise ApiProblem(404, "input_request_not_found", "확인 질문을 찾을 수 없습니다.")
    if request.get("status") != "pending" or run.status != AWAITING_INPUT:
        raise ApiProblem(409, "input_request_not_pending", "이미 답변했거나 종료된 확인 질문입니다.")
    return request


def _normalized_user_input_answers(
    request: Mapping[str, Any], answers: Iterable[Any]
) -> list[dict[str, Any]]:
    questions = {
        str(question.get("id")): question
        for question in request.get("questions", [])
        if isinstance(question, dict) and question.get("id")
    }
    answer_items = list(answers)
    supplied = {answer.question_id: answer for answer in answer_items}
    if len(supplied) != len(answer_items):
        raise ApiProblem(422, "input_answer_duplicate", "같은 질문에는 한 번만 답변해 주세요.")
    if set(supplied) != set(questions):
        raise ApiProblem(422, "input_answers_incomplete", "모든 확인 질문에 답변해 주세요.")
    normalized: list[dict[str, Any]] = []
    for question_id, question in questions.items():
        answer = supplied[question_id]
        selected_count = sum(
            (
                bool(answer.option_id),
                bool(answer.custom_text and answer.custom_text.strip()),
                answer.use_ai_judgment,
            )
        )
        if selected_count != 1:
            raise ApiProblem(422, "input_answer_invalid", "각 질문에는 하나의 답변만 선택해 주세요.")
        if answer.use_ai_judgment:
            normalized.append(
                {"questionId": question_id, "kind": "ai", "text": "AI가 판단"}
            )
            continue
        if answer.custom_text and answer.custom_text.strip():
            normalized.append(
                {
                    "questionId": question_id,
                    "kind": "custom",
                    "text": answer.custom_text.strip(),
                }
            )
            continue
        option = next(
            (
                item
                for item in question.get("options", [])
                if isinstance(item, dict) and item.get("id") == answer.option_id
            ),
            None,
        )
        if option is None:
            raise ApiProblem(422, "input_option_invalid", "선택한 답변 항목을 사용할 수 없습니다.")
        normalized.append(
            {
                "questionId": question_id,
                "kind": "option",
                "optionId": answer.option_id,
                "text": str(option.get("label", "")),
            }
        )
    return normalized


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
    input_request: dict[str, Any] | None = None
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
    if payload.type == "submit_user_input":
        input_request = _input_request(run, payload.input_request_id)
        _require_approval_actor(db, run=run, user=user)

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
            "analysis_depth": payload.message.analysis_depth,
            "answer_length": payload.message.answer_length,
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
                "analysis_depth": payload.message.analysis_depth,
                "answer_length": payload.message.answer_length,
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
                        "analysis_depth": canonical_message["analysis_depth"],
                        "answer_length": canonical_message["answer_length"],
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
                    "analysis_depth": canonical_message["analysis_depth"],
                    "answer_length": canonical_message["answer_length"],
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
                        "analysis_depth": target_message.metadata_json.get(
                            "analysis_depth", "auto"
                        ),
                        "answer_length": target_message.metadata_json.get(
                            "answer_length", "auto"
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
    elif payload.type == "submit_user_input":
        assert input_request is not None
        normalized_answers = _normalized_user_input_answers(input_request, payload.answers)
        resolved_at = utc_now()
        resolved_request = {
            **input_request,
            "status": "submitted",
            "answers": normalized_answers,
            "answeredAt": resolved_at.isoformat(),
            "answeredByUserId": user.id,
        }
        requests = [
            resolved_request if item.get("id") == input_request["id"] else item
            for item in run.snapshot_json.get("input_requests", [])
            if isinstance(item, dict)
        ]
        run.snapshot_json = {**run.snapshot_json, "input_requests": requests}
        command.status = "applied"
        command.applied_at = resolved_at
        command.payload_json = {
            **command.payload_json,
            "input_request_id": input_request["id"],
            "answers": normalized_answers,
        }
        append_event(
            db,
            run,
            "input_submitted",
            {"request": resolved_request, "command": command_payload(command)},
        )
        run.queued_at = resolved_at
        transition_run(db, run, QUEUED)
    elif payload.type == "pause":
        if run.status in {AWAITING_APPROVAL, AWAITING_INPUT}:
            raise ApiProblem(
                409,
                "user_response_waiting",
                "사용자 응답을 기다리는 Run은 이미 안전하게 정지되어 있습니다.",
            )
        if run.status not in (ACTIVE_STATUSES - {PAUSED}) | {QUEUED}:
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
        "inputRequestId": command.payload_json.get("input_request_id"),
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
    for queue_position, queued_message in enumerate(queued_messages, start=1):
        queued_message.position = queue_position
        positions[queued_message.id] = queue_position
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
        resolved_position = positions.get(str(queued_message_id))
        if (
            resolved_position is None
            or queued_command.payload_json.get("queue_position") == resolved_position
        ):
            continue
        queued_command.payload_json = {
            **queued_command.payload_json,
            "queue_position": resolved_position,
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
