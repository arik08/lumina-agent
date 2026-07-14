from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..messages.service import require_message
from ..models import Message, Run, User, UserMemory, UserSetting, utc_now
from ..providers.types import ProviderAdapter, ProviderMessage, ProviderRequest
from ..runs.service import append_event
from .policy import (
    contains_sensitive_memory as _contains_sensitive,
    normalize_fact,
    validate_memory_text,
)


EXTRACTOR_VERSION = "offline-conservative-v2"
LLM_EXTRACTOR_VERSION = "llm-structured-v1"
LLM_OPTIMIZER_VERSION = "llm-memory-optimizer-v1"
_STABLE_MARKER = re.compile(
    r"(?i)(?:항상|앞으로|매번|선호|기억해|기억해\s*주세요|원칙|반드시|"
    r"always|from\s+now\s+on|every\s+time|prefer|remember|must)"
)
_KOREAN_LANGUAGE = re.compile(
    r"(?i)(?:답변|응답|대답).{0,40}?(한국어|영어).{0,12}?(?:로|으로)"
)
_ENGLISH_LANGUAGE = re.compile(
    r"(?i)(?:respond|answer|reply).{0,40}?\b(korean|english)\b"
)
_KOREAN_ROLE = re.compile(
    r"(?:제|내)\s*(?:역할|직무|업무)\s*(?:은|는|이|가)?\s*"
    r"(.{2,80}?)(?:입니다|이에요|예요)(?:[.!?]|$)"
)
_ENGLISH_ROLE = re.compile(r"(?i)\b(?:my\s+role\s+is|i\s+work\s+as)\s+([^.!?\n]{2,80})")
_KOREAN_NAME = re.compile(
    r"(?:제|내)\s*이름\s*(?:은|는|이|가)?\s*"
    r"([가-힣A-Za-z][가-힣A-Za-z0-9 ._-]{0,79}?)"
    r"(?:이라고|라고|이야|야|입니다|이에요|예요)(?=[,.!?，。！？\s]|$)"
)
_ENGLISH_NAME = re.compile(
    r"(?i)\bmy\s+name\s+is\s+([A-Za-z][A-Za-z0-9 .'-]{0,79}?)"
    r"(?=[.!?]|\s+(?:and\s+)?remember\b|$)"
)
_MEMORY_COMMAND_ONLY = re.compile(
    r"(?i)^(?:(?:앞으로|항상)\s*)?(?:이걸?|그걸?|이것|그것)?\s*"
    r"(?:기억해(?:\s*줘|\s*주세요)?|remember(?:\s+it|\s+this)?)[.!?。！？]*$"
)
_EXPLICIT_MEMORY_REQUEST = re.compile(
    r"(?i)(?:기억해(?:\s*줘|\s*주세요)?|remember(?:\s+it|\s+this)?)"
    r"(?=[,.!?，。！？\s]|$)"
)
_MEMORY_RECALL_REQUEST = re.compile(
    r"(?i)(?:"
    r"(?:내|제)\s*(?:이름|직업|역할|고향|생일|취향|선호(?:사항)?|말투)"
    r"\s*(?:은|는|이|가)?\s*(?:뭐|무엇|뭔지|뭐였|무엇이었)"
    r"|(?:나|저)에?\s*대해\s*(?:뭘|무엇을|뭐를)?\s*(?:기억|알고)"
    r"|(?:나|저)를?\s*(?:어떻게|뭐라고)\s*(?:기억|알고)"
    r"|what(?:'s|\s+is)\s+my\s+(?:name|job|role|hometown|birthday|preference)"
    r"|what\s+do\s+you\s+(?:remember|know)\s+about\s+me"
    r")"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|[\r\n]+")
_MEMORY_TERM = re.compile(r"[A-Za-z0-9_]{2,}|[가-힣]{2,}")


@dataclass(frozen=True, slots=True)
class MemorySourceMessage:
    id: str
    run_id: str
    text: str


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    category: str
    fact: str
    display_text: str
    confidence: float
    conflict_key: str | None
    source_message_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryExtractionResult:
    mode: str
    created_ids: tuple[str, ...]
    updated_ids: tuple[str, ...]
    pending_ids: tuple[str, ...]
    skipped_count: int


@dataclass(frozen=True, slots=True)
class MemoryOptimizationResult:
    merged_ids: tuple[str, ...]
    superseded_ids: tuple[str, ...]


class MemoryExtractor(Protocol):
    version: str

    def extract(
        self, messages: Sequence[MemorySourceMessage]
    ) -> Sequence[MemoryCandidate]: ...


class ConservativeMemoryExtractor:
    """Extract only explicit, stable user-authored preferences and roles."""

    version = EXTRACTOR_VERSION

    def extract(
        self, messages: Sequence[MemorySourceMessage]
    ) -> Sequence[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        seen: set[tuple[str, str]] = set()
        for message in messages:
            identity_candidate = _explicit_identity_candidate(message.text, message.id)
            if identity_candidate is not None:
                key = (
                    identity_candidate.conflict_key or "",
                    normalize_fact(identity_candidate.fact),
                )
                seen.add(key)
                candidates.append(identity_candidate)
            for sentence in _sentences(message.text):
                if _contains_sensitive(sentence):
                    continue
                if identity_candidate is not None and (
                    _KOREAN_NAME.search(sentence) or _ENGLISH_NAME.search(sentence)
                ):
                    continue
                candidate = _candidate_from_sentence(sentence, message.id)
                if candidate is None:
                    continue
                key = (candidate.conflict_key or "", normalize_fact(candidate.fact))
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(candidate)
        return candidates


def is_explicit_memory_request(value: str) -> bool:
    """Return whether the user explicitly asks Lumina to remember something."""

    return bool(_EXPLICIT_MEMORY_REQUEST.search(value))


def is_memory_interaction_request(value: str) -> bool:
    """Return whether the request writes or directly recalls personal memory."""

    return is_explicit_memory_request(value) or bool(_MEMORY_RECALL_REQUEST.search(value))


class PreparedMemoryExtractor:
    version = LLM_EXTRACTOR_VERSION

    def __init__(self, candidates: Sequence[MemoryCandidate]) -> None:
        self._candidates = tuple(candidates)

    def extract(
        self, messages: Sequence[MemorySourceMessage]
    ) -> Sequence[MemoryCandidate]:
        return self._candidates


async def prepare_memory_extractor(
    provider: ProviderAdapter | None,
    *,
    model: str,
    messages: Sequence[MemorySourceMessage],
) -> MemoryExtractor:
    """Prefer the deterministic path and call an LLM only when it adds value."""

    local_extractor = ConservativeMemoryExtractor()
    local_candidates = local_extractor.extract(messages)
    if (
        local_candidates
        or provider is None
        or not messages
        or any(_contains_sensitive(message.text) for message in messages)
    ):
        return local_extractor
    candidates = await extract_memory_candidates_with_llm(
        provider,
        model=model,
        messages=messages,
    )
    return PreparedMemoryExtractor(candidates)


async def extract_memory_candidates_with_llm(
    provider: ProviderAdapter,
    *,
    model: str,
    messages: Sequence[MemorySourceMessage],
) -> tuple[MemoryCandidate, ...]:
    if not messages:
        return ()
    source_payload = [
        {"messageId": message.id, "text": message.text} for message in messages
    ]
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "user_memory_candidates",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {
                                    "type": "string",
                                    "enum": [
                                        "user_identity",
                                        "user_role",
                                        "communication_preference",
                                        "output_preference",
                                        "recurring_rule",
                                        "long_term_goal",
                                        "terminology",
                                    ],
                                },
                                "fact": {"type": "string"},
                                "displayText": {"type": "string"},
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "conflictKey": {
                                    "type": ["string", "null"]
                                },
                                "sourceMessageIds": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 1,
                                },
                            },
                            "required": [
                                "category",
                                "fact",
                                "displayText",
                                "confidence",
                                "conflictKey",
                                "sourceMessageIds",
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["candidates"],
                "additionalProperties": False,
            },
        },
    }
    prompt = (
        "Extract only explicit, stable facts the user stated about themselves or "
        "their lasting preferences. Preserve the meaning across sentence boundaries. "
        "A request such as 'remember this' is evidence of intent, never a fact by "
        "itself. For 'My name is Alex. Remember it', extract the name, not the word "
        "'remember'. Do not infer facts from assistant text, tools, or documents. "
        "Exclude passwords, tokens, certificates, government or employee identifiers, "
        "health, politics, union membership, one-time codes, temporary approvals, "
        "third-party secrets, and transient requests. Use a stable conflictKey such as "
        "user_name, user_role, response_language, response_tone, or null when facts can "
        "coexist. Write fact and displayText as the same concise Korean sentence. "
        "Do not add an English translation; keep only proper nouns and established "
        "technical terms when needed. Return no candidate when there is no useful "
        "durable fact.\n\n"
        f"User-authored messages:\n{json.dumps(source_payload, ensure_ascii=False)}"
    )
    chunks: list[str] = []
    async for event in provider.stream(
        ProviderRequest(
            model=model,
            messages=(
                ProviderMessage(
                    role="system",
                    content=(
                        "You are a conservative user-memory extraction component. "
                        "Return only the requested JSON."
                    ),
                ),
                ProviderMessage(role="user", content=prompt),
            ),
            response_format=schema,
            effort="low",
            max_output_tokens=800,
            metadata={"purpose": "user_memory_extraction"},
        )
    ):
        if event.type == "text_delta" and event.text:
            chunks.append(event.text)
    raw = "".join(chunks).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    parsed = json.loads(raw)
    rows = parsed.get("candidates") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Memory extractor response is missing candidates")
    allowed_ids = {message.id for message in messages}
    candidates: list[MemoryCandidate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_ids = tuple(
            dict.fromkeys(
                source_id
                for source_id in row.get("sourceMessageIds", [])
                if isinstance(source_id, str) and source_id in allowed_ids
            )
        )
        if not source_ids:
            continue
        conflict_key = row.get("conflictKey")
        display_text = str(row.get("displayText", "")).strip()
        candidate = MemoryCandidate(
            category=str(row.get("category", "")),
            fact=display_text,
            display_text=display_text,
            confidence=float(row.get("confidence", 0)),
            conflict_key=conflict_key if isinstance(conflict_key, str) else None,
            source_message_ids=source_ids,
        )
        if _candidate_is_valid(candidate):
            candidates.append(candidate)
    return tuple(candidates)


async def optimize_memories_with_llm(
    db: Session,
    *,
    user: User,
    provider: ProviderAdapter,
    model: str,
) -> MemoryOptimizationResult:
    memories = list_memories(db, user=user, status="active")
    if len(memories) < 2:
        return MemoryOptimizationResult((), ())
    payload = [
        {
            "id": memory.id,
            "category": memory.category,
            "fact": memory.normalized_fact,
            "displayText": memory.display_text,
            "conflictKey": memory.conflict_key,
            "confidence": memory.confidence,
            "evidenceCount": memory.evidence_count,
        }
        for memory in memories
    ]
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "user_memory_optimization",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "merges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sourceMemoryIds": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 2,
                                },
                                "category": {"type": "string"},
                                "fact": {"type": "string"},
                                "displayText": {"type": "string"},
                                "conflictKey": {"type": ["string", "null"]},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                            "required": ["sourceMemoryIds", "category", "fact", "displayText", "conflictKey", "confidence"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["merges"],
                "additionalProperties": False,
            },
        },
    }
    prompt = (
        "Consolidate only memories that express the same durable fact or preference. "
        "Merge paraphrases and fragmented statements when no meaning is lost. Never "
        "merge merely related facts, different people, conflicting values, or facts "
        "with different scopes. Return an empty merges array when uncertain. Preserve "
        "all concrete details in a concise standalone Korean sentence. Write fact and "
        "displayText as that same Korean sentence without an English translation. Use "
        "only the supplied memory IDs.\n\nActive memories:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    chunks: list[str] = []
    async for event in provider.stream(
        ProviderRequest(
            model=model,
            messages=(
                ProviderMessage(role="system", content="You conservatively optimize a user's memory store. Return only JSON."),
                ProviderMessage(role="user", content=prompt),
            ),
            response_format=schema,
            max_output_tokens=3_000,
            metadata={"purpose": "user_memory_optimization"},
        )
    ):
        if event.type == "text_delta" and event.text:
            chunks.append(event.text)
    parsed = json.loads("".join(chunks).strip())
    merges = parsed.get("merges") if isinstance(parsed, dict) else None
    if not isinstance(merges, list):
        raise ValueError("Memory optimizer response is missing merges")

    by_id = {memory.id: memory for memory in memories}
    used: set[str] = set()
    merged_ids: list[str] = []
    superseded_ids: list[str] = []
    for merge in merges:
        if not isinstance(merge, dict):
            continue
        source_ids = tuple(dict.fromkeys(merge.get("sourceMemoryIds", [])))
        if len(source_ids) < 2 or any(source_id not in by_id or source_id in used for source_id in source_ids):
            continue
        category = str(merge.get("category", "")).strip()
        display_text = str(merge.get("displayText", "")).strip()
        fact = display_text
        conflict_key = merge.get("conflictKey")
        confidence = float(merge.get("confidence", 0))
        candidate = MemoryCandidate(category, fact, display_text, confidence, conflict_key if isinstance(conflict_key, str) else None, ())
        if not _candidate_is_valid(candidate) or _contains_sensitive("\n".join((fact, display_text))):
            continue
        sources = [by_id[source_id] for source_id in source_ids]
        combined = UserMemory(
            user_id=user.id,
            category=category,
            normalized_fact=normalize_fact(fact),
            display_text=display_text,
            conflict_key=candidate.conflict_key,
            source_message_ids_json=list(dict.fromkeys(item for source in sources for item in source.source_message_ids_json)),
            source_run_ids_json=list(dict.fromkeys(item for source in sources for item in source.source_run_ids_json)),
            confidence=confidence,
            evidence_count=sum(source.evidence_count for source in sources),
            status="active",
            supersedes_memory_id=sources[0].id,
            extractor_version=LLM_OPTIMIZER_VERSION,
        )
        db.add(combined)
        db.flush()
        for source in sources:
            source.status = "superseded"
            source.updated_at = utc_now()
            superseded_ids.append(source.id)
        used.update(source_ids)
        merged_ids.append(combined.id)
    return MemoryOptimizationResult(tuple(merged_ids), tuple(superseded_ids))


def _validate_memory_text(*values: str) -> None:
    validate_memory_text(*values)


def _validate_expiry(value: datetime | None) -> None:
    if value is not None and value.tzinfo is None:
        raise ApiProblem(
            422, "timezone_required", "Memory 만료 시각에는 시간대가 필요합니다."
        )


def _source_messages(
    db: Session, *, user: User, source_message_ids: list[str]
) -> list[Message]:
    messages: list[Message] = []
    for message_id in dict.fromkeys(source_message_ids):
        message = require_message(db, user, message_id)
        if message.role != "user" or message.author_user_id != user.id:
            raise ApiProblem(
                409,
                "memory_source_invalid",
                "본인이 작성한 사용자 메시지만 Memory 출처로 사용할 수 있습니다.",
            )
        messages.append(message)
    if not messages:
        raise ApiProblem(422, "memory_source_required", "Memory 출처가 필요합니다.")
    return messages


def _append_memory_events(
    db: Session, *, run_ids: list[str], memory: UserMemory, action: str
) -> None:
    for run_id in dict.fromkeys(run_ids):
        run = db.get(Run, run_id)
        if run is not None:
            append_event(
                db,
                run,
                "memory_changed",
                {"memoryId": memory.id, "action": action, "status": memory.status},
            )


def create_memory(
    db: Session,
    *,
    user: User,
    category: str,
    fact: str,
    display_text: str,
    source_message_ids: list[str],
    confidence: float,
    expires_at: datetime | None,
) -> tuple[UserMemory, bool]:
    _validate_memory_text(fact, display_text)
    _validate_expiry(expires_at)
    messages = _source_messages(db, user=user, source_message_ids=source_message_ids)
    normalized = normalize_fact(fact)
    source_ids = [message.id for message in messages]
    run_ids = list(
        dict.fromkeys(message.run_id for message in messages if message.run_id)
    )
    existing = db.scalar(
        select(UserMemory).where(
            UserMemory.user_id == user.id,
            UserMemory.normalized_fact == normalized,
            UserMemory.status == "active",
            UserMemory.deleted_at.is_(None),
        )
    )
    now = utc_now()
    if existing is not None:
        existing.source_message_ids_json = list(
            dict.fromkeys(existing.source_message_ids_json + source_ids)
        )
        existing.source_run_ids_json = list(
            dict.fromkeys(existing.source_run_ids_json + run_ids)
        )
        existing.display_text = display_text
        existing.category = category
        existing.confidence = max(existing.confidence, confidence)
        existing.evidence_count += 1
        existing.last_confirmed_at = now
        existing.expires_at = expires_at
        existing.updated_at = now
        memory = existing
        created = False
    else:
        memory = UserMemory(
            user_id=user.id,
            category=category,
            normalized_fact=normalized,
            display_text=display_text,
            conflict_key=None,
            source_message_ids_json=source_ids,
            source_run_ids_json=run_ids,
            confidence=confidence,
            evidence_count=1,
            status="active",
            extractor_version="manual-v1",
            expires_at=expires_at,
        )
        db.add(memory)
        created = True
    db.flush()
    _append_memory_events(
        db, run_ids=run_ids, memory=memory, action="created" if created else "confirmed"
    )
    return memory, created


def learn_memories_for_run(
    db: Session,
    run_id: str,
    *,
    extractor: MemoryExtractor | None = None,
) -> MemoryExtractionResult:
    run = db.get(Run, run_id)
    if run is None or run.status != "completed":
        raise ValueError("Memory extraction requires a completed Run")
    user = db.get(User, run.user_id)
    if user is None:
        raise ValueError("Run owner no longer exists")
    mode = _mode_for_run(db, run, user)
    if mode == "off":
        return MemoryExtractionResult("off", (), (), (), 0)

    source_rows = list(
        db.scalars(
            select(Message)
            .where(
                Message.run_id == run.id,
                Message.role == "user",
                Message.author_user_id == run.user_id,
                Message.status == "completed",
            )
            .order_by(Message.created_at, Message.id)
        )
    )
    sources = tuple(
        MemorySourceMessage(
            id=message.id,
            run_id=run.id,
            text=message.canonical_text,
        )
        for message in source_rows
    )
    selected_extractor = extractor or ConservativeMemoryExtractor()
    if not selected_extractor.version or len(selected_extractor.version) > 80:
        raise ValueError("Memory extractor version must be 1-80 characters")
    candidates = selected_extractor.extract(sources)
    allowed_source_ids = {source.id for source in sources}
    created_ids: list[str] = []
    updated_ids: list[str] = []
    pending_ids: list[str] = []
    skipped_count = 0
    seen_candidates: set[str] = set()

    for candidate in candidates:
        if not _candidate_is_valid(candidate):
            skipped_count += 1
            continue
        normalized = normalize_fact(candidate.fact)
        if normalized in seen_candidates or _contains_sensitive(
            "\n".join((candidate.fact, candidate.display_text))
        ):
            skipped_count += 1
            continue
        seen_candidates.add(normalized)
        source_ids = list(
            dict.fromkeys(
                source_id
                for source_id in candidate.source_message_ids
                if source_id in allowed_source_ids
            )
        )
        if not source_ids:
            skipped_count += 1
            continue

        exact_matches = list(
            db.scalars(
                select(UserMemory)
                .where(
                    UserMemory.user_id == run.user_id,
                    UserMemory.normalized_fact == normalized,
                )
                .order_by(UserMemory.updated_at.desc(), UserMemory.id)
            )
        )
        if any(
            match.deleted_at is not None or match.status in {"deleted", "dismissed"}
            for match in exact_matches
        ):
            skipped_count += 1
            continue
        existing = next(
            (
                match
                for match in exact_matches
                if match.deleted_at is None and match.status in {"active", "pending"}
            ),
            None,
        )
        if existing is not None:
            new_source_ids = [
                source_id
                for source_id in source_ids
                if source_id not in existing.source_message_ids_json
            ]
            if new_source_ids:
                existing.source_message_ids_json = list(
                    dict.fromkeys(existing.source_message_ids_json + source_ids)
                )
                existing.source_run_ids_json = list(
                    dict.fromkeys(existing.source_run_ids_json + [run.id])
                )
                existing.evidence_count += 1
                existing.confidence = max(existing.confidence, candidate.confidence)
                existing.last_confirmed_at = utc_now()
                existing.updated_at = existing.last_confirmed_at
                updated_ids.append(existing.id)
                _append_memory_events(
                    db, run_ids=[run.id], memory=existing, action="evidence_merged"
                )
            else:
                if not (existing.status == "pending" and mode == "auto"):
                    skipped_count += 1
            if existing.status == "pending" and mode == "auto":
                conflicts = _active_conflicts(
                    db,
                    user_id=run.user_id,
                    conflict_key=existing.conflict_key,
                    normalized_fact=existing.normalized_fact,
                )
                if conflicts and existing.supersedes_memory_id is None:
                    existing.supersedes_memory_id = conflicts[0].id
                existing.status = "active"
                existing.last_confirmed_at = utc_now()
                existing.updated_at = existing.last_confirmed_at
                _supersede_conflicts(db, conflicts, replacing=existing)
                if existing.id not in updated_ids:
                    updated_ids.append(existing.id)
                _append_memory_events(
                    db,
                    run_ids=[run.id],
                    memory=existing,
                    action="auto_accepted",
                )
            if existing.status == "pending":
                pending_ids.append(existing.id)
            continue

        conflicts = _active_conflicts(
            db,
            user_id=run.user_id,
            conflict_key=candidate.conflict_key,
            normalized_fact=normalized,
        )
        newest_conflict = conflicts[0] if conflicts else None
        memory = UserMemory(
            user_id=run.user_id,
            category=candidate.category,
            normalized_fact=normalized,
            display_text=candidate.display_text,
            conflict_key=candidate.conflict_key,
            source_message_ids_json=source_ids,
            source_run_ids_json=[run.id],
            confidence=min(1.0, max(0.0, candidate.confidence)),
            evidence_count=1,
            status="active" if mode == "auto" else "pending",
            supersedes_memory_id=newest_conflict.id if newest_conflict else None,
            extractor_version=selected_extractor.version,
        )
        db.add(memory)
        db.flush()
        if mode == "auto":
            _supersede_conflicts(db, conflicts, replacing=memory)
        else:
            pending_ids.append(memory.id)
        created_ids.append(memory.id)
        _append_memory_events(
            db,
            run_ids=[run.id],
            memory=memory,
            action="created" if mode == "auto" else "candidate_created",
        )

    append_event(
        db,
        run,
        "memory_extraction_completed",
        {
            "mode": mode,
            "extractorVersion": selected_extractor.version,
            "createdIds": created_ids,
            "updatedIds": updated_ids,
            "pendingIds": list(dict.fromkeys(pending_ids)),
            "skippedCount": skipped_count,
        },
    )
    return MemoryExtractionResult(
        mode=mode,
        created_ids=tuple(created_ids),
        updated_ids=tuple(updated_ids),
        pending_ids=tuple(dict.fromkeys(pending_ids)),
        skipped_count=skipped_count,
    )


def list_memories(
    db: Session,
    *,
    user: User,
    status: str = "active",
    query: str | None = None,
) -> list[UserMemory]:
    statement = select(UserMemory).where(
        UserMemory.user_id == user.id,
        UserMemory.deleted_at.is_(None),
        UserMemory.status == status,
    )
    if status == "active":
        now = utc_now()
        statement = statement.where(
            or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now)
        )
    if query:
        normalized = f"%{' '.join(query.split()).casefold()}%"
        statement = statement.where(
            or_(
                UserMemory.normalized_fact.like(normalized),
                UserMemory.display_text.ilike(normalized),
            )
        )
    return list(
        db.scalars(statement.order_by(UserMemory.updated_at.desc(), UserMemory.id))
    )


