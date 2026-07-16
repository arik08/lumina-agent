from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    CompactedContextEntry,
    Message,
    Plan,
    PlanStep,
    Run,
    ToolExecution,
    utc_now,
)
from ..providers import ProviderMessage
from ..providers.catalog import (
    DEFAULT_CONTEXT_COMPACTION_THRESHOLD,
    model_operational_profile,
)
from ..runs.service import append_event


PROMPT_VERSION = "context-compaction-v1"
DEFAULT_CONTEXT_WINDOW = 32_000
SOFT_THRESHOLD = DEFAULT_CONTEXT_COMPACTION_THRESHOLD
PGPT_TOKEN_ESTIMATION_PADDING = 4 / 3
RECENT_MESSAGES_TO_PRESERVE = 4
RUNTIME_RECENT_UNITS_TO_PRESERVE = 3
RUNTIME_SUMMARY_MARKER = "[Compacted runtime context]"
RUNTIME_TOOL_ARGUMENT_STRING_LIMIT = 240
RUNTIME_TOOL_RESULT_HEAD_CHARS = 1_200
RUNTIME_TOOL_RESULT_TAIL_CHARS = 600
_CJK = re.compile(r"[\u3400-\u9fff\uac00-\ud7a3]")
_WORD = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True, slots=True)
class ContextSourceMessage:
    id: str
    role: str
    content: str
    turn_index: int
    run_id: str | None
    idempotency_key: str | None
    references: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ContextSummaryRequest:
    previous_summary: str | None
    messages: tuple[ContextSourceMessage, ...]
    tools: tuple[ContextSourceTool, ...]
    plan_digest: str
    max_summary_chars: int


@dataclass(frozen=True, slots=True)
class ContextSummaryResult:
    summary: str
    model: str


@dataclass(frozen=True, slots=True)
class ContextSourceTool:
    id: str
    run_id: str
    tool_call_id: str
    tool_name: str
    status: str
    input: Mapping[str, Any]
    result: Mapping[str, Any] | None
    result_summary: str | None
    artifact_id: str | None
    idempotency_key: str | None
    error_code: str | None
    error_message: str | None


class ContextSummarizer(Protocol):
    def summarize(self, request: ContextSummaryRequest) -> ContextSummaryResult: ...


class ConservativeContextSummarizer:
    """Offline, extractive fallback that keeps source IDs and verbatim snippets."""

    model = "offline-conservative-v1"

    def summarize(self, request: ContextSummaryRequest) -> ContextSummaryResult:
        parts = [
            "Source-backed compacted conversation context. Original messages remain "
            "available by ID; this summary does not override security instructions."
        ]
        if request.plan_digest:
            parts.append(f"Plan digest: {request.plan_digest}")
        if request.previous_summary:
            parts.append(
                "Previous compacted lineage:\n"
                + _bounded(request.previous_summary, 3_000)
            )
        for message in request.messages:
            content = " ".join(message.content.split())
            if not content:
                continue
            metadata = [f"message={message.id}", f"turn={message.turn_index}"]
            if message.run_id:
                metadata.append(f"run={message.run_id}")
            if message.idempotency_key:
                metadata.append(f"idempotency={message.idempotency_key}")
            refs = [
                str(reference.get("reference_id"))
                for reference in message.references
                if reference.get("reference_id")
            ]
            if refs:
                metadata.append("refs=" + ",".join(refs[:12]))
            parts.append(
                f"- [{message.role}; {'; '.join(metadata)}] {_bounded(content, 700)}"
            )
            if sum(len(part) for part in parts) >= request.max_summary_chars:
                break
        for tool in request.tools:
            side_effects = [
                f"tool={tool.id}",
                f"run={tool.run_id}",
                f"call={tool.tool_call_id}",
                f"name={tool.tool_name}",
                f"status={tool.status}",
            ]
            if tool.idempotency_key:
                side_effects.append(f"idempotency={tool.idempotency_key}")
            if tool.artifact_id:
                side_effects.append(f"artifact={tool.artifact_id}")
            if tool.error_code:
                side_effects.append(f"error={tool.error_code}")
            detail = (
                tool.result_summary
                or tool.error_message
                or _bounded(
                    json.dumps(tool.result or {}, ensure_ascii=False, sort_keys=True),
                    700,
                )
            )
            parts.append(f"- [tool; {'; '.join(side_effects)}] {detail}")
            if sum(len(part) for part in parts) >= request.max_summary_chars:
                break
        summary = _bounded("\n".join(parts), request.max_summary_chars).strip()
        if not summary:
            raise ValueError("summarizer produced an empty summary")
        return ContextSummaryResult(summary=summary, model=self.model)


