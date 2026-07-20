from __future__ import annotations

import asyncio
from datetime import timedelta
import json
from pathlib import Path

import pytest

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lumina.agent.executor import LocalRunExecutor
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.context import (
    CURRENT_RUN_CONTEXT_METADATA_KEY,
    compact_runtime_messages,
    prepare_context,
)
from lumina.context import service as context_service
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.memories.service import (
    MemoryCandidate,
    MemoryExtractionResult,
    PreparedMemoryExtractor,
    learn_memories_for_run,
    optimize_memories_with_llm,
    patch_memory,
    select_relevant_memories,
)
from lumina.models import (
    CompactedContextEntry,
    Conversation,
    Message,
    Project,
    Run,
    RunEvent,
    ToolExecution,
    User,
    UserMemory,
    utc_now,
)
from lumina.providers import ProviderImage, ProviderMessage
from lumina.runs.service import create_run_plan, run_snapshot
from lumina.providers.types import ProviderCapabilities, ProviderEvent


def _inline_extractor(
    message: Message,
    *,
    category: str,
    fact: str,
    conflict_key: str | None,
    confidence: float = 0.98,
) -> PreparedMemoryExtractor:
    return PreparedMemoryExtractor(
        (
            MemoryCandidate(
                category=category,
                fact=fact,
                display_text=fact,
                confidence=confidence,
                conflict_key=conflict_key,
                source_message_ids=(message.id,),
            ),
        )
    )


def _configure(tmp_path: Path, name: str) -> tuple[User, Project, Conversation]:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(root / 'lumina.db').as_posix()}",
        data_dir=root,
        files_dir=root / "files",
        artifacts_dir=root / "artifacts",
        cookie_secure=False,
    )
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert user is not None
        project = db.scalar(select(Project).where(Project.owner_user_id == user.id))
        assert project is not None
        conversation = Conversation(
            organization_id=user.organization_id,
            project_id=project.id,
            owner_user_id=user.id,
            title="Context and Memory contract",
        )
        db.add(conversation)
        db.commit()
        db.refresh(user)
        db.refresh(project)
        db.refresh(conversation)
        db.expunge_all()
        return user, project, conversation


def _run(
    db: Session,
    *,
    user: User,
    project: Project,
    conversation: Conversation,
    sequence: int,
    status: str = "completed",
    memory_mode: str = "auto",
    context_window: int = 32_000,
) -> Run:
    now = utc_now() + timedelta(seconds=sequence)
    run = Run(
        organization_id=user.organization_id,
        project_id=project.id,
        conversation_id=conversation.id,
        user_id=user.id,
        status=status,
        provider_id="mock",
        model_key="mock-agent",
        runtime_model_id="mock-agent",
        model_display_name="Mock",
        effort="medium",
        approval_mode="yolo",
        environment_type="local_worker",
        snapshot_json={
            "memory_learning_mode": memory_mode,
            "execution": {
                "capabilities": {
                    "context_window": context_window,
                    "max_output_tokens": 256,
                }
            },
        },
        usage_json={},
        assistant_draft="",
        current_turn=1,
        last_sequence=0,
        max_turns=20,
        idempotency_key=f"run-{sequence}",
        queued_at=now,
        started_at=now,
        finished_at=now if status == "completed" else None,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    db.flush()
    return run


def _message(
    db: Session,
    *,
    run: Run,
    user: User,
    role: str,
    text: str,
    turn_index: int,
    offset: int,
) -> Message:
    created = run.created_at + timedelta(milliseconds=offset)
    message = Message(
        conversation_id=run.conversation_id,
        run_id=run.id,
        author_user_id=user.id if role == "user" else None,
        role=role,
        status="completed",
        canonical_text=text,
        turn_index=turn_index,
        metadata_json={},
        created_at=created,
        updated_at=created,
    )
    db.add(message)
    db.flush()
    return message


def test_memory_context_is_pinned_per_turn_without_mutating_user_text(
    tmp_path: Path,
) -> None:
    name = "memory-prefix"
    user, project, conversation = _configure(tmp_path, name)
    with SessionLocal() as db:
        user = db.merge(user)
        project = db.merge(project)
        conversation = db.merge(conversation)
        first = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=1,
        )
        first.snapshot_json = {
            **first.snapshot_json,
            "user_memories": [
                {
                    "id": "memory-one",
                    "category": "preference",
                    "display_text": "첫 번째 턴 메모리",
                }
            ],
        }
        _message(
            db,
            run=first,
            user=user,
            role="user",
            text="첫 번째 질문",
            turn_index=1,
            offset=0,
        )
        _message(
            db,
            run=first,
            user=user,
            role="assistant",
            text="첫 번째 답변",
            turn_index=1,
            offset=1,
        )
        second = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=2,
        )
        second.snapshot_json = {
            **second.snapshot_json,
            "user_memories": [
                {
                    "id": "memory-two",
                    "category": "preference",
                    "display_text": "두 번째 턴 메모리",
                }
            ],
        }
        _message(
            db,
            run=second,
            user=user,
            role="user",
            text="두 번째 질문",
            turn_index=2,
            offset=0,
        )
        second_id = second.id
        db.commit()

    root = tmp_path / name
    messages = LocalRunExecutor(
        Settings(
            environment="test",
            database_url=f"sqlite:///{(root / 'lumina.db').as_posix()}",
            data_dir=root,
            files_dir=root / "files",
            artifacts_dir=root / "artifacts",
        )
    )._conversation_messages(second_id, "두 번째 질문")
    first_user_index = next(
        index
        for index, message in enumerate(messages)
        if message.role == "user" and message.content == "첫 번째 질문"
    )
    assert messages[0].role == "system"
    assert "Clarification mode:" in str(messages[0].content)
    current_context_index = next(
        index
        for index, message in enumerate(messages)
        if message.role == "system"
        and "memory-two" in str(message.content)
    )
    current_user_index = next(
        index
        for index, message in enumerate(messages)
        if message.role == "user" and message.content == "두 번째 질문"
    )
    assert first_user_index < current_context_index < current_user_index
    assert messages[current_context_index].provider_metadata.get(
        CURRENT_RUN_CONTEXT_METADATA_KEY
    ) is True
    assert messages[current_user_index].provider_metadata.get(
        CURRENT_RUN_CONTEXT_METADATA_KEY
    ) is True
    relevant = [
        (message.role, str(message.content))
        for message in messages
        if any(
            marker in str(message.content)
            for marker in (
                "memory-one",
                "memory-two",
                "첫 번째 질문",
                "첫 번째 답변",
                "두 번째 질문",
            )
        )
    ]

    assert [role for role, _content in relevant] == [
        "system",
        "user",
        "assistant",
        "system",
        "user",
    ]
    assert relevant[1][1] == "첫 번째 질문"
    assert relevant[4][1] == "두 번째 질문"
    assert "memory-one" in relevant[0][1]
    assert "memory-two" in relevant[3][1]