def select_relevant_memories(
    db: Session,
    *,
    user_id: str,
    query: str,
    limit: int = 8,
    character_budget: int = 8_000,
) -> list[UserMemory]:
    """Select a small deterministic subset instead of injecting all Memory."""

    now = utc_now()
    candidates = list(
        db.scalars(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.status == "active",
                UserMemory.deleted_at.is_(None),
                or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
            )
        )
    )
    query_terms = _memory_terms(query)
    ranked: list[tuple[int, int, float, str, UserMemory]] = []
    for memory in candidates:
        always_relevant = memory.category in {
            "communication_preference",
            "user_identity",
            "user_role",
        }
        memory_terms = _memory_terms(
            " ".join(
                (
                    memory.normalized_fact,
                    memory.display_text,
                    memory.category,
                    memory.conflict_key or "",
                )
            )
        )
        overlap = len(query_terms & memory_terms)
        if not always_relevant and overlap == 0:
            continue
        score = (1_000 if always_relevant else 0) + overlap * 50
        ranked.append(
            (score, memory.evidence_count, memory.confidence, memory.id, memory)
        )
    ranked.sort(key=lambda item: item[:4], reverse=True)
    selected: list[UserMemory] = []
    remaining = max(0, character_budget)
    for _score, _evidence, _confidence, _id, memory in ranked:
        text_length = (
            len(memory.display_text.strip())
            + len(memory.id)
            + len(memory.category)
            + 32
        )
        if text_length == 0 or text_length > remaining:
            continue
        selected.append(memory)
        remaining -= text_length
        if len(selected) >= max(0, limit):
            break
    return selected


