from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...authorization import require_conversation
from ...attachments import MIME_BY_EXTENSION, extract_attachment_text, sniff_mime
from ...config import Settings, get_settings
from ...db import get_db
from ...models import Attachment, User, utc_now
from ...storage import ManagedLocalStorage
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem


router = APIRouter(tags=["attachments"])

_MIME_BY_EXTENSION = MIME_BY_EXTENSION


def _storage(settings: Settings) -> ManagedLocalStorage:
    if settings.files_dir is None:
        raise RuntimeError("LUMINA_FILES_DIR is not configured")
    return ManagedLocalStorage(settings.files_dir)


def _payload(attachment: Attachment) -> dict[str, object]:
    return {
        "id": attachment.id,
        "conversationId": attachment.conversation_id,
        "projectId": attachment.project_id,
        "kind": attachment.kind,
        "fileName": attachment.original_filename,
        "mimeType": attachment.sniffed_mime_type,
        "size": attachment.size_bytes,
        "contentHash": attachment.content_hash,
        "status": attachment.status,
        "extractionStatus": attachment.extraction_status,
        "extractionVersion": attachment.extraction_version,
        "locatorMap": attachment.locator_map_json,
        "metadata": attachment.metadata_json,
        "createdAt": attachment.created_at,
    }


@router.post("/conversations/{conversation_id}/attachments", status_code=201)
async def post_attachment(
    conversation_id: str,
    file: UploadFile | None = File(default=None),
    pasted_text: str | None = Form(default=None),
    source: str = Form(default="upload"),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    conversation = require_conversation(db, context.user, conversation_id, write=True)
    if (file is None) == (pasted_text is None):
        raise ApiProblem(
            422,
            "attachment_input_required",
            "파일 또는 붙여넣은 텍스트 하나가 필요합니다.",
        )

    if pasted_text is not None:
        content = pasted_text.encode("utf-8")
        if len(content) > settings.max_pasted_text_bytes:
            raise ApiProblem(
                413, "attachment_too_large", "붙여넣은 텍스트가 너무 큽니다."
            )
        kind = "pasted_text"
        filename = "붙여넣은 텍스트.txt"
        mime_type = "text/plain"
        metadata = {"source": "paste", "lineCount": len(pasted_text.splitlines())}
        extension = "txt"
    else:
        assert file is not None
        content = await file.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            raise ApiProblem(
                413, "attachment_too_large", "첨부 파일이 허용 크기를 초과했습니다."
            )
        filename = Path(file.filename or "attachment").name
        extension_value = Path(filename).suffix.lower()
        if extension_value not in _MIME_BY_EXTENSION:
            raise ApiProblem(
                415, "unsupported_attachment", "지원하지 않는 파일 형식입니다."
            )
        mime_type = _sniff_mime(content, extension_value)
        expected = _MIME_BY_EXTENSION[extension_value]
        if mime_type != expected:
            raise ApiProblem(
                415, "mime_mismatch", "파일 내용과 확장자가 일치하지 않습니다."
            )
        kind = "image" if mime_type.startswith("image/") else "file"
        metadata = {"source": source, "clientMimeType": file.content_type}
        extension = extension_value.removeprefix(".")

    if not content or (mime_type.startswith("text/") and not content.strip()):
        raise ApiProblem(422, "attachment_empty", "빈 파일은 첨부할 수 없습니다.")
    extraction = extract_attachment_text(
        filename=filename, mime_type=mime_type, content=content
    )
    if extraction.status == "failed":
        raise ApiProblem(
            422,
            "attachment_extraction_failed",
            "문서 내용을 안전하게 읽을 수 없습니다.",
            details={"errorType": extraction.metadata.get("errorType", "Unknown")},
        )
    if kind == "file" and extraction.status == "unsupported":
        raise ApiProblem(
            415,
            "attachment_extraction_unsupported",
            "이 문서 형식의 내용 추출을 지원하지 않습니다.",
        )

    digest = hashlib.sha256(content).hexdigest()
    attachment = Attachment(
        organization_id=context.user.organization_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        owner_user_id=context.user.id,
        kind=kind,
        original_filename=filename,
        sniffed_mime_type=mime_type,
        size_bytes=len(content),
        content_hash=digest,
        storage_backend="local",
        storage_key="pending",
        status="pending",
        extraction_status="pending" if kind == "file" else "not_required",
        metadata_json=metadata,
    )
    db.add(attachment)
    db.flush()
    key = f"attachments/{context.user.id}/{attachment.id}/{digest}.{extension}"
    stored = _storage(settings).put_bytes(key, content, expected_sha256=digest)
    attachment.storage_key = stored.key
    attachment.status = "ready"
    attachment.extraction_status = extraction.status
    attachment.extraction_version = "lumina-text-v1"
    attachment.locator_map_json = extraction.locator_map
    attachment.metadata_json = {**metadata, **extraction.metadata}
    if extraction.status == "completed":
        extracted = extraction.text.encode("utf-8")
        extracted_digest = hashlib.sha256(extracted).hexdigest()
        extraction_key = (
            f"extractions/{context.user.id}/{attachment.id}/{extracted_digest}.txt"
        )
        stored_extraction = _storage(settings).put_bytes(
            extraction_key, extracted, expected_sha256=extracted_digest
        )
        attachment.metadata_json = {
            **attachment.metadata_json,
            "extractedStorageKey": stored_extraction.key,
            "extractedContentHash": extracted_digest,
            "extractedSize": len(extracted),
        }
    db.commit()
    return _payload(attachment)


@router.get("/attachments/{attachment_id}")
def get_attachment(
    attachment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.deleted_at is not None:
        raise ApiProblem(404, "not_found", "첨부 파일을 찾을 수 없습니다.")
    require_conversation(db, user, attachment.conversation_id or "")
    return _payload(attachment)


@router.get("/attachments/{attachment_id}/content")
def get_attachment_content(
    attachment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.deleted_at is not None:
        raise ApiProblem(404, "not_found", "첨부 파일을 찾을 수 없습니다.")
    require_conversation(db, user, attachment.conversation_id or "")
    content = _storage(settings).read_bytes(
        attachment.storage_key, expected_sha256=attachment.content_hash
    )
    return Response(content=content, media_type=attachment.sniffed_mime_type)


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    attachment_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.deleted_at is not None:
        raise ApiProblem(404, "not_found", "첨부 파일을 찾을 수 없습니다.")
    require_conversation(db, context.user, attachment.conversation_id or "", write=True)
    attachment.deleted_at = utc_now()
    attachment.status = "deleted"
    db.commit()
    return Response(status_code=204)


_sniff_mime = sniff_mime