def test_compaction_is_recoverable_and_preserves_tool_side_effects(
    tmp_path: Path,
) -> None:
    user, project, conversation = _configure(tmp_path, "compaction")
    with SessionLocal() as db:
        user = db.merge(user)
        project = db.merge(project)
        conversation = db.merge(conversation)
        history: list[Message] = []
        runs: list[Run] = []
        for index in range(6):
            run = _run(
                db,
                user=user,
                project=project,
                conversation=conversation,
                sequence=index + 1,
                context_window=2_500,
            )
            runs.append(run)
            history.extend(
                (
                    _message(
                        db,
                        run=run,
                        user=user,
                        role="user",
                        text=f"Request {index}: " + ("source detail " * 320),
                        turn_index=index + 1,
                        offset=1,
                    ),
                    _message(
                        db,
                        run=run,
                        user=user,
                        role="assistant",
                        text=f"Answer {index}: " + ("verified result " * 320),
                        turn_index=index + 1,
                        offset=2,
                    ),
                )
            )
        terminal_tool = ToolExecution(
            run_id=runs[0].id,
            tool_call_id="call-side-effect",
            tool_name="create_report",
            validated_input_json={"format": "html"},
            status="completed",
            result_json={"artifact_id": "artifact-contract-001", "version": 1},
            result_summary="HTML report created and validated.",
            artifact_id="artifact-contract-001",
            idempotency_key="tool-idempotency-001",
            started_at=runs[0].created_at,
            finished_at=runs[0].created_at + timedelta(seconds=1),
        )
        incomplete_tool = ToolExecution(
            run_id=runs[1].id,
            tool_call_id="call-still-running",
            tool_name="external_write",
            validated_input_json={"target": "pending"},
            status="running",
            idempotency_key="tool-idempotency-pending",
            started_at=runs[1].created_at,
        )
        db.add_all((terminal_tool, incomplete_tool))
        db.flush()
        original_message_ids = {message.id for message in history}
        current_run = runs[-1]
        prepared = prepare_context(
            db,
            run=current_run,
            history=history,
            content_by_message_id={
                message.id: message.canonical_text for message in history
            },
            prefix_texts=("System contract",),
            tool_schemas=({"name": "create_report"},),
        )
        db.flush()

        assert prepared.compaction is not None
        assert prepared.compaction.status == "active"
        assert prepared.summary is not None
        assert "artifact-contract-001" in prepared.summary
        assert "tool-idempotency-001" in prepared.summary
        assert prepared.compaction.estimated_tokens_after < (
            prepared.compaction.estimated_tokens_before * 0.9
        )
        assert prepared.compaction.context_window == 2_500
        assert len(prepared.compaction.source_hash) == 64
        assert prepared.compaction.prompt_version == "context-compaction-v1"
        assert prepared.compaction.summary_model == "offline-conservative-v1"
        assert any(
            reference.get("reference_id") == terminal_tool.id
            and reference.get("artifact_id") == "artifact-contract-001"
            and reference.get("idempotency_key") == "tool-idempotency-001"
            for reference in prepared.compaction.source_refs_json
        )
        incomplete_message_ids = {
            message.id for message in history if message.run_id == runs[1].id
        }
        assert incomplete_message_ids <= set(prepared.retained_message_ids)
        assert incomplete_message_ids.isdisjoint(
            prepared.compaction.source_message_ids_json
        )
        assert len(set(prepared.retained_message_ids) & original_message_ids) >= 4
        assert db.scalar(select(func.count(Message.id))) == len(original_message_ids)

        snapshot = run_snapshot(db, current_run)
        snapshot_entry = snapshot["contextCompactions"][0]
        assert snapshot_entry["sourceHash"] == prepared.compaction.source_hash
        assert snapshot_entry["sourceMessageIds"] == (
            prepared.compaction.source_message_ids_json
        )
        event_types = set(
            db.scalars(
                select(RunEvent.event_type).where(RunEvent.run_id == current_run.id)
            )
        )
        assert "context_compacted" in event_types

        second = prepare_context(
            db,
            run=current_run,
            history=history,
            content_by_message_id={
                message.id: message.canonical_text for message in history
            },
            prefix_texts=("System contract",),
            tool_schemas=({"name": "create_report"},),
        )
        assert second.compaction is not None
        assert second.compaction.id == prepared.compaction.id
        assert db.scalar(select(func.count(CompactedContextEntry.id))) == 1