@dataclass(frozen=True, slots=True)
class ContextPreparation:
    summary: str | None
    retained_tool_context: str | None
    retained_message_ids: tuple[str, ...]
    compaction: CompactedContextEntry | None
    estimated_tokens: int
    effective_input_budget: int


@dataclass(frozen=True, slots=True)
class RuntimeContextPreparation:
    messages: tuple[ProviderMessage, ...]
    compacted: bool
    estimated_tokens_before: int
    estimated_tokens_after: int
    effective_input_budget: int
    compacted_message_count: int = 0
    preserved_message_count: int = 0
    compacted_payload_count: int = 0


def compact_runtime_messages(
    run: Run,
    messages: Sequence[ProviderMessage],
    tool_schemas: Sequence[Mapping[str, Any]],
    *,
    force: bool = False,
) -> RuntimeContextPreparation:
    """Compact an in-flight tool loop while preserving recent tool-call pairs.

    Completed conversation turns are compacted by :func:`prepare_context`. This
    companion handles assistant/tool messages that exist only in the active
    provider request and therefore are not yet stored as completed Messages.
    """

    _, effective_budget = _context_budget(run, tool_schemas)
    estimated_before = _padded_estimate(
        run,
        _estimate_provider_messages(messages, tool_schemas),
    )
    threshold = _compaction_threshold(run, effective_budget)
    if not force and estimated_before <= threshold:
        return RuntimeContextPreparation(
            messages=tuple(messages),
            compacted=False,
            estimated_tokens_before=estimated_before,
            estimated_tokens_after=estimated_before,
            effective_input_budget=effective_budget,
        )

    head: list[ProviderMessage] = []
    previous_summaries: list[str] = []
    body_start = 0
    for index, message in enumerate(messages):
        if message.role != "system":
            body_start = index
            break
        if (message.content or "").startswith(RUNTIME_SUMMARY_MARKER):
            previous_summaries.append(message.content or "")
        else:
            head.append(message)
        body_start = index + 1

    units = _provider_message_units(messages[body_start:])
    preserve_target = 1 if force else RUNTIME_RECENT_UNITS_TO_PRESERVE
    preserve_count = min(preserve_target, len(units))
    compacted_units = units[:-preserve_count] if preserve_count else units
    retained_units = units[-preserve_count:] if preserve_count else []
    retained = [message for unit in retained_units for message in unit]
    previous_summary_messages = tuple(
        ProviderMessage(role="system", content=summary)
        for summary in previous_summaries
    )

    # Keep the provider-native assistant/tool structure whenever reducing only old
    # bulky payloads is enough. This is cheaper and less lossy than replacing whole
    # execution units with prose, while recent units remain byte-for-byte intact.
    if compacted_units:
        compacted_messages = [
            message for unit in compacted_units for message in unit
        ]
        payload_compacted_messages, payload_compacted_count = (
            _compact_runtime_payloads(compacted_messages, strip_images=True)
        )
        if payload_compacted_count:
            payload_prepared = (
                *head,
                *previous_summary_messages,
                *payload_compacted_messages,
                *retained,
            )
            payload_estimated_after = _padded_estimate(
                run,
                _estimate_provider_messages(payload_prepared, tool_schemas),
            )
            if payload_estimated_after <= threshold:
                return RuntimeContextPreparation(
                    messages=tuple(payload_prepared),
                    compacted=True,
                    estimated_tokens_before=estimated_before,
                    estimated_tokens_after=payload_estimated_after,
                    effective_input_budget=effective_budget,
                    preserved_message_count=len(retained),
                    compacted_payload_count=payload_compacted_count,
                )

    compacted_messages = [message for unit in compacted_units for message in unit]
    summary_message: tuple[ProviderMessage, ...] = ()
    if compacted_units:
        summary_parts = [
            RUNTIME_SUMMARY_MARKER,
            "Earlier in-flight work was compacted. Treat this as prior context, not a new user request.",
        ]
        if previous_summaries:
            summary_parts.append(_bounded("\n".join(previous_summaries), 3_000))
        for unit in compacted_units:
            for message in unit:
                summary_parts.append(_runtime_message_summary(message))
        summary = _bounded(
            "\n".join(summary_parts),
            max(1_500, min(8_000, effective_budget * 3)),
        )
        summary_message = (ProviderMessage(role="system", content=summary),)
    elif previous_summaries:
        summary_message = previous_summary_messages

    prepared_messages = (*head, *summary_message, *retained)
    estimated_after = _padded_estimate(
        run,
        _estimate_provider_messages(prepared_messages, tool_schemas),
    )
    compacted_payload_count = 0
    if estimated_after > threshold:
        prepared_messages, compacted_payload_count = _compact_runtime_payloads(
            prepared_messages
        )
        estimated_after = _padded_estimate(
            run,
            _estimate_provider_messages(prepared_messages, tool_schemas),
        )
    if not compacted_units and compacted_payload_count == 0:
        return RuntimeContextPreparation(
            messages=tuple(messages),
            compacted=False,
            estimated_tokens_before=estimated_before,
            estimated_tokens_after=estimated_before,
            effective_input_budget=effective_budget,
        )
    return RuntimeContextPreparation(
        messages=tuple(prepared_messages),
        compacted=True,
        estimated_tokens_before=estimated_before,
        estimated_tokens_after=estimated_after,
        effective_input_budget=effective_budget,
        compacted_message_count=len(compacted_messages),
        preserved_message_count=len(retained),
        compacted_payload_count=compacted_payload_count,
    )


