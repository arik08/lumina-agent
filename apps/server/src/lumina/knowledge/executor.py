from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import select, update

from ..db import SessionLocal, session_scope
from ..models import (
    KnowledgeEvidenceSegment,
    KnowledgeIngestionJob,
    KnowledgeSource,
    User,
    utc_now,
)
from ..providers.errors import ProviderConfigurationError, ProviderRequestError
from ..providers.types import ProviderAdapter
from .extractor import EvidenceInput, KnowledgeExtraction, extract_knowledge
from .schemas import KnowledgeEntityCreate, KnowledgeStatementCreate
from .service import create_knowledge_entity, create_knowledge_statement


logger = logging.getLogger(__name__)


class KnowledgeIngestionExecutor:
    def __init__(self) -> None:
        self._started = False
        self._provider_factory: Callable[[str], ProviderAdapter] | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def started(self) -> bool:
        return self._started

    def configure(
        self, *, provider_factory: Callable[[str], ProviderAdapter]
    ) -> None:
        if self._started:
            raise RuntimeError("Cannot reconfigure Knowledge ingestion while running")
        self._provider_factory = provider_factory

    async def start(self) -> None:
        if self._started:
            return
        if self._provider_factory is None:
            raise RuntimeError("Knowledge ingestion provider factory is not configured")
        self._started = True
        self._loop = asyncio.get_running_loop()
        with session_scope() as db:
            db.execute(
                update(KnowledgeIngestionJob)
                .where(KnowledgeIngestionJob.status == "running")
                .values(
                    status="queued",
                    started_at=None,
                    error_code=None,
                    error_message=None,
                    updated_at=utc_now(),
                )
            )
            queued_ids = list(
                db.scalars(
                    select(KnowledgeIngestionJob.id)
                    .where(KnowledgeIngestionJob.status == "queued")
                    .order_by(
                        KnowledgeIngestionJob.queued_at,
                        KnowledgeIngestionJob.id,
                    )
                )
            )
        for job_id in queued_ids:
            self.enqueue(job_id)

    async def stop(self) -> None:
        self._started = False
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._loop = None

    def enqueue(self, job_id: str) -> None:
        loop = self._loop
        if not self._started or loop is None:
            return
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            loop.call_soon_threadsafe(self._schedule, job_id)
            return
        if current_loop is loop:
            self._schedule(job_id)
        else:
            loop.call_soon_threadsafe(self._schedule, job_id)

    def _schedule(self, job_id: str) -> None:
        if not self._started or job_id in self._tasks:
            return
        task = asyncio.create_task(
            self._execute(job_id), name=f"lumina-knowledge-ingestion-{job_id}"
        )
        self._tasks[job_id] = task
        task.add_done_callback(lambda completed: self._discard(job_id, completed))

    def _discard(self, job_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(job_id) is task:
            self._tasks.pop(job_id, None)

    async def _execute(self, job_id: str) -> None:
        try:
            prepared = self._claim(job_id)
            if prepared is None:
                return
            provider_factory = self._provider_factory
            if provider_factory is None:
                raise RuntimeError("Knowledge ingestion provider factory is unavailable")
            extraction = await extract_knowledge(
                provider=provider_factory(prepared["provider_id"]),
                model=prepared["runtime_model_id"],
                source_title=prepared["source_title"],
                evidence=prepared["evidence"],
            )
            self._apply(job_id, extraction)
        except asyncio.CancelledError:
            self._requeue(job_id)
            raise
        except (ProviderConfigurationError, ProviderRequestError) as exc:
            self._fail(job_id, "knowledge_provider_failed", str(exc))
        except Exception:
            logger.exception("Knowledge ingestion failed", extra={"job_id": job_id})
            self._fail(
                job_id,
                "knowledge_extraction_failed",
                "AI가 원문에서 검토 가능한 지식을 추출하지 못했습니다.",
            )

    def _claim(self, job_id: str) -> dict[str, object] | None:
        with session_scope() as db:
            job = db.get(KnowledgeIngestionJob, job_id)
            if job is None or job.status != "queued":
                return None
            source = db.get(KnowledgeSource, job.source_id)
            user = db.get(User, job.requested_by_user_id)
            if source is None or user is None:
                job.status = "failed"
                job.error_code = "knowledge_ingestion_context_missing"
                job.error_message = "AI 추출 대상 또는 요청 계정을 찾을 수 없습니다."
                job.finished_at = utc_now()
                return None
            evidence = list(
                db.scalars(
                    select(KnowledgeEvidenceSegment)
                    .where(
                        KnowledgeEvidenceSegment.source_revision_id
                        == job.source_revision_id
                    )
                    .order_by(
                        KnowledgeEvidenceSegment.segment_ordinal,
                        KnowledgeEvidenceSegment.id,
                    )
                )
            )
            job.status = "running"
            job.started_at = utc_now()
            job.finished_at = None
            job.error_code = None
            job.error_message = None
            return {
                "provider_id": job.provider_id,
                "runtime_model_id": job.runtime_model_id,
                "source_title": source.title,
                "evidence": [
                    EvidenceInput(
                        id=item.id,
                        text=item.text,
                        locator=dict(item.locator_json),
                    )
                    for item in evidence
                ],
            }

    def _apply(self, job_id: str, extraction: KnowledgeExtraction) -> None:
        with session_scope() as db:
            job = db.get(KnowledgeIngestionJob, job_id)
            if job is None or job.status != "running":
                return
            user = db.get(User, job.requested_by_user_id)
            if user is None:
                raise RuntimeError("Knowledge ingestion user disappeared")
            entities_by_key = {}
            for item in extraction.entities:
                entity, _created = create_knowledge_entity(
                    db,
                    user,
                    job.space_id,
                    KnowledgeEntityCreate(
                        entity_type=item.entity_type,
                        canonical_name=item.canonical_name,
                        description=item.description,
                    ),
                )
                entities_by_key[item.key] = entity
            statement_count = 0
            for item in extraction.statements:
                subject = entities_by_key[item.subject_key]
                object_entity = entities_by_key[item.object_key]
                statement = create_knowledge_statement(
                    db,
                    user,
                    job.space_id,
                    KnowledgeStatementCreate(
                        subject_entity_id=subject.id,
                        predicate_key=item.predicate_key,
                        object_kind="entity",
                        object_entity_id=object_entity.id,
                        evidence_segment_ids=item.evidence_segment_ids,
                        status="proposed",
                        confidence=item.confidence,
                        change_summary=(
                            f"{job.extractor_version} AI 추출 · 사용자 검토 대기"
                        ),
                    ),
                )
                statement.created_by_type = "agent"
                statement_count += 1
            job.status = "completed"
            job.input_segment_count = extraction.input_segment_count
            job.input_character_count = extraction.input_character_count
            job.entity_count = len(entities_by_key)
            job.statement_count = statement_count
            job.input_tokens = extraction.input_tokens
            job.output_tokens = extraction.output_tokens
            job.finished_at = utc_now()
            job.error_code = None
            job.error_message = None

    def _requeue(self, job_id: str) -> None:
        with session_scope() as db:
            job = db.get(KnowledgeIngestionJob, job_id)
            if job is not None and job.status == "running":
                job.status = "queued"
                job.started_at = None
                job.finished_at = None

    def _fail(self, job_id: str, code: str, message: str) -> None:
        with SessionLocal() as db:
            job = db.get(KnowledgeIngestionJob, job_id)
            if job is None or job.status not in {"queued", "running"}:
                return
            job.status = "failed"
            job.error_code = code[:120]
            job.error_message = message[:2_000]
            job.finished_at = utc_now()
            db.commit()


knowledge_ingestion_executor = KnowledgeIngestionExecutor()