def test_compaction_failure_keeps_the_existing_full_context(tmp_path: Path) -> None:
    user, project, conversation = _configure(tmp_path, "fallback")

    class FailingSummarizer:
        def summarize(self, _request: object) -> object:
            raise RuntimeError("offline summarizer failure")

    with SessionLocal() as db:
        user = db.merge(user)
        project = db.merge(project)
        conversation = db.merge(conversation)
        run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=1,
            context_window=1_000,
        )
        history = [
            _message(
                db,
                run=run,
                user=user,
                role="user" if index % 2 == 0 else "assistant",
                text="critical original context " * 300,
                turn_index=index // 2 + 1,
                offset=index,
            )
            for index in range(8)
        ]
        prepared = prepare_context(
            db,
            run=run,
            history=history,
            content_by_message_id={
                message.id: message.canonical_text for message in history
            },
            prefix_texts=(),
            tool_schemas=(),
            summarizer=FailingSummarizer(),  # type: ignore[arg-type]
        )
        assert prepared.summary is None
        assert set(prepared.retained_message_ids) == {message.id for message in history}
        failed_entry = db.scalar(select(CompactedContextEntry))
        assert failed_entry is not None
        assert failed_entry.status == "failed"
        assert failed_entry.retrieval_policy == "original_context_retained"
        assert failed_entry.estimated_tokens_after == (
            failed_entry.estimated_tokens_before
        )
        assert failed_entry.cooldown_until > failed_entry.compacted_at
        assert db.scalar(select(func.count(Message.id))) == len(history)
        assert (
            db.scalar(
                select(func.count(RunEvent.id)).where(
                    RunEvent.run_id == run.id,
                    RunEvent.event_type == "context_compaction_failed",
                )
            )
            == 1
        )


def test_incremental_compaction_keeps_cumulative_source_lineage(
    tmp_path: Path,
) -> None:
    user, project, conversation = _configure(tmp_path, "incremental-lineage")
    with SessionLocal() as db:
        user = db.merge(user)
        project = db.merge(project)
        conversation = db.merge(conversation)
        first_run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=1,
            context_window=1_500,
        )
        first_history = [
            _message(
                db,
                run=first_run,
                user=user,
                role="user" if index % 2 == 0 else "assistant",
                text=f"first segment {index} " * 220,
                turn_index=index // 2 + 1,
                offset=index,
            )
            for index in range(8)
        ]
        first_history[0].metadata_json = {
            "prompt_references": [{"kind": "file", "reference_id": "old-ref"}]
        }
        first = prepare_context(
            db,
            run=first_run,
            history=first_history,
            content_by_message_id={
                message.id: message.canonical_text for message in first_history
            },
            prefix_texts=(),
            tool_schemas=(),
        )
        assert first.compaction is not None
        assert first.compaction.status == "active"
        first_source_ids = list(first.compaction.source_message_ids_json)
        first_range = dict(first.compaction.source_message_range_json)
        first_hash = first.compaction.source_hash

        second_run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=2,
            context_window=1_500,
        )
        new_history = [
            _message(
                db,
                run=second_run,
                user=user,
                role="user" if index % 2 == 0 else "assistant",
                text=f"second segment {index} " * 220,
                turn_index=5 + index // 2,
                offset=index,
            )
            for index in range(8)
        ]
        second = prepare_context(
            db,
            run=second_run,
            history=new_history,
            content_by_message_id={
                message.id: message.canonical_text for message in new_history
            },
            prefix_texts=(),
            tool_schemas=(),
            now=first.compaction.cooldown_until + timedelta(seconds=1),
        )

        assert second.compaction is not None
        assert second.compaction.status == "active"
        assert second.compaction.parent_compaction_id == first.compaction.id
        assert set(first_source_ids) < set(second.compaction.source_message_ids_json)
        assert (
            second.compaction.source_message_range_json["firstMessageId"]
            == (first_range["firstMessageId"])
        )
        assert second.compaction.source_message_range_json["lastMessageId"] in {
            message.id for message in new_history
        }
        assert any(
            reference.get("reference_id") == "old-ref"
            for reference in second.compaction.source_refs_json
        )
        assert second.compaction.source_hash != first_hash


def test_runtime_compaction_preserves_recent_tool_pairs_and_marks_summary(
    tmp_path: Path,
) -> None:
    user, project, conversation = _configure(tmp_path, "runtime-compaction")
    with SessionLocal() as db:
        run = _run(
            db,
            user=db.merge(user),
            project=db.merge(project),
            conversation=db.merge(conversation),
            sequence=1,
            context_window=2_500,
        )
        messages = [ProviderMessage(role="system", content="System contract")]
        for index in range(6):
            call_id = f"call-{index}"
            messages.extend(
                (
                    ProviderMessage(
                        role="assistant",
                        content=f"Research round {index} " * 120,
                        tool_calls=(
                            {
                                "id": call_id,
                                "name": "web_search",
                                "arguments": '{"query":"context compaction"}',
                            },
                        ),
                    ),
                    ProviderMessage(
                        role="tool",
                        name="web_search",
                        tool_call_id=call_id,
                        content=f"Result {index} " * 180,
                    ),
                )
            )

        prepared = compact_runtime_messages(run, messages, ({"name": "web_search"},))

    assert prepared.compacted is True
    assert prepared.estimated_tokens_after < prepared.estimated_tokens_before
    assert prepared.messages[0].role == "system"
    assert prepared.messages[1].content is not None
    assert prepared.messages[1].content.startswith("[Compacted runtime context]")
    retained = prepared.messages[2:]
    assert len(retained) == 6
    for index in range(0, len(retained), 2):
        assistant = retained[index]
        tool = retained[index + 1]
        assert assistant.role == "assistant" and assistant.tool_calls
        assert tool.role == "tool"
        assert tool.tool_call_id == assistant.tool_calls[0]["id"]