def require_memory(db: Session, user: User, memory_id: str) -> UserMemory:
    memory = db.get(UserMemory, memory_id)
    if memory is None or memory.user_id != user.id or memory.deleted_at is not None:
        raise ApiProblem(404, "memory_not_found", "Memory를 찾을 수 없습니다.")
    return memory


def patch_memory(
    db: Session,
    *,
    user: User,
    memory_id: str,
    changes: dict[str, Any],
) -> UserMemory:
    memory = require_memory(db, user, memory_id)
    if "expires_at" in changes:
        _validate_expiry(changes["expires_at"])
    fact = changes.get("fact")
    display_text = changes.get("display_text")
    _validate_memory_text(
        str(fact) if fact is not None else memory.normalized_fact,
        str(display_text) if display_text is not None else memory.display_text,
    )
    if fact is not None:
        normalized = normalize_fact(str(fact))
        duplicate = db.scalar(
            select(UserMemory).where(
                UserMemory.user_id == user.id,
                UserMemory.normalized_fact == normalized,
                UserMemory.status == "active",
                UserMemory.deleted_at.is_(None),
                UserMemory.id != memory.id,
            )
        )
        if duplicate is not None:
            raise ApiProblem(
                409, "memory_fact_exists", "같은 내용의 활성 Memory가 있습니다."
            )
        memory.normalized_fact = normalized
    if "category" in changes:
        memory.category = str(changes["category"])
    if display_text is not None:
        memory.display_text = str(display_text)
    if "confidence" in changes:
        memory.confidence = float(changes["confidence"])
    action = "updated"
    if "status" in changes:
        requested_status = str(changes["status"])
        if memory.status == "pending" and requested_status == "active":
            replaced = (
                db.get(UserMemory, memory.supersedes_memory_id)
                if memory.supersedes_memory_id
                else None
            )
            if replaced is not None and replaced.status == "active":
                replaced.status = "superseded"
                replaced.updated_at = utc_now()
                _append_memory_events(
                    db,
                    run_ids=replaced.source_run_ids_json,
                    memory=replaced,
                    action="superseded",
                )
            memory.status = "active"
            action = "accepted"
        elif requested_status == "dismissed":
            memory.status = "dismissed"
            action = "dismissed"
        else:
            memory.status = requested_status
    if "expires_at" in changes:
        memory.expires_at = changes["expires_at"]
    memory.last_confirmed_at = utc_now()
    memory.updated_at = memory.last_confirmed_at
    db.flush()
    _append_memory_events(
        db, run_ids=memory.source_run_ids_json, memory=memory, action=action
    )
    return memory


