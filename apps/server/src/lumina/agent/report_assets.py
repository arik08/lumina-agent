from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..artifacts.reporting import ReportImage
from ..artifacts.service import current_artifact_version, require_artifact
from ..attachments import sniff_mime
from ..authorization import require_conversation
from ..models import Attachment, Run, User
from ..storage import ManagedLocalStorage, StorageError


def resolve_report_images(
    db: Session,
    *,
    run: Run,
    user: User,
    arguments: dict[str, Any],
    file_storage: ManagedLocalStorage,
    artifact_storage: ManagedLocalStorage,
    max_total_bytes: int,
) -> tuple[ReportImage, ...]:
    attachment_ids = _ids(arguments, "image_attachment_ids")
    artifact_ids = _ids(arguments, "image_artifact_ids")
    if len(attachment_ids) + len(artifact_ids) > 8:
        raise ValueError("보고서 본문 이미지 자산은 최대 8개까지 사용할 수 있습니다.")

    images: list[ReportImage] = []
    total_bytes = 0
    for attachment_id in attachment_ids:
        attachment = db.get(Attachment, attachment_id)
        if (
            attachment is None
            or attachment.deleted_at is not None
            or attachment.status != "ready"
            or attachment.project_id != run.project_id
            or attachment.conversation_id is None
        ):
            raise ValueError("보고서 이미지 Attachment를 사용할 수 없습니다.")
        try:
            require_conversation(db, user, attachment.conversation_id)
            content = file_storage.read_bytes(
                attachment.storage_key, expected_sha256=attachment.content_hash
            )
        except (ApiProblem, StorageError) as exc:
            raise ValueError("보고서 이미지 Attachment를 사용할 수 없습니다.") from exc
        actual_mime = sniff_mime(
            content, Path(attachment.original_filename).suffix.lower()
        )
        if (
            attachment.kind != "image"
            or actual_mime != attachment.sniffed_mime_type
            or actual_mime not in {"image/png", "image/jpeg", "image/webp"}
        ):
            raise ValueError("보고서 Attachment가 지원하는 이미지가 아닙니다.")
        total_bytes += len(content)
        _check_total_size(total_bytes, max_total_bytes)
        images.append(
            ReportImage(
                source_type="attachment",
                source_id=attachment.id,
                source_version=None,
                display_name=attachment.original_filename,
                mime_type=actual_mime,
                content_hash=attachment.content_hash,
                content=content,
            )
        )

    for artifact_id in artifact_ids:
        try:
            artifact = require_artifact(db, user, artifact_id)
        except ApiProblem as exc:
            raise ValueError("보고서 이미지 Artifact를 사용할 수 없습니다.") from exc
        if artifact.project_id != run.project_id or not artifact.mime_type.startswith(
            "image/"
        ):
            raise ValueError("보고서 이미지 Artifact를 사용할 수 없습니다.")
        version = current_artifact_version(db, artifact)
        if version is None:
            raise ValueError("보고서 이미지 Artifact 버전을 찾을 수 없습니다.")
        try:
            content = artifact_storage.read_bytes(
                version.storage_key, expected_sha256=version.content_hash
            )
        except StorageError as exc:
            raise ValueError("보고서 이미지 Artifact를 읽을 수 없습니다.") from exc
        actual_mime = sniff_mime(content, Path(artifact.display_name).suffix.lower())
        if actual_mime != artifact.mime_type or actual_mime not in {
            "image/png",
            "image/jpeg",
            "image/webp",
        }:
            raise ValueError("보고서 Artifact가 지원하는 이미지가 아닙니다.")
        total_bytes += len(content)
        _check_total_size(total_bytes, max_total_bytes)
        images.append(
            ReportImage(
                source_type="artifact",
                source_id=artifact.id,
                source_version=version.version_number,
                display_name=artifact.display_name,
                mime_type=actual_mime,
                content_hash=version.content_hash,
                content=content,
            )
        )
    return tuple(images)


def _ids(arguments: dict[str, Any], key: str) -> list[str]:
    raw = arguments.get(key, [])
    if not isinstance(raw, list) or len(raw) > 8:
        raise ValueError(f"{key} 값을 확인해 주세요.")
    result: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise ValueError(f"{key} 값을 확인해 주세요.")
        normalized = value.strip()
        if normalized not in result:
            result.append(normalized)
    return result


def _check_total_size(total_bytes: int, maximum: int) -> None:
    if total_bytes > maximum:
        raise ValueError("보고서 이미지 자산의 전체 크기가 허용 범위를 초과했습니다.")


__all__ = ["resolve_report_images"]