@pytest.mark.parametrize("force", (False, True))
def test_runtime_compaction_preserves_current_run_required_context(
    tmp_path: Path,
    force: bool,
) -> None:
    user, project, conversation = _configure(
        tmp_path, f"runtime-required-context-{force}"
    )
    with SessionLocal() as db:
        run = _run(
            db,
            user=db.merge(user),
            project=db.merge(project),
            conversation=db.merge(conversation),
            sequence=1,
            context_window=2_500,
        )
        marker = {CURRENT_RUN_CONTEXT_METADATA_KEY: True}
        messages = [ProviderMessage(role="system", content="Stable system contract")]
        for index in range(5):
            messages.extend(
                (
                    ProviderMessage(
                        role="user",
                        content=f"old question {index} " * 120,
                    ),
                    ProviderMessage(
                        role="assistant",
                        content=f"old answer {index} " * 120,
                    ),
                )
            )
        required = (
            ProviderMessage(
                role="system",
                content="CURRENT DYNAMIC CONTRACT " * 120,
                provider_metadata=marker,
            ),
            ProviderMessage(
                role="system",
                content="CURRENT RETAINED TOOL CONTEXT " * 80,
                provider_metadata=marker,
            ),
            ProviderMessage(
                role="system",
                content="CURRENT RECALLED MEMORY " * 80,
                provider_metadata=marker,
            ),
            ProviderMessage(
                role="user",
                content="CURRENT USER REQUEST " * 80,
                provider_metadata=marker,
            ),
        )
        messages.extend(required)
        for index in range(5):
            messages.extend(
                (
                    ProviderMessage(
                        role="assistant",
                        content=f"tool round {index}",
                        tool_calls=(
                            {
                                "id": f"call-{index}",
                                "name": "web_search",
                                "arguments": '{"query":"cache context"}',
                            },
                        ),
                    ),
                    ProviderMessage(
                        role="tool",
                        name="web_search",
                        tool_call_id=f"call-{index}",
                        content=f"large result {index} " * 180,
                    ),
                )
            )

        prepared = compact_runtime_messages(
            run,
            messages,
            ({"name": "web_search"},),
            force=force,
        )

    assert prepared.compacted is True
    for required_message in required:
        assert required_message in prepared.messages
        assert next(
            message
            for message in prepared.messages
            if message is required_message
        ).content == required_message.content
    required_indices = [prepared.messages.index(message) for message in required]
    assert required_indices == list(
        range(required_indices[0], required_indices[0] + len(required))
    )
    assert prepared.estimated_tokens_after < prepared.estimated_tokens_before


def test_runtime_compaction_shrinks_oversized_recent_tool_pair_as_valid_json(
    tmp_path: Path,
) -> None:
    user, project, conversation = _configure(tmp_path, "runtime-large-tool-pair")
    with SessionLocal() as db:
        run = _run(
            db,
            user=db.merge(user),
            project=db.merge(project),
            conversation=db.merge(conversation),
            sequence=1,
            context_window=2_500,
        )
        call_id = "call-large-write"
        messages = [
            ProviderMessage(role="system", content="System contract"),
            ProviderMessage(
                role="system",
                content="[Compacted runtime context]\nEarlier verified decision.",
            ),
            ProviderMessage(role="user", content="Create the requested file."),
            ProviderMessage(
                role="assistant",
                tool_calls=(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps(
                                {
                                    "path": "outputs/report.html",
                                    "content": "large generated document " * 1_500,
                                }
                            ),
                        },
                    },
                ),
            ),
            ProviderMessage(
                role="tool",
                name="write_file",
                tool_call_id=call_id,
                content="stored file result " * 1_500,
            ),
        ]

        prepared = compact_runtime_messages(run, messages, ({"name": "write_file"},))

    assert prepared.compacted is True
    assert prepared.compacted_payload_count == 2
    assert prepared.estimated_tokens_after < prepared.estimated_tokens_before
    assert prepared.estimated_tokens_after <= int(
        prepared.effective_input_budget * 0.75
    )
    assert any(
        "Earlier verified decision" in str(message.content)
        for message in prepared.messages
    )
    assert [message.role for message in prepared.messages[-3:]] == [
        "user",
        "assistant",
        "tool",
    ]
    assistant = prepared.messages[-2]
    tool = prepared.messages[-1]
    assert tool.tool_call_id == assistant.tool_calls[0]["id"]
    arguments = json.loads(assistant.tool_calls[0]["function"]["arguments"])
    assert arguments["path"] == "outputs/report.html"
    assert arguments["content"].endswith("...[context compacted]")
    assert "full result remains stored" in str(tool.content)