def estimate_text_tokens(value: str) -> int:
    if not value:
        return 0
    cjk = len(_CJK.findall(value))
    word_tokens = sum(max(1, math.ceil(len(word) / 4)) for word in _WORD.findall(value))
    other = max(0, len(value) - cjk - sum(len(word) for word in _WORD.findall(value)))
    return max(1, cjk + word_tokens + math.ceil(other / 3))


def prepare_context(
    db: Session,
    *,
    run: Run,
    history: Sequence[Message],
    content_by_message_id: Mapping[str, str],
    prefix_texts: Sequence[str],
    tool_schemas: Sequence[Mapping[str, Any]],
    summarizer: ContextSummarizer | None = None,
    now: datetime | None = None,
) -> ContextPreparation:
    current = now or utc_now()
    ordered = sorted(history, key=lambda item: (item.created_at, item.id))
    latest = db.scalar(
        select(CompactedContextEntry)
        .where(CompactedContextEntry.conversation_id == run.conversation_id)
        .order_by(CompactedContextEntry.version.desc(), CompactedContextEntry.id.desc())
        .limit(1)
    )
    active = db.scalar(
        select(CompactedContextEntry)
        .where(
            CompactedContextEntry.conversation_id == run.conversation_id,
            CompactedContextEntry.status == "active",
        )
        .order_by(CompactedContextEntry.version.desc(), CompactedContextEntry.id.desc())
        .limit(1)
    )
    represented_ids = set(active.source_message_ids_json if active else [])
    retained = [message for message in ordered if message.id not in represented_ids]
    all_run_ids = {message.run_id for message in ordered if message.run_id}
    tools = (
        list(
            db.scalars(
                select(ToolExecution)
                .where(ToolExecution.run_id.in_(all_run_ids))
                .order_by(ToolExecution.created_at, ToolExecution.id)
            )
        )
        if all_run_ids
        else []
    )
    incomplete_tool_run_ids = {
        tool.run_id for tool in tools if tool.status not in {"completed", "failed"}
    }
    retained_tools = _tools_for_messages(tools, retained)
    retained_tool_context = _tool_context(retained_tools)
    context_window, effective_budget = _context_budget(run, tool_schemas)
    estimated_before = _padded_estimate(
        run,
        _estimate_context(
            prefix_texts,
            active.summary if active else None,
            retained,
            content_by_message_id,
            tool_schemas,
            retained_tool_context,
        ),
    )
    actual_input = run.usage_json.get("input_tokens", 0)
    if isinstance(actual_input, int) and not isinstance(actual_input, bool):
        estimated_before = max(estimated_before, actual_input)
    threshold = _compaction_threshold(run, effective_budget)
    if estimated_before <= threshold or (
        latest is not None and latest.cooldown_until > current
    ):
        return _preparation(
            active,
            retained,
            estimated_before,
            effective_budget,
            retained_tool_context=retained_tool_context,
        )

    preserve_count = min(RECENT_MESSAGES_TO_PRESERVE, len(ordered))
    source_candidates = ordered[:-preserve_count] if preserve_count else ordered
    source_messages = [
        message
        for message in source_candidates
        if message.run_id not in incomplete_tool_run_ids
    ]
    if not source_messages:
        return _preparation(
            active,
            retained,
            estimated_before,
            effective_budget,
            retained_tool_context=retained_tool_context,
        )
    source_ids = [message.id for message in source_messages]
    newly_compacted = [
        message for message in source_messages if message.id not in represented_ids
    ]
    if not newly_compacted:
        return _preparation(
            active,
            retained,
            estimated_before,
            effective_budget,
            retained_tool_context=retained_tool_context,
        )

    run_ids = {message.run_id for message in source_messages if message.run_id}
    source_runs = {
        source_run.id: source_run
        for source_run in db.scalars(select(Run).where(Run.id.in_(run_ids)))
    }
    summary_request = ContextSummaryRequest(
        previous_summary=active.summary if active else None,
        messages=tuple(
            _source_message(message, content_by_message_id, source_runs)
            for message in newly_compacted
        ),
        tools=tuple(
            _source_tool(tool) for tool in _tools_for_messages(tools, newly_compacted)
        ),
        plan_digest=_plan_digest(db, run),
        max_summary_chars=max(1_500, min(8_000, effective_budget * 3)),
    )
    selected_summarizer = summarizer or ConservativeContextSummarizer()
    try:
        result = selected_summarizer.summarize(summary_request)
        if not result.summary.strip():
            raise ValueError("summarizer produced an empty summary")
    except Exception:
        failed_tools = _tools_for_messages(tools, source_messages)
        failed_version = (
            int(
                db.scalar(
                    select(func.max(CompactedContextEntry.version)).where(
                        CompactedContextEntry.conversation_id == run.conversation_id
                    )
                )
                or 0
            )
            + 1
        )
        failed_count = (latest.ineffective_count if latest is not None else 0) + 1
        failed_cooldown = current + timedelta(minutes=5 * failed_count)
        failed_entry = CompactedContextEntry(
            conversation_id=run.conversation_id,
            run_id=run.id,
            parent_compaction_id=active.id if active else None,
            version=failed_version,
            status="failed",
            summary=active.summary if active else "",
            source_message_ids_json=source_ids,
            source_message_range_json=_source_range(source_messages),
            source_event_range_json=_source_event_range(source_runs),
            source_refs_json=_source_refs(source_messages, failed_tools),
            source_hash=_source_hash(
                source_messages,
                content_by_message_id,
                source_runs,
                failed_tools,
            ),
            estimated_tokens_before=estimated_before,
            estimated_tokens_after=estimated_before,
            context_window=context_window,
            effective_input_budget=effective_budget,
            summary_model=type(selected_summarizer).__name__[:160],
            prompt_version=PROMPT_VERSION,
            retrieval_policy="original_context_retained",
            access_scope="private_user",
            cooldown_until=failed_cooldown,
            ineffective_count=failed_count,
            compacted_at=current,
        )
        db.add(failed_entry)
        db.flush()
        append_event(
            db,
            run,
            "context_compaction_failed",
            {
                "compactionId": failed_entry.id,
                "version": failed_entry.version,
                "reason": "summarizer_failed",
                "keptExistingContext": True,
                "cooldownUntil": failed_cooldown,
            },
        )
        return _preparation(
            active,
            retained,
            estimated_before,
            effective_budget,
            failed_entry,
            retained_tool_context=retained_tool_context,
        )

    retained_after = [
        message for message in ordered if message.id not in set(source_ids)
    ]
    retained_tools_after = _tools_for_messages(tools, retained_after)
    retained_tool_context_after = _tool_context(retained_tools_after)
    estimated_after = _padded_estimate(
        run,
        _estimate_context(
            prefix_texts,
            result.summary,
            retained_after,
            content_by_message_id,
            tool_schemas,
            retained_tool_context_after,
        ),
    )
    effective = estimated_after <= int(estimated_before * 0.9)
    previous_ineffective = latest.ineffective_count if latest is not None else 0
    ineffective_count = 0 if effective else previous_ineffective + 1
    cooldown = current + timedelta(minutes=5 * max(1, ineffective_count))
    version = (
        int(
            db.scalar(
                select(func.max(CompactedContextEntry.version)).where(
                    CompactedContextEntry.conversation_id == run.conversation_id
                )
            )
            or 0
        )
        + 1
    )
    if effective and active is not None:
        active.status = "superseded"
    entry = CompactedContextEntry(
        conversation_id=run.conversation_id,
        run_id=run.id,
        parent_compaction_id=active.id if active else None,
        version=version,
        status="active" if effective else "ineffective",
        summary=result.summary,
        source_message_ids_json=source_ids,
        source_message_range_json=_source_range(source_messages),
        source_event_range_json=_source_event_range(source_runs),
        source_refs_json=_source_refs(
            source_messages, _tools_for_messages(tools, source_messages)
        ),
        source_hash=_source_hash(
            source_messages,
            content_by_message_id,
            source_runs,
            _tools_for_messages(tools, source_messages),
        ),
        estimated_tokens_before=estimated_before,
        estimated_tokens_after=estimated_after,
        context_window=context_window,
        effective_input_budget=effective_budget,
        summary_model=result.model,
        prompt_version=PROMPT_VERSION,
        retrieval_policy="source_messages_by_id",
        access_scope="private_user",
        cooldown_until=cooldown,
        ineffective_count=ineffective_count,
        compacted_at=current,
    )
    db.add(entry)
    db.flush()
    append_event(
        db,
        run,
        "context_compacted" if effective else "context_compaction_ineffective",
        {
            "compactionId": entry.id,
            "version": entry.version,
            "status": entry.status,
            "sourceMessageRange": entry.source_message_range_json,
            "sourceHash": entry.source_hash,
            "estimatedTokensBefore": estimated_before,
            "estimatedTokensAfter": estimated_after,
            "cooldownUntil": cooldown,
        },
    )
    if not effective:
        return _preparation(
            active,
            retained,
            estimated_before,
            effective_budget,
            entry,
            retained_tool_context,
        )
    run.snapshot_json = {
        **run.snapshot_json,
        "context_compaction": {
            "id": entry.id,
            "version": entry.version,
            "source_hash": entry.source_hash,
            "estimated_tokens_before": estimated_before,
            "estimated_tokens_after": estimated_after,
        },
    }
    return ContextPreparation(
        summary=entry.summary,
        retained_tool_context=retained_tool_context_after,
        retained_message_ids=tuple(message.id for message in retained_after),
        compaction=entry,
        estimated_tokens=estimated_after,
        effective_input_budget=effective_budget,
    )