def delete_memory(db: Session, *, user: User, memory_id: str) -> UserMemory:
    memory = require_memory(db, user, memory_id)
    memory.status = "deleted"
    memory.deleted_at = utc_now()
    memory.updated_at = memory.deleted_at
    _append_memory_events(
        db, run_ids=memory.source_run_ids_json, memory=memory, action="deleted"
    )
    return memory


def get_memory_setting(db: Session, user: User) -> tuple[str, UserSetting | None]:
    setting = db.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user.id,
            UserSetting.key == "memory_learning",
        )
    )
    if setting is None or not isinstance(setting.value_json, dict):
        return "auto", setting
    mode = setting.value_json.get("mode")
    return mode if mode in {"auto", "confirm", "off"} else "auto", setting


def set_memory_setting(db: Session, *, user: User, mode: str) -> UserSetting:
    _current, setting = get_memory_setting(db, user)
    if setting is None:
        setting = UserSetting(
            user_id=user.id,
            key="memory_learning",
            value_json={"mode": mode},
        )
        db.add(setting)
    else:
        setting.value_json = {"mode": mode}
        setting.updated_at = utc_now()
    db.flush()
    return setting


def memory_payload(memory: UserMemory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "category": memory.category,
        "normalizedFact": memory.normalized_fact,
        "displayText": memory.display_text,
        "conflictKey": memory.conflict_key,
        "sourceMessageIds": memory.source_message_ids_json,
        "sourceRunIds": memory.source_run_ids_json,
        "confidence": memory.confidence,
        "evidenceCount": memory.evidence_count,
        "status": memory.status,
        "supersedesMemoryId": memory.supersedes_memory_id,
        "extractorVersion": memory.extractor_version,
        "expiresAt": memory.expires_at,
        "firstLearnedAt": memory.first_learned_at,
        "lastConfirmedAt": memory.last_confirmed_at,
        "updatedAt": memory.updated_at,
    }