def test_runtime_compaction_microcompacts_old_tool_payload_before_summarizing(
    tmp_path: Path,
) -> None:
    user, project, conversation = _configure(tmp_path, "runtime-microcompact")
    with SessionLocal() as db:
        run = _run(
            db,
            user=db.merge(user),
            project=db.merge(project),
            conversation=db.merge(conversation),
            sequence=1,
            context_window=12_000,
        )
        messages = [ProviderMessage(role="system", content="System contract")]
        for index in range(4):
            call_id = f"call-{index}"
            messages.extend(
                (
                    ProviderMessage(
                        role="assistant",
                        content=f"Round {index}",
                        tool_calls=(
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": "web_search",
                                    "arguments": json.dumps(
                                        {"query": f"topic {index}"}
                                    ),
                                },
                            },
                        ),
                    ),
                    ProviderMessage(
                        role="tool",
                        name="web_search",
                        tool_call_id=call_id,
                        content=(
                            ("old oversized evidence " * 1_500)
                            if index == 0
                            else f"short result {index}"
                        ),
                    ),
                )
            )

        prepared = compact_runtime_messages(run, messages, ({"name": "web_search"},))

    assert prepared.compacted is True
    assert prepared.compacted_message_count == 0
    assert prepared.compacted_payload_count == 1
    assert prepared.estimated_tokens_after < prepared.estimated_tokens_before
    assert [message.role for message in prepared.messages] == [
        "system",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    assert not any(
        str(message.content or "").startswith("[Compacted runtime context]")
        for message in prepared.messages
    )
    assert "full result remains stored" in str(prepared.messages[2].content)


def test_runtime_payload_compaction_deduplicates_old_results_and_removes_images() -> (
    None
):
    repeated = "same external result " * 200
    messages = (
        ProviderMessage(
            role="tool",
            name="browser_capture",
            tool_call_id="older",
            content=repeated,
            images=(ProviderImage(mime_type="image/png", data_base64="aGVsbG8="),),
        ),
        ProviderMessage(
            role="tool",
            name="browser_capture",
            tool_call_id="newer",
            content=repeated,
        ),
    )

    compacted, changed = context_service._compact_runtime_payloads(
        messages, strip_images=True
    )

    assert changed >= 2
    assert "Duplicate Tool result" in str(compacted[0].content)
    assert "historical image" in str(compacted[0].content)
    assert compacted[0].images == ()
    assert "full result remains stored" in str(compacted[1].content)


def test_provider_message_estimate_counts_provider_metadata() -> None:
    plain = ProviderMessage(role="assistant", content="tool call")
    signed = ProviderMessage(
        role="assistant",
        content="tool call",
        provider_metadata={"call-1": {"thought_signature": "s" * 8_000}},
    )

    plain_tokens = context_service._estimate_provider_messages((plain,), ())
    signed_tokens = context_service._estimate_provider_messages((signed,), ())

    assert signed_tokens > plain_tokens + 1_000


def test_read_tool_result_pages_full_result_from_same_run(tmp_path: Path) -> None:
    name = "tool-result-readback"
    user, project, conversation = _configure(tmp_path, name)
    with SessionLocal() as db:
        run = _run(
            db,
            user=db.merge(user),
            project=db.merge(project),
            conversation=db.merge(conversation),
            sequence=1,
            status="tools_running",
        )
        create_run_plan(db, run, goal="read stored Tool result")
        db.add(
            ToolExecution(
                run_id=run.id,
                tool_call_id="source-call",
                tool_name="mcp_get_records",
                status="completed",
                result_json={"content": "record " * 3_000},
                result_summary="records",
                started_at=utc_now(),
                finished_at=utc_now(),
            )
        )
        db.commit()
        run_id = run.id

    root = tmp_path / name
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            database_url=f"sqlite:///{(root / 'lumina.db').as_posix()}",
            data_dir=root,
            files_dir=root / "files",
            artifacts_dir=root / "artifacts",
            cookie_secure=False,
        )
    )
    result = asyncio.run(
        executor._execute_tool(
            run_id,
            {
                "id": "readback-call",
                "name": "read_tool_result",
                "arguments": json.dumps(
                    {"tool_call_id": "source-call", "offset": 0, "limit": 1_000}
                ),
            },
            "read stored result",
            mcp_tools={"mcp_get_records": object()},
        )
    )

    assert result["toolCallId"] == "source-call"
    assert result["hasMore"] is True
    assert result["nextOffset"] == 1_000
    assert len(result["content"]) == 1_000
    assert result["untrustedExternalContent"] is True
    with SessionLocal() as db:
        readback = db.scalar(
            select(ToolExecution).where(
                ToolExecution.run_id == run_id,
                ToolExecution.tool_call_id == "readback-call",
            )
        )
        assert readback is not None and readback.status == "completed"


def test_context_window_budget_avoids_character_only_compaction(tmp_path: Path) -> None:
    user, project, conversation = _configure(tmp_path, "large-context-window")
    with SessionLocal() as db:
        user = db.merge(user)
        project = db.merge(project)
        conversation = db.merge(conversation)
        run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=1,
            context_window=200_000,
        )
        history = [
            _message(
                db,
                run=run,
                user=user,
                role="user" if index % 2 == 0 else "assistant",
                text="large but still within the model token budget " * 600,
                turn_index=index // 2 + 1,
                offset=index,
            )
            for index in range(8)
        ]
        prepared = prepare_context(
            db,
            run=run,
            history=history,
            content_by_message_id={
                message.id: message.canonical_text for message in history
            },
            prefix_texts=("System contract",),
            tool_schemas=(),
        )
        assert prepared.compaction is None
        assert set(prepared.retained_message_ids) == {message.id for message in history}
        assert prepared.effective_input_budget > prepared.estimated_tokens
        assert db.scalar(select(func.count(CompactedContextEntry.id))) == 0


def test_pgpt_gpt54_uses_myharness_large_context_budget(
    tmp_path: Path,
) -> None:
    user, project, conversation = _configure(tmp_path, "pgpt-context-budget")
    with SessionLocal() as db:
        run = _run(
            db,
            user=db.merge(user),
            project=db.merge(project),
            conversation=db.merge(conversation),
            sequence=1,
            context_window=1_050_000,
        )
        run.provider_id = "pgpt"
        run.runtime_model_id = "gpt-5.4"
        prepared = compact_runtime_messages(
            run,
            (ProviderMessage(role="user", content="short context"),),
            (),
        )

    assert prepared.compacted is False
    assert prepared.effective_input_budget >= 990_000
    assert prepared.estimated_tokens_before == 16


def test_reactive_runtime_compaction_forces_recovery_below_soft_threshold(
    tmp_path: Path,
) -> None:
    user, project, conversation = _configure(tmp_path, "reactive-context-recovery")
    with SessionLocal() as db:
        run = _run(
            db,
            user=db.merge(user),
            project=db.merge(project),
            conversation=db.merge(conversation),
            sequence=1,
            context_window=1_050_000,
        )
        run.provider_id = "pgpt"
        run.runtime_model_id = "gpt-5.4"
        messages = tuple(
            ProviderMessage(
                role="user" if index % 2 == 0 else "assistant",
                content=f"turn {index}: " + ("context " * 200),
            )
            for index in range(8)
        )

        automatic = compact_runtime_messages(run, messages, ())
        reactive = compact_runtime_messages(run, messages, (), force=True)

    assert automatic.compacted is False
    assert reactive.compacted is True
    assert reactive.compacted_message_count == 7
    assert reactive.preserved_message_count == 1
    assert reactive.estimated_tokens_after < reactive.estimated_tokens_before


