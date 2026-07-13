from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..artifacts.service import (
    create_artifact,
    create_binary_artifact_version,
    require_artifact,
)
from ..attachments import sniff_mime
from ..authorization import require_conversation
from ..image_formats import IMAGE_FORMAT_BY_MIME, IMAGE_MIME_BY_FORMAT
from ..models import Attachment, Run, User, utc_now
from ..providers.codex import GeneratedImage, ImageGenerationRequest
from ..storage import ManagedLocalStorage, StorageError


GENERATE_IMAGE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Generate one managed image Artifact for the current Project. "
            "Image references and edits are not supported in this release."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "minLength": 1, "maxLength": 32000},
                "reference_attachment_ids": {
                    "type": "array",
                    "maxItems": 8,
                    "items": {"type": "string", "minLength": 1, "maxLength": 64},
                },
                "size": {
                    "type": "string",
                    "pattern": r"^(auto|[0-9]{3,4}x[0-9]{3,4})$",
                    "default": "auto",
                },
                "quality": {
                    "type": "string",
                    "enum": ["auto", "low", "medium", "high"],
                    "default": "auto",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["png", "jpeg", "webp"],
                    "default": "png",
                },
                "background": {
                    "type": "string",
                    "enum": ["auto", "opaque", "transparent"],
                    "default": "auto",
                },
                "destination_project_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                },
                "destination_artifact_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
}

_SIZE = re.compile(r"^(\d{3,4})x(\d{3,4})$")