def _sentences(value: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in _SENTENCE_SPLIT.split(value)
        if sentence.strip()
    ]


def _candidate_is_valid(candidate: MemoryCandidate) -> bool:
    return (
        0 < len(candidate.category) <= 80
        and 0 < len(candidate.fact) <= 1_000
        and 0 < len(candidate.display_text) <= 4_000
        and (candidate.conflict_key is None or len(candidate.conflict_key) <= 160)
        and 0.0 <= candidate.confidence <= 1.0
    )


def _memory_terms(value: str) -> set[str]:
    result: set[str] = set()
    for match in _MEMORY_TERM.findall(value.casefold()):
        result.add(match)
        if any("가" <= character <= "힣" for character in match):
            result.update(match[index : index + 2] for index in range(len(match) - 1))
    return result


def _explicit_identity_candidate(
    value: str, message_id: str
) -> MemoryCandidate | None:
    if not _STABLE_MARKER.search(value) or _contains_sensitive(value):
        return None
    match = _KOREAN_NAME.search(value) or _ENGLISH_NAME.search(value)
    if match is None:
        return None
    name = " ".join(match.group(1).split()).strip(" ._-'")
    if not name or _contains_sensitive(name):
        return None
    return MemoryCandidate(
        category="user_identity",
        fact=f"사용자 이름은 {name}입니다.",
        display_text=f"사용자 이름은 {name}입니다.",
        confidence=0.99,
        conflict_key="user_name",
        source_message_ids=(message_id,),
    )