@pytest.mark.parametrize(
    "model_id",
    ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
)
def test_codex_36k_context_uses_272k_budget_without_compaction(
    tmp_path: Path,
    model_id: str,
) -> None:
    user, project, conversation = _configure(tmp_path, f"codex-36k-context-{model_id}")
    with SessionLocal() as db:
        user = db.merge(user)
        project = db.merge(project)
        conversation = db.merge(conversation)
        run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=1,
        )
        run.provider_id = "codex"
        run.model_key = model_id
        run.runtime_model_id = model_id
        run.snapshot_json = {"execution": {"capabilities": {}}}
        run.usage_json = {"input_tokens": 36_175}
        history = [
            _message(
                db,
                run=run,
                user=user,
                role="user" if index % 2 == 0 else "assistant",
                text="cache-stable conversation context " * 120,
                turn_index=index // 2 + 1,
                offset=index,
            )
            for index in range(8)
        ]

        prepared = prepare_context(
            db,
            run=run,
            history=history,
            content_by_message_id={
                message.id: message.canonical_text for message in history
            },
            prefix_texts=("Stable system contract",),
            tool_schemas=(),
        )

        assert prepared.compaction is None
        assert prepared.estimated_tokens == 36_175
        assert prepared.effective_input_budget > 250_000
        assert set(prepared.retained_message_ids) == {message.id for message in history}
        assert db.scalar(select(func.count(CompactedContextEntry.id))) == 0


def test_codex_luna_runtime_tool_loop_does_not_compact_at_36k(tmp_path: Path) -> None:
    user, project, conversation = _configure(tmp_path, "codex-luna-runtime-36k")
    with SessionLocal() as db:
        run = _run(
            db,
            user=db.merge(user),
            project=db.merge(project),
            conversation=db.merge(conversation),
            sequence=1,
        )
        run.provider_id = "codex"
        run.model_key = "gpt-5.6-luna"
        run.runtime_model_id = "gpt-5.6-luna"
        run.snapshot_json = {"execution": {"capabilities": {"context_window": 32_000}}}
        messages = (
            ProviderMessage(role="system", content="Stable system contract"),
            ProviderMessage(role="user", content="cache-stable input " * 5_200),
        )

        prepared = compact_runtime_messages(run, messages, ())

    assert 35_000 <= prepared.estimated_tokens_before <= 40_000
    assert prepared.effective_input_budget > 250_000
    assert prepared.compacted is False
    assert prepared.messages == messages


def test_codex_context_keeps_raw_prefix_past_default_75_percent_threshold(
    tmp_path: Path,
) -> None:
    user, project, conversation = _configure(tmp_path, "codex-85-percent-threshold")
    with SessionLocal() as db:
        user = db.merge(user)
        project = db.merge(project)
        conversation = db.merge(conversation)
        run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=1,
        )
        run.provider_id = "codex"
        run.model_key = "gpt-5.6-terra"
        run.runtime_model_id = "gpt-5.6-terra"
        run.snapshot_json = {"execution": {"capabilities": {}}}
        run.usage_json = {"input_tokens": 210_000}
        history = [
            _message(
                db,
                run=run,
                user=user,
                role="user" if index % 2 == 0 else "assistant",
                text="cache lineage must stay stable " * 120,
                turn_index=index // 2 + 1,
                offset=index,
            )
            for index in range(8)
        ]

        prepared = prepare_context(
            db,
            run=run,
            history=history,
            content_by_message_id={
                message.id: message.canonical_text for message in history
            },
            prefix_texts=("Stable system contract",),
            tool_schemas=(),
        )

        assert prepared.compaction is None
        assert prepared.estimated_tokens == 210_000
        assert db.scalar(select(func.count(CompactedContextEntry.id))) == 0


@pytest.mark.parametrize(
    ("provider_id", "model_id", "minimum_budget"),
    [
        ("openai", "gpt-5.6-terra", 1_000_000),
        ("google", "gemini-3.1-pro", 900_000),
        ("anthropic", "claude-sonnet-5", 850_000),
        ("anthropic", "claude-haiku-4-5", 130_000),
    ],
)
def test_standard_api_models_do_not_inherit_codex_context_cap(
    tmp_path: Path,
    provider_id: str,
    model_id: str,
    minimum_budget: int,
) -> None:
    user, project, conversation = _configure(
        tmp_path, f"standard-api-{provider_id}-{model_id}"
    )
    with SessionLocal() as db:
        run = _run(
            db,
            user=db.merge(user),
            project=db.merge(project),
            conversation=db.merge(conversation),
            sequence=1,
        )
        run.provider_id = provider_id
        run.model_key = model_id
        run.runtime_model_id = model_id
        run.snapshot_json = {"execution": {"capabilities": {}}}

        prepared = compact_runtime_messages(
            run,
            (ProviderMessage(role="user", content="short context"),),
            (),
        )

        assert prepared.compacted is False
        assert prepared.effective_input_budget >= minimum_budget