class ImageToolError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str = "validation",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class GenerateImageInput:
    prompt: str
    reference_attachment_ids: tuple[str, ...]
    size: str
    quality: str
    output_format: str
    background: str
    destination_project_id: str | None
    destination_artifact_id: str | None

    @property
    def prompt_hash(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedImageTool:
    run_id: str
    user_id: str
    project_id: str
    conversation_id: str
    tool_call_id: str
    requested_provider: str
    requested_model: str
    image_backend_model: str
    input: GenerateImageInput
    destination_base_version: int | None

    def provider_request(self) -> ImageGenerationRequest:
        return ImageGenerationRequest(
            model=self.requested_model,
            image_model=self.image_backend_model,
            prompt=self.input.prompt,
            size=self.input.size,
            quality=self.input.quality,
            output_format=self.input.output_format,
            background=self.input.background,
        )


@dataclass(frozen=True, slots=True)
class PersistedImage:
    artifact_id: str
    version: int
    display_name: str
    mime_type: str
    content_hash: str
    validation_status: str
    preview_url: str
    metadata: dict[str, Any]

    def tool_result(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "version": self.version,
            "preview_url": self.preview_url,
            "display_name": self.display_name,
            "mime_type": self.mime_type,
            "content_hash": self.content_hash,
            "validation_status": self.validation_status,
            "metadata": self.metadata,
        }


def parse_generate_image_input(arguments: dict[str, Any]) -> GenerateImageInput:
    prompt = arguments.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ImageToolError(
            "image_prompt_required", "이미지 생성 prompt가 필요합니다."
        )
    prompt = prompt.strip()
    if len(prompt) > 32_000:
        raise ImageToolError(
            "image_prompt_too_long", "이미지 생성 prompt가 너무 깁니다."
        )

    raw_references = arguments.get("reference_attachment_ids", [])
    if not isinstance(raw_references, list) or len(raw_references) > 8:
        raise ImageToolError(
            "invalid_image_references", "참조 이미지 ID 목록을 확인해 주세요."
        )
    references: list[str] = []
    for raw_id in raw_references:
        if not isinstance(raw_id, str) or not raw_id.strip() or len(raw_id) > 64:
            raise ImageToolError(
                "invalid_image_references", "참조 이미지 ID 목록을 확인해 주세요."
            )
        normalized = raw_id.strip()
        if normalized not in references:
            references.append(normalized)

    size = _option(arguments, "size", "auto", None)
    _validate_size(size)
    quality = _option(arguments, "quality", "auto", {"auto", "low", "medium", "high"})
    output_format = _option(
        arguments, "output_format", "png", set(IMAGE_MIME_BY_FORMAT)
    )
    background = _option(
        arguments,
        "background",
        "auto",
        {"auto", "opaque", "transparent"},
    )
    if background == "transparent" and output_format == "jpeg":
        raise ImageToolError(
            "transparent_jpeg_unsupported",
            "투명 배경은 PNG 또는 WebP 형식에서만 사용할 수 있습니다.",
        )

    return GenerateImageInput(
        prompt=prompt,
        reference_attachment_ids=tuple(references),
        size=size,
        quality=quality,
        output_format=output_format,
        background=background,
        destination_project_id=_optional_id(arguments, "destination_project_id"),
        destination_artifact_id=_optional_id(arguments, "destination_artifact_id"),
    )


def redacted_generate_image_input(arguments: dict[str, Any]) -> dict[str, Any]:
    prompt = arguments.get("prompt")
    prompt_text = prompt if isinstance(prompt, str) else ""
    references = arguments.get("reference_attachment_ids")
    return {
        "prompt_hash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "prompt_length": len(prompt_text),
        "reference_attachment_ids": (
            [str(value)[:64] for value in references[:8]]
            if isinstance(references, list)
            else []
        ),
        "size": str(arguments.get("size", "auto"))[:32],
        "quality": str(arguments.get("quality", "auto"))[:16],
        "output_format": str(arguments.get("output_format", "png"))[:16],
        "background": str(arguments.get("background", "auto"))[:16],
        "destination_project_id": str(arguments.get("destination_project_id", ""))[:64]
        or None,
        "destination_artifact_id": str(arguments.get("destination_artifact_id", ""))[
            :64
        ]
        or None,
    }


def prepare_image_tool(
    db: Session,
    file_storage: ManagedLocalStorage,
    *,
    run_id: str,
    tool_call_id: str,
    arguments: dict[str, Any],
) -> PreparedImageTool:
    run = db.get(Run, run_id)
    user = db.get(User, run.user_id) if run is not None else None
    if run is None or user is None:
        raise ImageToolError(
            "run_context_missing",
            "Run Context를 찾을 수 없습니다.",
            stage="dispatch",
        )
    capabilities = run.snapshot_json.get("execution", {}).get("capabilities", {})
    if run.provider_id != "codex":
        raise ImageToolError(
            "codex_provider_required",
            "이미지 생성은 Codex Provider Run에서만 사용할 수 있습니다.",
            stage="capability",
        )
    if not isinstance(capabilities, dict) or not capabilities.get("image_generation"):
        raise ImageToolError(
            "image_generation_unavailable",
            "현재 Codex 모델은 이미지 생성 capability가 없습니다.",
            stage="capability",
        )
    image_backend_model = run.snapshot_json.get("execution", {}).get(
        "image_backend_model"
    )
    if not isinstance(image_backend_model, str) or not image_backend_model:
        raise ImageToolError(
            "image_backend_unpinned",
            "Run에 이미지 생성 backend model이 고정되어 있지 않습니다.",
            stage="capability",
        )

    parsed = parse_generate_image_input(arguments)
    if (
        image_backend_model in {"gpt-image-2", "gpt-image-2-2026-04-21"}
        and parsed.background == "transparent"
    ):
        raise ImageToolError(
            "transparent_background_unsupported",
            "현재 고정된 GPT Image 2 backend는 투명 배경을 지원하지 않습니다.",
            stage="capability",
        )
    if parsed.destination_project_id not in {None, run.project_id}:
        raise ImageToolError(
            "cross_project_image_destination",
            "이미지는 현재 Run의 Project에만 저장할 수 있습니다.",
            stage="authorization",
        )
    _validate_reference_attachments(
        db,
        file_storage,
        user=user,
        run=run,
        attachment_ids=parsed.reference_attachment_ids,
    )
    if parsed.reference_attachment_ids:
        raise ImageToolError(
            "image_reference_unsupported",
            "현재 Codex 이미지 endpoint에서는 참조 이미지 편집을 지원하지 않습니다.",
            stage="capability",
        )

    destination_base_version: int | None = None
    if parsed.destination_artifact_id:
        try:
            artifact = require_artifact(
                db, user, parsed.destination_artifact_id, write=True
            )
        except ApiProblem as exc:
            raise ImageToolError(
                "image_destination_unavailable",
                "대상 이미지 Artifact를 사용할 수 없습니다.",
                stage="authorization",
            ) from exc
        if artifact.project_id != run.project_id or not artifact.mime_type.startswith(
            "image/"
        ):
            raise ImageToolError(
                "image_destination_unavailable",
                "대상 이미지 Artifact를 사용할 수 없습니다.",
                stage="authorization",
            )
        expected_mime = IMAGE_MIME_BY_FORMAT[parsed.output_format]
        if artifact.mime_type != expected_mime:
            raise ImageToolError(
                "image_destination_format_conflict",
                "대상 Artifact와 요청한 이미지 형식이 다릅니다.",
            )
        destination_base_version = artifact.current_version_number
        if destination_base_version is None:
            raise ImageToolError(
                "image_destination_unavailable",
                "대상 이미지 Artifact의 기준 버전을 찾을 수 없습니다.",
            )

    return PreparedImageTool(
        run_id=run.id,
        user_id=user.id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        tool_call_id=tool_call_id,
        requested_provider=run.provider_id,
        requested_model=run.runtime_model_id,
        image_backend_model=image_backend_model,
        input=parsed,
        destination_base_version=destination_base_version,
    )


def persist_generated_image(
    db: Session,
    artifact_storage: ManagedLocalStorage,
    *,
    prepared: PreparedImageTool,
    generated: GeneratedImage,
) -> PersistedImage:
    run = db.get(Run, prepared.run_id)
    user = db.get(User, prepared.user_id)
    if run is None or user is None:
        raise ImageToolError(
            "run_context_missing",
            "Run Context를 찾을 수 없습니다.",
            stage="storage",
        )
    if (
        run.provider_id != prepared.requested_provider
        or run.runtime_model_id != prepared.requested_model
    ):
        raise ImageToolError(
            "run_execution_changed",
            "Run의 Provider 또는 Model snapshot이 변경되었습니다.",
            stage="storage",
        )
    actual_format = IMAGE_FORMAT_BY_MIME.get(generated.mime_type)
    if actual_format is None:
        raise ImageToolError("invalid_image_mime", "지원하지 않는 이미지 형식입니다.")

    generated_at = utc_now()
    content_hash = hashlib.sha256(generated.content).hexdigest()
    actual_model = (
        generated.actual_model
        if generated.actual_model_reported
        else prepared.image_backend_model
    )
    generation_metadata: dict[str, Any] = {
        "sourceRunId": run.id,
        "sourceToolCallId": prepared.tool_call_id,
        "requestedProvider": prepared.requested_provider,
        "requestedModel": prepared.requested_model,
        "requestedImageBackendModel": prepared.image_backend_model,
        "actualBackend": generated.actual_backend,
        "actualModel": actual_model,
        "actualModelSource": (
            "api_response"
            if generated.actual_model_reported
            else "pinned_request_contract"
        ),
        "responseModel": generated.response_model,
        "promptHash": prepared.input.prompt_hash,
        "promptLength": len(prepared.input.prompt),
        "revisedPromptHash": generated.revised_prompt_hash,
        "size": prepared.input.size,
        "quality": prepared.input.quality,
        "requestedFormat": prepared.input.output_format,
        "actualFormat": actual_format,
        "background": prepared.input.background,
        "referenceAttachmentIds": list(prepared.input.reference_attachment_ids),
        "contentHash": content_hash,
        "createdAt": generated_at.isoformat(),
    }
    renderer_manifest = {
        "renderer": "image",
        "version": "1",
        "generation": generation_metadata,
    }

    try:
        if prepared.input.destination_artifact_id:
            if prepared.destination_base_version is None:
                raise ImageToolError(
                    "image_destination_unavailable",
                    "대상 이미지 Artifact의 기준 버전을 찾을 수 없습니다.",
                )
            artifact, version = create_binary_artifact_version(
                db,
                artifact_storage,
                user=user,
                artifact_id=prepared.input.destination_artifact_id,
                base_version=prepared.destination_base_version,
                mime_type=generated.mime_type,
                content=generated.content,
                change_type="agent_generated_image",
                change_summary="Codex 이미지 생성",
                renderer_manifest=renderer_manifest,
            )
        else:
            safe_token = hashlib.sha256(
                f"{run.id}:{prepared.tool_call_id}".encode("utf-8")
            ).hexdigest()[:12]
            extension = "jpg" if actual_format == "jpeg" else actual_format
            artifact, version = create_artifact(
                db,
                artifact_storage,
                user=user,
                project_id=run.project_id,
                conversation_id=run.conversation_id,
                source_run_id=run.id,
                display_name=f"Lumina_Image_{safe_token}.{extension}",
                kind="image",
                mime_type=generated.mime_type,
                content=generated.content,
                change_type="agent_generated_image",
                change_summary="Codex 이미지 생성",
                renderer_manifest=renderer_manifest,
            )
    except (ApiProblem, StorageError) as exc:
        raise ImageToolError(
            "image_storage_failed",
            "생성 이미지를 Artifact Storage에 저장하지 못했습니다.",
            stage="storage",
        ) from exc

    return PersistedImage(
        artifact_id=artifact.id,
        version=version.version_number,
        display_name=artifact.display_name,
        mime_type=artifact.mime_type,
        content_hash=version.content_hash,
        validation_status=version.validation_status,
        preview_url=(
            f"/api/artifacts/{artifact.id}/preview?version={version.version_number}"
        ),
        metadata=generation_metadata,
    )


def _validate_reference_attachments(
    db: Session,
    file_storage: ManagedLocalStorage,
    *,
    user: User,
    run: Run,
    attachment_ids: tuple[str, ...],
) -> None:
    for attachment_id in attachment_ids:
        attachment = db.get(Attachment, attachment_id)
        if (
            attachment is None
            or attachment.deleted_at is not None
            or attachment.status != "ready"
            or attachment.project_id != run.project_id
            or attachment.conversation_id is None
        ):
            raise ImageToolError(
                "image_attachment_unavailable",
                "참조 이미지 Attachment를 사용할 수 없습니다.",
                stage="authorization",
            )
        try:
            require_conversation(db, user, attachment.conversation_id)
            content = file_storage.read_bytes(
                attachment.storage_key, expected_sha256=attachment.content_hash
            )
        except (ApiProblem, StorageError) as exc:
            raise ImageToolError(
                "image_attachment_unavailable",
                "참조 이미지 Attachment를 사용할 수 없습니다.",
                stage="authorization",
            ) from exc
        actual_mime = sniff_mime(
            content, Path(attachment.original_filename).suffix.lower()
        )
        if (
            attachment.kind != "image"
            or not attachment.sniffed_mime_type.startswith("image/")
            or actual_mime != attachment.sniffed_mime_type
        ):
            raise ImageToolError(
                "image_attachment_invalid",
                "참조 Attachment가 유효한 이미지가 아닙니다.",
            )


def _option(
    arguments: dict[str, Any],
    name: str,
    default: str,
    allowed: set[str] | None,
) -> str:
    value = arguments.get(name, default)
    if not isinstance(value, str) or (allowed is not None and value not in allowed):
        raise ImageToolError(
            f"invalid_{name}", f"이미지 생성 {name} 값을 확인해 주세요."
        )
    return value


def _optional_id(arguments: dict[str, Any], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 64:
        raise ImageToolError(f"invalid_{name}", f"{name} 값을 확인해 주세요.")
    return value.strip()


def _validate_size(size: str) -> None:
    if size == "auto":
        return
    match = _SIZE.fullmatch(size)
    if match is None:
        raise ImageToolError("invalid_size", "이미지 생성 size 값을 확인해 주세요.")
    width, height = (int(value) for value in match.groups())
    pixels = width * height
    if (
        width > 3840
        or height > 3840
        or width % 16
        or height % 16
        or max(width, height) / min(width, height) > 3
        or pixels < 655_360
        or pixels > 8_294_400
    ):
        raise ImageToolError(
            "invalid_size", "이미지 생성 size가 지원 범위를 벗어났습니다."
        )


__all__ = [
    "GENERATE_IMAGE_TOOL_SCHEMA",
    "GenerateImageInput",
    "ImageToolError",
    "PersistedImage",
    "PreparedImageTool",
    "parse_generate_image_input",
    "persist_generated_image",
    "prepare_image_tool",
    "redacted_generate_image_input",
]