def _candidate_from_sentence(sentence: str, message_id: str) -> MemoryCandidate | None:
    if _MEMORY_COMMAND_ONLY.fullmatch(sentence.strip()):
        return None
    language_match = _KOREAN_LANGUAGE.search(sentence) or _ENGLISH_LANGUAGE.search(
        sentence
    )
    if language_match is not None and _STABLE_MARKER.search(sentence):
        language = language_match.group(1).casefold()
        display_language = "한국어" if language in {"한국어", "korean"} else "영어"
        memory_text = f"답변 언어로 {display_language}를 선호합니다."
        return MemoryCandidate(
            category="communication_preference",
            fact=memory_text,
            display_text=memory_text,
            confidence=0.98,
            conflict_key="response_language",
            source_message_ids=(message_id,),
        )
    role_match = _KOREAN_ROLE.search(sentence) or _ENGLISH_ROLE.search(sentence)
    if role_match is not None:
        role = " ".join(role_match.group(1).split()).strip(" .")
        if role and not _contains_sensitive(role):
            memory_text = f"사용자 역할은 {role}입니다."
            return MemoryCandidate(
                category="user_role",
                fact=memory_text,
                display_text=memory_text,
                confidence=0.9,
                conflict_key="user_role",
                source_message_ids=(message_id,),
            )
    if not _STABLE_MARKER.search(sentence):
        return None
    lowered = sentence.casefold()
    if any(
        token in lowered
        for token in ("간결", "짧게", "concise")
    ):
        category = "communication_preference"
        conflict_key = "response_detail"
        memory_text = "답변은 간결하게 작성하는 것을 선호합니다."
    elif any(token in lowered for token in ("자세", "상세", "detailed")):
        category = "communication_preference"
        conflict_key = "response_detail"
        memory_text = "답변은 상세하게 작성하는 것을 선호합니다."
    elif any(token in lowered for token in ("존댓말", "반말", "formal", "casual")):
        category = "communication_preference"
        conflict_key = "response_tone"
        memory_text = (
            "존댓말 사용을 선호합니다."
            if any(token in lowered for token in ("존댓말", "formal"))
            else "반말 사용을 선호합니다."
        )
    elif any(
        token in lowered for token in ("보고서", "report", "html", "markdown", "pdf")
    ):
        category = "output_preference"
        conflict_key = "report_output"
        format_name = next(
            (
                display
                for token, display in (
                    ("markdown", "Markdown"),
                    ("html", "HTML"),
                    ("pdf", "PDF"),
                )
                if token in lowered
            ),
            None,
        )
        memory_text = (
            f"보고서는 {format_name} 형식을 선호합니다."
            if format_name
            else "출력은 보고서 형식을 선호합니다."
        )
    else:
        return None
    return MemoryCandidate(
        category=category,
        fact=memory_text,
        display_text=memory_text,
        confidence=0.82,
        conflict_key=conflict_key,
        source_message_ids=(message_id,),
    )