def test_automatic_memory_learning_merge_conflict_delete_and_modes(
    tmp_path: Path,
) -> None:
    user, project, conversation = _configure(tmp_path, "memory")
    with SessionLocal() as db:
        user = db.merge(user)
        project = db.merge(project)
        conversation = db.merge(conversation)

        first_run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=1,
        )
        first_message = _message(
            db,
            run=first_run,
            user=user,
            role="user",
            text="답변은 항상 한국어로 해주세요.",
            turn_index=1,
            offset=1,
        )
        _message(
            db,
            run=first_run,
            user=user,
            role="assistant",
            text="Always answer in English.",
            turn_index=1,
            offset=2,
        )
        first = learn_memories_for_run(
            db,
            first_run.id,
            extractor=_inline_extractor(
                first_message,
                category="communication_preference",
                fact="답변 언어로 한국어를 선호합니다.",
                conflict_key="response_language",
            ),
        )
        assert first.mode == "auto"
        assert len(first.created_ids) == 1
        korean = db.get(UserMemory, first.created_ids[0])
        assert korean is not None
        assert korean.status == "active"
        assert korean.conflict_key == "response_language"
        assert korean.source_message_ids_json == [first_message.id]
        extraction_event = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == first_run.id,
                RunEvent.event_type == "memory_extraction_completed",
            )
        )
        assert extraction_event is not None
        assert extraction_event.payload_json["extractorVersion"] == "llm-inline-v1"
        assert extraction_event.payload_json["createdIds"] == [korean.id]

        repeated_run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=2,
        )
        repeated_message = _message(
            db,
            run=repeated_run,
            user=user,
            role="user",
            text="답변은 항상 한국어로 해주세요.",
            turn_index=2,
            offset=1,
        )
        repeated_extractor = _inline_extractor(
            repeated_message,
            category="communication_preference",
            fact="답변 언어로 한국어를 선호합니다.",
            conflict_key="response_language",
        )
        repeated = learn_memories_for_run(
            db, repeated_run.id, extractor=repeated_extractor
        )
        assert repeated.updated_ids == (korean.id,)
        assert korean.evidence_count == 2
        assert repeated_message.id in korean.source_message_ids_json
        again = learn_memories_for_run(
            db, repeated_run.id, extractor=repeated_extractor
        )
        assert again.updated_ids == ()
        assert korean.evidence_count == 2

        conflict_run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=3,
        )
        conflict_message = _message(
            db,
            run=conflict_run,
            user=user,
            role="user",
            text="답변은 앞으로 항상 영어로 해주세요.",
            turn_index=3,
            offset=1,
        )
        conflict = learn_memories_for_run(
            db,
            conflict_run.id,
            extractor=_inline_extractor(
                conflict_message,
                category="communication_preference",
                fact="답변 언어로 영어를 선호합니다.",
                conflict_key="response_language",
            ),
        )
        english = db.get(UserMemory, conflict.created_ids[0])
        assert english is not None
        assert english.status == "active"
        assert english.supersedes_memory_id == korean.id
        assert korean.status == "superseded"

        confirm_conflict_run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=4,
            memory_mode="confirm",
        )
        confirm_conflict_message = _message(
            db,
            run=confirm_conflict_run,
            user=user,
            role="user",
            text="답변은 앞으로 항상 한국어로 해주세요.",
            turn_index=4,
            offset=1,
        )
        confirm_conflict = learn_memories_for_run(
            db,
            confirm_conflict_run.id,
            extractor=_inline_extractor(
                confirm_conflict_message,
                category="communication_preference",
                fact="답변 언어로 한국어를 선호합니다.",
                conflict_key="response_language",
            ),
        )
        pending_language = db.get(UserMemory, confirm_conflict.pending_ids[0])
        assert pending_language is not None
        assert pending_language.status == "pending"
        assert pending_language.supersedes_memory_id == english.id
        patch_memory(
            db,
            user=user,
            memory_id=pending_language.id,
            changes={"status": "active"},
        )
        assert pending_language.status == "active"
        assert english.status == "superseded"

        english.status = "deleted"
        english.deleted_at = utc_now()
        deleted_run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=5,
        )
        deleted_message = _message(
            db,
            run=deleted_run,
            user=user,
            role="user",
            text="답변은 앞으로 항상 영어로 해주세요.",
            turn_index=5,
            offset=1,
        )
        deleted_repeat = learn_memories_for_run(
            db,
            deleted_run.id,
            extractor=_inline_extractor(
                deleted_message,
                category="communication_preference",
                fact="답변 언어로 영어를 선호합니다.",
                conflict_key="response_language",
            ),
        )
        assert deleted_repeat.created_ids == ()
        assert english.status == "deleted"

        confirm_run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=6,
            memory_mode="confirm",
        )
        confirm_message = _message(
            db,
            run=confirm_run,
            user=user,
            role="user",
            text="앞으로 보고서는 항상 HTML로 작성해 주세요.",
            turn_index=6,
            offset=1,
        )
        pending_result = learn_memories_for_run(
            db,
            confirm_run.id,
            extractor=_inline_extractor(
                confirm_message,
                category="output_preference",
                fact="보고서는 HTML 형식을 선호합니다.",
                conflict_key="report_output",
            ),
        )
        assert pending_result.mode == "confirm"
        pending = db.get(UserMemory, pending_result.pending_ids[0])
        assert pending is not None and pending.status == "pending"
        accepted = patch_memory(
            db,
            user=user,
            memory_id=pending.id,
            changes={"status": "active"},
        )
        assert accepted.status == "active"

        off_run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=7,
            memory_mode="off",
        )
        _message(
            db,
            run=off_run,
            user=user,
            role="user",
            text="항상 자세하게 답변해 주세요.",
            turn_index=7,
            offset=1,
        )
        off = learn_memories_for_run(db, off_run.id)
        assert off == MemoryExtractionResult("off", (), (), (), 0)
        assert (
            db.scalar(
                select(func.count(RunEvent.id)).where(
                    RunEvent.run_id == off_run.id,
                    RunEvent.event_type.like("memory_extraction%"),
                )
            )
            == 0
        )


