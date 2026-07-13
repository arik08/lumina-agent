from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path

import pytest

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lumina.agent.executor import LocalRunExecutor
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.context import compact_runtime_messages, prepare_context
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.memories.service import (
    ConservativeMemoryExtractor,
    MemoryExtractionResult,
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
from lumina.providers import ProviderMessage
from lumina.runs.service import run_snapshot
from lumina.providers.types import ProviderCapabilities, ProviderEvent


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
        first = learn_memories_for_run(db, first_run.id)
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
        assert extraction_event.payload_json["extractorVersion"] == (
            "offline-conservative-v2"
        )
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
        repeated = learn_memories_for_run(db, repeated_run.id)
        assert repeated.updated_ids == (korean.id,)
        assert korean.evidence_count == 2
        assert repeated_message.id in korean.source_message_ids_json
        again = learn_memories_for_run(db, repeated_run.id)
        assert again.updated_ids == ()
        assert korean.evidence_count == 2

        conflict_run = _run(
            db,
            user=user,
            project=project,
            conversation=conversation,
            sequence=3,
        )
        _message(
            db,
            run=conflict_run,
            user=user,
            role="user",
            text="답변은 앞으로 항상 영어로 해주세요.",
            turn_index=3,
            offset=1,
        )
        conflict = learn_memories_for_run(db, conflict_run.id)
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
        _message(
            db,
            run=confirm_conflict_run,
            user=user,
            role="user",
            text="답변은 앞으로 항상 한국어로 해주세요.",
            turn_index=4,
            offset=1,
        )
        confirm_conflict = learn_memories_for_run(db, confirm_conflict_run.id)
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
        _message(
            db,
            run=deleted_run,
            user=user,
            role="user",
            text="답변은 앞으로 항상 영어로 해주세요.",
            turn_index=5,
            offset=1,
        )
        deleted_repeat = learn_memories_for_run(db, deleted_run.id)
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
        _message(
            db,
            run=confirm_run,
            user=user,
            role="user",
            text="앞으로 보고서는 항상 HTML로 작성해 주세요.",
            turn_index=6,
            offset=1,
        )
        pending_result = learn_memories_for_run(db, confirm_run.id)
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


def test_conservative_memory_extractor_blocks_prohibited_sensitive_topics() -> None:
    extractor = ConservativeMemoryExtractor()
    from lumina.memories.service import MemorySourceMessage

    sensitive = (
        "앞으로 제 사번은 123456으로 기억해 주세요.",
        "항상 제 건강 진단 결과를 기억해 주세요.",
        "앞으로 제가 지지하는 정당을 기억해 주세요.",
        "항상 제 노조 가입 여부를 기억해 주세요.",
        "항상 api_key=abcdef123456 값을 사용해 주세요.",
        "Always remember that password is abcdef123456.",
        "항상 -----BEGIN PRIVATE KEY----- 값을 기억해 주세요.",
    )
    for index, text in enumerate(sensitive):
        candidates = extractor.extract((MemorySourceMessage(str(index), "run", text),))
        assert not candidates, text


def test_explicit_name_is_stored_by_offline_extractor(tmp_path: Path) -> None:
    user, project, conversation = _configure(tmp_path, "explicit-name-memory")
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
            text="내 이름은 오명철이야. 기억해",
            turn_index=1,
            offset=1,
        )

        result = learn_memories_for_run(
            db,
            run.id,
            extractor=ConservativeMemoryExtractor(),
        )
        assert len(result.created_ids) == 1
        memory = db.get(UserMemory, result.created_ids[0])
        assert memory is not None
        assert memory.category == "user_identity"
        assert memory.normalized_fact == "사용자 이름은 오명철입니다."
        assert memory.display_text == "사용자 이름은 오명철입니다."
        assert memory.conflict_key == "user_name"
        assert memory.source_message_ids_json == [source.id]
        assert memory.extractor_version == "offline-conservative-v2"


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