def _mode_for_run(db: Session, run: Run, user: User) -> str:
    snapshotted = run.snapshot_json.get("memory_learning_mode")
    if snapshotted in {"auto", "confirm", "off"}:
        return str(snapshotted)
    mode, _setting = get_memory_setting(db, user)
    return mode


def _active_conflicts(
    db: Session,
    *,
    user_id: str,
    conflict_key: str | None,
    normalized_fact: str,
) -> list[UserMemory]:
    if conflict_key is None:
        return []
    return list(
        db.scalars(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.conflict_key == conflict_key,
                UserMemory.normalized_fact != normalized_fact,
                UserMemory.status == "active",
                UserMemory.deleted_at.is_(None),
            )
            .order_by(UserMemory.updated_at.desc(), UserMemory.id)
        )
    )


def _supersede_conflicts(
    db: Session, conflicts: Sequence[UserMemory], *, replacing: UserMemory
) -> None:
    now = utc_now()
    for conflict in conflicts:
        conflict.status = "superseded"
        conflict.updated_at = now
        _append_memory_events(
            db,
            run_ids=conflict.source_run_ids_json,
            memory=conflict,
            action="superseded",
        )
    if conflicts and replacing.supersedes_memory_id is None:
        replacing.supersedes_memory_id = conflicts[0].id