def test_general_inline_llm_fact_is_stored_without_local_extraction(
    tmp_path: Path,
) -> None:
    user, project, conversation = _configure(tmp_path, "inline-memory")
    with SessionLocal() as db:
        user = db.merge(user)
        project = db.merge(project)
        conversation = db.merge(conversation)
        run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=1,
        )
        source = _message(
            db,
            run=run,
            user=user,
            role="user",
            text="저는 주말마다 등산을 합니다.",
            turn_index=1,
            offset=1,
        )

        result = learn_memories_for_run(
            db,
            run.id,
            extractor=_inline_extractor(
                source,
                category="recurring_rule",
                fact="사용자는 주말마다 등산합니다.",
                conflict_key="weekend_activity",
                confidence=0.94,
            ),
        )
        assert len(result.created_ids) == 1
        memory = db.get(UserMemory, result.created_ids[0])
        assert memory is not None
        assert memory.category == "recurring_rule"
        assert memory.normalized_fact == "사용자는 주말마다 등산합니다."
        assert memory.display_text == "사용자는 주말마다 등산합니다."
        assert memory.conflict_key == "weekend_activity"
        assert memory.source_message_ids_json == [source.id]
        assert memory.extractor_version == "llm-inline-v1"


def test_memory_retrieval_selects_relevant_subset_with_core_preferences(
    tmp_path: Path,
) -> None:
    user, _project, _conversation = _configure(tmp_path, "memory-retrieval")
    with SessionLocal() as db:
        user = db.merge(user)
        rows = (
            UserMemory(
                user_id=user.id,
                category="user_identity",
                normalized_fact="the user's name is 오명철",
                display_text="Name: 오명철",
                conflict_key="user_name",
                source_message_ids_json=[],
                source_run_ids_json=[],
                confidence=1.0,
                evidence_count=1,
                status="active",
                extractor_version="test",
            ),
            UserMemory(
                user_id=user.id,
                category="communication_preference",
                normalized_fact="response language: korean",
                display_text="답변은 한국어로 제공합니다.",
                conflict_key="response_language",
                source_message_ids_json=[],
                source_run_ids_json=[],
                confidence=0.9,
                evidence_count=2,
                status="active",
                extractor_version="test",
            ),
            UserMemory(
                user_id=user.id,
                category="user_role",
                normalized_fact="user role: 설비 엔지니어",
                display_text="사용자는 설비 엔지니어입니다.",
                conflict_key="user_role",
                source_message_ids_json=[],
                source_run_ids_json=[],
                confidence=0.9,
                evidence_count=1,
                status="active",
                extractor_version="test",
            ),
            UserMemory(
                user_id=user.id,
                category="output_preference",
                normalized_fact="보고서는 html 형식을 선호",
                display_text="보고서는 HTML 형식을 선호합니다.",
                conflict_key="report_output",
                source_message_ids_json=[],
                source_run_ids_json=[],
                confidence=0.8,
                evidence_count=1,
                status="active",
                extractor_version="test",
            ),
            UserMemory(
                user_id=user.id,
                category="recurring_rule",
                normalized_fact="회의는 월요일 오전",
                display_text="정기 회의는 월요일 오전입니다.",
                conflict_key=None,
                source_message_ids_json=[],
                source_run_ids_json=[],
                confidence=0.8,
                evidence_count=1,
                status="active",
                extractor_version="test",
            ),
        )
        db.add_all(rows)
        db.flush()
        selected = select_relevant_memories(
            db,
            user_id=user.id,
            query="설비 점검 결과를 HTML 보고서로 작성해 주세요.",
        )
        assert len(selected) == 4
        assert {memory.category for memory in selected} == {
            "communication_preference",
            "user_identity",
            "user_role",
            "output_preference",
        }
        assert all(memory.display_text != rows[-1].display_text for memory in selected)


@pytest.mark.asyncio
async def test_llm_memory_optimizer_merges_provenance_and_supersedes_sources(
    tmp_path: Path,
) -> None:
    user, _project, _conversation = _configure(tmp_path, "memory-optimizer")

    class Provider:
        provider_id = "test"
        capabilities = ProviderCapabilities(structured_output=True)

        async def stream(self, request):
            assert request.temperature is None
            assert request.metadata == {"purpose": "user_memory_optimization"}
            yield ProviderEvent(
                type="text_delta",
                text=json.dumps(
                    {
                        "merges": [
                            {
                                "sourceMemoryIds": [first.id, second.id],
                                "category": "output_preference",
                                "fact": "reports should use html",
                                "displayText": "보고서는 HTML 형식을 선호합니다.",
                                "conflictKey": "report_output",
                                "confidence": 0.96,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            )

    with SessionLocal() as db:
        user = db.merge(user)
        first = UserMemory(
            user_id=user.id,
            category="output_preference",
            normalized_fact="html 보고서 선호",
            display_text="HTML 보고서를 선호합니다.",
            source_message_ids_json=["m1"],
            source_run_ids_json=["r1"],
            confidence=0.9,
            evidence_count=2,
            status="active",
            extractor_version="test",
        )
        second = UserMemory(
            user_id=user.id,
            category="output_preference",
            normalized_fact="보고서는 html",
            display_text="보고서 형식은 HTML입니다.",
            source_message_ids_json=["m2"],
            source_run_ids_json=["r2"],
            confidence=0.8,
            evidence_count=1,
            status="active",
            extractor_version="test",
        )
        db.add_all((first, second))
        db.flush()
        result = await optimize_memories_with_llm(
            db, user=user, provider=Provider(), model="test-model"
        )
        assert len(result.merged_ids) == 1
        merged = db.get(UserMemory, result.merged_ids[0])
        assert merged is not None
        assert merged.source_message_ids_json == ["m1", "m2"]
        assert merged.source_run_ids_json == ["r1", "r2"]
        assert merged.evidence_count == 3
        assert merged.normalized_fact == "보고서는 html 형식을 선호합니다."
        assert merged.display_text == "보고서는 HTML 형식을 선호합니다."
        assert merged.extractor_version == "llm-memory-optimizer-v1"
        assert first.status == second.status == "superseded"