def _preparation(
    active: CompactedContextEntry | None,
    retained: Sequence[Message],
    estimated_tokens: int,
    effective_budget: int,
    attempted: CompactedContextEntry | None = None,
    retained_tool_context: str | None = None,
) -> ContextPreparation:
    return ContextPreparation(
        summary=active.summary if active else None,
        retained_tool_context=retained_tool_context,
        retained_message_ids=tuple(message.id for message in retained),
        compaction=attempted or active,
        estimated_tokens=estimated_tokens,
        effective_input_budget=effective_budget,
    )


def _context_budget(
    run: Run, tool_schemas: Sequence[Mapping[str, Any]]
) -> tuple[int, int]:
    execution = run.snapshot_json.get("execution", {})
    capabilities = (
        execution.get("capabilities", {}) if isinstance(execution, dict) else {}
    )
    if not isinstance(capabilities, Mapping):
        capabilities = {}
    fallback_context_window = _fallback_context_window(run)
    context_window = _positive_integer(
        capabilities.get("context_window", capabilities.get("contextWindow")),
        fallback_context_window,
    )
    operational_profile = _run_operational_profile(run)
    if (
        operational_profile is not None
        and operational_profile.context_compaction_threshold is not None
        and operational_profile.context_window is not None
    ):
        context_window = max(context_window, operational_profile.context_window)
    reserved_output = _positive_integer(
        capabilities.get(
            "configured_max_output_tokens",
            capabilities.get(
                "configuredMaxOutputTokens",
                capabilities.get(
                    "max_output_tokens", capabilities.get("maxOutputTokens")
                ),
            ),
        ),
        max(512, min(4_096, context_window // 8)),
    )
    tool_tokens = (
        estimate_text_tokens(
            json.dumps(
                list(tool_schemas), ensure_ascii=False, sort_keys=True, default=str
            )
        )
        if tool_schemas
        else 0
    )
    safety_margin = max(256, min(4_096, context_window // 20))
    max_input_tokens = _positive_integer(
        capabilities.get(
            "max_input_tokens", capabilities.get("maxInputTokens")
        ),
        context_window,
    )
    return context_window, max(
        256,
        min(context_window - reserved_output, max_input_tokens)
        - tool_tokens
        - safety_margin,
    )


def _compaction_threshold(run: Run, effective_budget: int) -> int:
    execution = run.snapshot_json.get("execution", {})
    capabilities = (
        execution.get("capabilities", {}) if isinstance(execution, Mapping) else {}
    )
    ratio = (
        capabilities.get("context_compaction_threshold")
        if isinstance(capabilities, Mapping)
        else None
    )
    if (
        not isinstance(ratio, (int, float))
        or isinstance(ratio, bool)
        or not 0 < ratio <= 1
    ):
        operational_profile = _run_operational_profile(run)
        ratio = (
            operational_profile.context_compaction_threshold
            if operational_profile is not None
            else None
        )
    if ratio is None:
        ratio = SOFT_THRESHOLD
    return max(1, int(effective_budget * ratio))


def _padded_estimate(run: Run, estimated_tokens: int) -> int:
    if run.provider_id == "pgpt":
        return math.ceil(estimated_tokens * PGPT_TOKEN_ESTIMATION_PADDING)
    return estimated_tokens


def _fallback_context_window(run: Run) -> int:
    operational_profile = _run_operational_profile(run)
    if (
        operational_profile is not None
        and operational_profile.context_window is not None
    ):
        return operational_profile.context_window
    return DEFAULT_CONTEXT_WINDOW


def _run_operational_profile(run: Run):
    return model_operational_profile(
        run.provider_id,
        getattr(run, "model_key", None) or run.runtime_model_id,
    )


def _estimate_context(
    prefix_texts: Sequence[str],
    summary: str | None,
    messages: Sequence[Message],
    content_by_message_id: Mapping[str, str],
    tool_schemas: Sequence[Mapping[str, Any]],
    retained_tool_context: str | None,
) -> int:
    total = sum(estimate_text_tokens(text) for text in prefix_texts)
    total += estimate_text_tokens(summary or "")
    total += estimate_text_tokens(retained_tool_context or "")
    total += sum(
        estimate_text_tokens(
            content_by_message_id.get(message.id, message.canonical_text)
        )
        + 6
        for message in messages
    )
    total += estimate_text_tokens(
        json.dumps(list(tool_schemas), ensure_ascii=False, sort_keys=True, default=str)
    )
    return total


def _estimate_provider_messages(
    messages: Sequence[ProviderMessage],
    tool_schemas: Sequence[Mapping[str, Any]],
) -> int:
    total = estimate_text_tokens(
        json.dumps(list(tool_schemas), ensure_ascii=False, sort_keys=True, default=str)
    )
    for message in messages:
        total += estimate_text_tokens(message.content or "") + 6
        if message.tool_calls:
            total += estimate_text_tokens(
                json.dumps(
                    list(message.tool_calls),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
            )
        if message.provider_metadata:
            total += estimate_text_tokens(
                json.dumps(
                    dict(message.provider_metadata),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
            )
        if message.images:
            # Do not count base64 bytes as text tokens, but reserve meaningful
            # space for the provider's image representation.
            total += 1_024 * len(message.images)
    return total


def _provider_message_units(
    messages: Sequence[ProviderMessage],
) -> list[list[ProviderMessage]]:
    """Group assistant tool calls with their following tool results."""

    units: list[list[ProviderMessage]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        unit = [message]
        index += 1
        if message.role == "assistant" and message.tool_calls:
            call_ids = {
                str(call.get("id"))
                for call in message.tool_calls
                if isinstance(call, Mapping) and call.get("id")
            }
            while (
                index < len(messages)
                and messages[index].role == "tool"
                and (
                    not call_ids or str(messages[index].tool_call_id or "") in call_ids
                )
            ):
                unit.append(messages[index])
                index += 1
        units.append(unit)
    return units


def _compact_runtime_payloads(
    messages: Sequence[ProviderMessage],
    *,
    strip_images: bool = False,
) -> tuple[tuple[ProviderMessage, ...], int]:
    """Shrink recoverable Tool payloads without breaking provider JSON contracts."""

    compacted_reversed: list[ProviderMessage] = []
    changed_count = 0
    seen_tool_hashes: set[str] = set()
    for message in reversed(messages):
        updated = message
        original_tool_digest = (
            hashlib.sha256((message.content or "").encode("utf-8")).hexdigest()
            if message.role == "tool" and len(message.content or "") >= 200
            else None
        )
        if message.tool_calls and not message.provider_metadata:
            tool_calls: list[Mapping[str, Any]] = []
            changed = False
            for raw_call in message.tool_calls:
                call = dict(raw_call)
                function = call.get("function")
                if isinstance(function, Mapping):
                    arguments = function.get("arguments")
                    compacted_arguments = _compact_tool_arguments(arguments)
                    if compacted_arguments != arguments:
                        call["function"] = {
                            **function,
                            "arguments": compacted_arguments,
                        }
                        changed = True
                tool_calls.append(call)
            if changed:
                updated = replace(updated, tool_calls=tuple(tool_calls))
                changed_count += 1
        if updated.role == "tool" and len(updated.content or "") > (
            RUNTIME_TOOL_RESULT_HEAD_CHARS + RUNTIME_TOOL_RESULT_TAIL_CHARS
        ):
            content = updated.content or ""
            updated = replace(
                updated,
                content=(
                    "[Tool result compacted for the provider context; the full result "
                    "remains stored in the Run and is recoverable by tool call ID.]\n"
                    f"{content[:RUNTIME_TOOL_RESULT_HEAD_CHARS]}\n"
                    "...[context compacted]...\n"
                    f"{content[-RUNTIME_TOOL_RESULT_TAIL_CHARS:]}"
                ),
            )
            changed_count += 1
        if original_tool_digest is not None:
            if original_tool_digest in seen_tool_hashes:
                updated = replace(
                    updated,
                    content=(
                        "[Duplicate Tool result compacted; the same content appears in a "
                        "more recent Tool call.]"
                    ),
                )
                changed_count += 1
            else:
                seen_tool_hashes.add(original_tool_digest)
        if strip_images and updated.images:
            image_note = f"[{len(updated.images)} historical image(s) removed from context]"
            updated = replace(
                updated,
                content=(
                    f"{updated.content}\n{image_note}" if updated.content else image_note
                ),
                images=(),
            )
            changed_count += 1
        compacted_reversed.append(updated)
    compacted_reversed.reverse()
    return tuple(compacted_reversed), changed_count


def _compact_tool_arguments(arguments: Any) -> Any:
    if not isinstance(arguments, str):
        return arguments
    try:
        parsed = json.loads(arguments)
    except (TypeError, ValueError):
        return arguments

    changed = False

    def shrink(value: Any) -> Any:
        nonlocal changed
        if isinstance(value, str) and len(value) > RUNTIME_TOOL_ARGUMENT_STRING_LIMIT:
            changed = True
            return value[:RUNTIME_TOOL_ARGUMENT_STRING_LIMIT] + "...[context compacted]"
        if isinstance(value, dict):
            return {key: shrink(item) for key, item in value.items()}
        if isinstance(value, list):
            return [shrink(item) for item in value]
        return value

    compacted = shrink(parsed)
    if not changed:
        return arguments
    return json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))


def _runtime_message_summary(message: ProviderMessage) -> str:
    label = message.role
    metadata: list[str] = []
    if message.name:
        metadata.append(f"name={message.name}")
    if message.tool_call_id:
        metadata.append(f"call={message.tool_call_id}")
    if message.tool_calls:
        names = [
            str(
                call.get("name")
                or (
                    call.get("function", {}).get("name")
                    if isinstance(call.get("function"), Mapping)
                    else None
                )
                or "tool"
            )
            for call in message.tool_calls
            if isinstance(call, Mapping)
        ]
        if names:
            metadata.append("calls=" + ",".join(names[:20]))
    suffix = "; " + "; ".join(metadata) if metadata else ""
    content = " ".join((message.content or "").split())
    if not content and message.images:
        content = f"{len(message.images)} image attachment(s)"
    return f"- [{label}{suffix}] {_bounded(content, 900)}"


def _source_message(
    message: Message,
    content_by_message_id: Mapping[str, str],
    source_runs: Mapping[str, Run],
) -> ContextSourceMessage:
    raw_references = message.metadata_json.get("prompt_references", [])
    references = (
        tuple(item for item in raw_references if isinstance(item, Mapping))
        if isinstance(raw_references, list)
        else ()
    )
    source_run = source_runs.get(message.run_id or "")
    return ContextSourceMessage(
        id=message.id,
        role=message.role,
        content=content_by_message_id.get(message.id, message.canonical_text),
        turn_index=message.turn_index,
        run_id=message.run_id,
        idempotency_key=source_run.idempotency_key if source_run else None,
        references=references,
    )


def _source_tool(tool: ToolExecution) -> ContextSourceTool:
    return ContextSourceTool(
        id=tool.id,
        run_id=tool.run_id,
        tool_call_id=tool.tool_call_id,
        tool_name=tool.tool_name,
        status=tool.status,
        input=tool.validated_input_json,
        result=tool.result_json,
        result_summary=tool.result_summary,
        artifact_id=tool.artifact_id,
        idempotency_key=tool.idempotency_key,
        error_code=tool.error_code,
        error_message=tool.error_message,
    )


def _tools_for_messages(
    tools: Sequence[ToolExecution], messages: Sequence[Message]
) -> list[ToolExecution]:
    run_ids = {message.run_id for message in messages if message.run_id}
    return [
        tool
        for tool in tools
        if tool.run_id in run_ids and tool.status in {"completed", "failed"}
    ]


def _tool_context(tools: Sequence[ToolExecution]) -> str | None:
    if not tools:
        return None
    lines = [
        "Recent source-backed tool executions. Preserve side effects and do not "
        "repeat them without checking idempotency."
    ]
    for tool in tools:
        attributes = [
            f"tool={tool.id}",
            f"run={tool.run_id}",
            f"call={tool.tool_call_id}",
            f"name={tool.tool_name}",
            f"status={tool.status}",
        ]
        if tool.idempotency_key:
            attributes.append(f"idempotency={tool.idempotency_key}")
        if tool.artifact_id:
            attributes.append(f"artifact={tool.artifact_id}")
        if tool.error_code:
            attributes.append(f"error={tool.error_code}")
        detail = (
            tool.result_summary
            or tool.error_message
            or _bounded(
                json.dumps(tool.result_json or {}, ensure_ascii=False, sort_keys=True),
                700,
            )
        )
        lines.append(f"- [{'; '.join(attributes)}] {detail}")
    return _bounded("\n".join(lines), 8_000)


def _plan_digest(db: Session, run: Run) -> str:
    plan = db.scalar(select(Plan).where(Plan.run_id == run.id))
    if plan is None:
        return ""
    steps = list(
        db.scalars(
            select(PlanStep)
            .where(PlanStep.plan_id == plan.id)
            .order_by(PlanStep.position, PlanStep.id)
        )
    )
    step_digest = ", ".join(f"{step.step_key}:{step.status}" for step in steps[:12])
    return _bounded(
        f"goal={plan.goal}; status={plan.status}; steps={step_digest}", 1_500
    )


def _source_range(messages: Sequence[Message]) -> dict[str, Any]:
    first = messages[0]
    last = messages[-1]
    return {
        "firstMessageId": first.id,
        "lastMessageId": last.id,
        "firstTurnIndex": first.turn_index,
        "lastTurnIndex": last.turn_index,
        "firstCreatedAt": first.created_at.isoformat(),
        "lastCreatedAt": last.created_at.isoformat(),
    }


def _source_event_range(source_runs: Mapping[str, Run]) -> dict[str, Any]:
    return {
        "runIds": sorted(source_runs),
        "throughSequenceByRun": {
            run_id: source_runs[run_id].last_sequence for run_id in sorted(source_runs)
        },
    }


def _source_refs(
    messages: Sequence[Message], tools: Sequence[ToolExecution]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in messages:
        raw = message.metadata_json.get("prompt_references", [])
        if not isinstance(raw, list):
            continue
        for reference in raw:
            if not isinstance(reference, dict):
                continue
            canonical = json.dumps(
                reference, ensure_ascii=False, sort_keys=True, default=str
            )
            if canonical in seen:
                continue
            seen.add(canonical)
            result.append(dict(reference))
    for tool in tools:
        reference = {
            "kind": "tool_execution",
            "reference_id": tool.id,
            "run_id": tool.run_id,
            "tool_call_id": tool.tool_call_id,
            "tool_name": tool.tool_name,
            "status": tool.status,
            "artifact_id": tool.artifact_id,
            "idempotency_key": tool.idempotency_key,
            "error_code": tool.error_code,
        }
        canonical = json.dumps(reference, ensure_ascii=False, sort_keys=True)
        if canonical not in seen:
            seen.add(canonical)
            result.append(reference)
    return result


def _source_hash(
    messages: Sequence[Message],
    content_by_message_id: Mapping[str, str],
    source_runs: Mapping[str, Run],
    tools: Sequence[ToolExecution],
) -> str:
    payload = {
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "turn_index": message.turn_index,
                "run_id": message.run_id,
                "content": content_by_message_id.get(
                    message.id, message.canonical_text
                ),
            }
            for message in messages
        ],
        "runs": [
            {
                "id": run_id,
                "idempotency_key": source_runs[run_id].idempotency_key,
                "last_sequence": source_runs[run_id].last_sequence,
            }
            for run_id in sorted(source_runs)
        ],
        "tools": [
            {
                "id": tool.id,
                "run_id": tool.run_id,
                "tool_call_id": tool.tool_call_id,
                "tool_name": tool.tool_name,
                "status": tool.status,
                "input": tool.validated_input_json,
                "result": tool.result_json,
                "result_summary": tool.result_summary,
                "artifact_id": tool.artifact_id,
                "idempotency_key": tool.idempotency_key,
                "error_code": tool.error_code,
                "error_message": tool.error_message,
            }
            for tool in tools
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _positive_integer(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return value


def _bounded(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"
