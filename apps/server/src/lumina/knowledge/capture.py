from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..config import Settings
from ..models import Conversation, Message, Run, User
from .schemas import EvidenceSegmentCreate, KnowledgeSourceCreate
from .service import (
    create_knowledge_ingestion_job,
    create_knowledge_source,
    knowledge_auto_capture_payload,
)


_MAX_CAPTURED_TEXT_CHARACTERS = 500_000
_MAX_EXTRACTION_CHARACTERS = 60_000
_MAX_ANALYSIS_SEGMENT_CHARACTERS = 30_000
_MAX_WEB_SOURCE_SEGMENTS = 10
_MAX_WEB_SOURCE_SEGMENT_CHARACTERS = 5_000


@dataclass(frozen=True)
class KnowledgeCaptureResult:
    source_id: str
    job_id: str | None
    source_created: bool
    job_created: bool
    ingestion_error_code: str | None = None


def capture_completed_research_run(
    db: Session,
    *,
    run_id: str,
    assistant_message_id: str,
    settings: Settings,
) -> KnowledgeCaptureResult | None:
    run = db.get(Run, run_id)
    message = db.get(Message, assistant_message_id)
    if (
        run is None
        or message is None
        or message.run_id != run.id
        or message.role != "assistant"
        or message.status != "completed"
        or not message.canonical_text.strip()
    ):
        return None
    user = db.get(User, run.user_id)
    if user is None or user.status != "active":
        return None
    auto_capture = knowledge_auto_capture_payload(db, user)
    space_id = auto_capture.get("spaceId")
    if auto_capture.get("enabled") is not True or not isinstance(space_id, str):
        return None

    raw_sources = message.metadata_json.get("sources", [])
    if not isinstance(raw_sources, list):
        return None
    fetched_sources = [
        source
        for source in raw_sources
        if isinstance(source, Mapping)
        and source.get("evidenceKind") == "fetched_content"
        and source.get("extractionStatus", "complete") == "complete"
    ]
    if not fetched_sources:
        return None

    conversation = db.get(Conversation, run.conversation_id)
    conversation_title = (
        conversation.title.strip() if conversation is not None else "리서치 분석"
    )
    title = f"{conversation_title or '리서치 분석'} · 분석 결과"[:500]
    analysis_text = message.canonical_text.strip()
    captured_text = _captured_markdown(analysis_text, fetched_sources)
    digest = sha256(captured_text.encode("utf-8")).hexdigest()
    evidence_segments = _evidence_segments(
        run=run,
        message=message,
        analysis_text=analysis_text,
        fetched_sources=fetched_sources,
    )
    source_payload = KnowledgeSourceCreate(
        source_type="conversation",
        title=title,
        canonical_locator=(
            f"lumina://conversations/{run.conversation_id}/runs/{run.id}"
        ),
        content_digest=digest,
        media_type="text/markdown",
        byte_size=len(captured_text.encode("utf-8")),
        captured_text=captured_text,
        parser_name="lumina-research-run",
        parser_version="1",
        parse_digest=digest,
        evidence_segments=evidence_segments,
    )
    source, _revision, _evidence, source_created = create_knowledge_source(
        db, user, space_id, source_payload
    )
    try:
        job, job_created = create_knowledge_ingestion_job(
            db, user, space_id, source.id, settings=settings
        )
    except ApiProblem as exc:
        return KnowledgeCaptureResult(
            source_id=source.id,
            job_id=None,
            source_created=source_created,
            job_created=False,
            ingestion_error_code=exc.code,
        )
    return KnowledgeCaptureResult(
        source_id=source.id,
        job_id=job.id,
        source_created=source_created,
        job_created=job_created,
    )


def _captured_markdown(
    analysis_text: str, fetched_sources: list[Mapping[str, Any]]
) -> str:
    source_lines = []
    for index, source in enumerate(fetched_sources[:_MAX_WEB_SOURCE_SEGMENTS], start=1):
        title = str(source.get("title") or source.get("domain") or f"출처 {index}").strip()
        url = str(source.get("normalizedUrl") or source.get("originalUrl") or "").strip()
        source_lines.append(f"{index}. {title}" + (f" — {url}" if url else ""))
    result = f"# 분석 결과\n\n{analysis_text}\n\n## 검증된 출처\n\n" + "\n".join(
        source_lines
    )
    return result[:_MAX_CAPTURED_TEXT_CHARACTERS]


def _evidence_segments(
    *,
    run: Run,
    message: Message,
    analysis_text: str,
    fetched_sources: list[Mapping[str, Any]],
) -> list[EvidenceSegmentCreate]:
    analysis_segment = analysis_text[:_MAX_ANALYSIS_SEGMENT_CHARACTERS]
    segments = [
        EvidenceSegmentCreate(
            text=analysis_segment,
            locator={
                "kind": "assistant_analysis",
                "conversationId": run.conversation_id,
                "runId": run.id,
                "messageId": message.id,
                "derived": True,
            },
            language="ko",
            token_count=max(1, len(analysis_segment) // 3),
        )
    ]
    character_count = len(analysis_segment)
    for source in fetched_sources[:_MAX_WEB_SOURCE_SEGMENTS]:
        excerpt = str(source.get("verbatimExcerpt") or "").strip()
        if not excerpt or character_count >= _MAX_EXTRACTION_CHARACTERS:
            continue
        remaining = _MAX_EXTRACTION_CHARACTERS - character_count
        excerpt = excerpt[: min(_MAX_WEB_SOURCE_SEGMENT_CHARACTERS, remaining)]
        if not excerpt:
            continue
        segments.append(
            EvidenceSegmentCreate(
                text=excerpt,
                locator={
                    "kind": "web_source",
                    "sourceId": source.get("sourceId"),
                    "title": source.get("title"),
                    "url": source.get("normalizedUrl") or source.get("originalUrl"),
                    "domain": source.get("domain"),
                },
                token_count=max(1, len(excerpt) // 3),
            )
        )
        character_count += len(excerpt)
    return segments
