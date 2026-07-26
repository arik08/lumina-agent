from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from lumina.api.schemas import RunCreate, RunMessageInput
from lumina.agent.executor import (
    LocalRunExecutor,
    _record_web_fetch_provider_context,
    _RunParked,
)
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.models import (
    Conversation,
    Plan,
    PlanStep,
    PlanSubtask,
    Project,
    Run,
    RunEvent,
    ToolExecution,
    User,
    utc_now,
)
from lumina.runs.recovery import (
    mark_model_turn_inflight,
    mark_worker_shutdown_interrupted,
    prepare_worker_recovery,
    queue_paused_run_for_resume,
)
from lumina.runs.broker import event_broker
from lumina.runs.service import (
    complete_plan_step,
    create_run,
    pause_plan,
    start_plan_step,
    transition_run,
)
from lumina.runs.state import (
    AWAITING_APPROVAL,
    COMPLETED,
    FAILED,
    MODEL_STREAMING,
    PAUSED,
    PREPARING,
    QUEUED,
    TOOLS_RUNNING,
)
from lumina.runs.subtasks import bind_tool_subtask, ensure_tool_subtasks


def test_executor_can_restart_on_a_new_event_loop(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "new-event-loop")
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    executor = LocalRunExecutor(settings)

    async def lifecycle() -> None:
        await executor.start()
        await executor.stop()

    asyncio.run(lifecycle())
    asyncio.run(lifecycle())


def test_worker_recovery_rewinds_only_the_inflight_model_draft(tmp_path: Path) -> None:
    run_id = _direct_run(tmp_path, "model-recovery")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        run.assistant_draft = "이전 단계 설명. "
        run.usage_json = {"model_turns": 2, "input_tokens": 30}
        mark_model_turn_inflight(db, run, turn_index=1)
        run.assistant_draft += "전송 중이던 일부 응답"
        db.commit()

    with SessionLocal() as db:
        batch = prepare_worker_recovery(db)
        db.commit()
        assert batch.resumable_run_ids == (run_id,)
        run = db.get(Run, run_id)
        assert run is not None
        assert run.status == QUEUED
        assert run.assistant_draft == "이전 단계 설명. "
        assert run.usage_json["model_turns"] == 1
        assert "model_turn_inflight" not in run.snapshot_json
        assert run.snapshot_json["workerRecoveryCount"] == 1


def test_worker_recovery_never_replays_an_unknown_tool_outcome(tmp_path: Path) -> None:
    run_id = _direct_run(tmp_path, "tool-recovery")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        complete_plan_step(db, run, "model", reason="test_model_completed")
        transition_run(db, run, TOOLS_RUNNING)
        start_plan_step(db, run, "tools", reason="test_tools")
        ensure_tool_subtasks(
            db,
            run,
            [
                {
                    "id": "call-running",
                    "name": "create_report",
                    "arguments": '{"title":"secret-free"}',
                },
                {
                    "id": "call-not-started",
                    "name": "web_search",
                    "arguments": '{"query":"status"}',
                },
            ],
        )
        tool = ToolExecution(
            run_id=run.id,
            tool_call_id="call-running",
            tool_name="create_report",
            validated_input_json={"title": "secret-free"},
            status="running",
            started_at=utc_now(),
        )
        db.add(tool)
        db.flush()
        bind_tool_subtask(db, run.id, tool)
        db.commit()

    with SessionLocal() as db:
        batch = prepare_worker_recovery(db)
        db.commit()
        assert batch.resumable_run_ids == (run_id,)
        run = db.get(Run, run_id)
        assert run is not None and run.status == QUEUED
        tool = db.scalar(select(ToolExecution).where(ToolExecution.run_id == run_id))
        assert tool is not None
        assert tool.status == "failed"
        assert tool.error_code == "worker_restarted_unknown_outcome"
        plan = db.scalar(select(Plan).where(Plan.run_id == run_id))
        assert plan is not None
        tools_step = db.scalar(
            select(PlanStep).where(
                PlanStep.plan_id == plan.id,
                PlanStep.step_key == "tools",
            )
        )
        assert tools_step is not None and tools_step.status == "queued"
        subtasks = list(
            db.scalars(
                select(PlanSubtask)
                .where(PlanSubtask.plan_step_id == tools_step.id)
                .order_by(PlanSubtask.position)
            )
        )
        assert [subtask.status for subtask in subtasks] == ["failed", "failed"]
        assert subtasks[0].error_code == "worker_restarted_unknown_outcome"
        assert subtasks[1].error_code == "worker_restarted_before_execution"


def test_graceful_shutdown_records_interrupted_then_schedules_recovery(
    tmp_path: Path,
) -> None:
    run_id = _direct_run(tmp_path, "graceful-recovery")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        run.snapshot_json = {**run.snapshot_json, "workerId": "worker-current"}
        interrupted = mark_worker_shutdown_interrupted(db, worker_id="worker-current")
        db.commit()
        assert interrupted == (run_id,)
        assert run.status == "interrupted"
        assert run.error_code == "worker_interrupted"
        assert run.snapshot_json["workerRecoverable"] is True

    with SessionLocal() as db:
        batch = prepare_worker_recovery(db)
        db.commit()
        assert batch.resumable_run_ids == (run_id,)
        run = db.get(Run, run_id)
        assert run is not None
        assert run.status == QUEUED
        assert run.error_code is None
        assert "workerRecoverable" not in run.snapshot_json


def test_stale_worker_shutdown_does_not_interrupt_reclaimed_run(
    tmp_path: Path,
) -> None:
    run_id = _direct_run(tmp_path, "stale-worker-shutdown")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        run.snapshot_json = {**run.snapshot_json, "workerId": "worker-new"}
        interrupted = mark_worker_shutdown_interrupted(db, worker_id="worker-old")
        db.commit()

        assert interrupted == ()
        assert run.status == MODEL_STREAMING
        assert run.error_code is None


def test_worker_recovery_respects_live_lease_and_reclaims_expired_lease(
    tmp_path: Path,
) -> None:
    run_id = _direct_run(tmp_path, "lease-recovery")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        run.worker_id = "live-worker"
        run.heartbeat_at = utc_now()
        run.lease_expires_at = utc_now() + timedelta(minutes=1)
        db.commit()

    with SessionLocal() as db:
        assert prepare_worker_recovery(db).resumable_run_ids == ()
        run = db.get(Run, run_id)
        assert run is not None and run.status == MODEL_STREAMING
        run.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

    with SessionLocal() as db:
        assert prepare_worker_recovery(db).resumable_run_ids == (run_id,)
        run = db.get(Run, run_id)
        assert run is not None and run.status == QUEUED
        assert run.worker_id is None
        assert run.heartbeat_at is None
        assert run.lease_expires_at is None


def test_periodic_recovery_skips_live_local_task_but_recovers_untracked_run(
    tmp_path: Path,
) -> None:
    key = "periodic-protected-recovery"
    settings = _settings(tmp_path, key)
    tracked_run_id = _direct_run(tmp_path, key)
    untracked_run_id = _add_run_to_current_database("periodic-untracked")
    executor = LocalRunExecutor(settings)
    expired_at = utc_now() - timedelta(minutes=1)

    with SessionLocal() as db:
        tracked_run = db.get(Run, tracked_run_id)
        untracked_run = db.get(Run, untracked_run_id)
        assert tracked_run is not None and untracked_run is not None
        _move_to_model(db, tracked_run)
        _move_to_model(db, untracked_run)
        tracked_run.worker_id = executor._worker_id
        tracked_run.snapshot_json = {
            **tracked_run.snapshot_json,
            "workerId": executor._worker_id,
        }
        tracked_run.heartbeat_at = expired_at
        tracked_run.lease_expires_at = expired_at
        untracked_run.worker_id = "expired-untracked-worker"
        untracked_run.snapshot_json = {
            **untracked_run.snapshot_json,
            "workerId": "expired-untracked-worker",
        }
        untracked_run.heartbeat_at = expired_at
        untracked_run.lease_expires_at = expired_at
        db.commit()

    async def exercise() -> None:
        async def hold_live_task() -> None:
            await asyncio.Event().wait()

        task = asyncio.create_task(hold_live_task())
        executor._tasks[tracked_run_id] = task
        try:
            executor._next_recovery_sweep_at = 0.0
            await executor._recover_expired_runs()
        finally:
            executor._tasks.pop(tracked_run_id, None)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())

    with SessionLocal() as db:
        tracked_run = db.get(Run, tracked_run_id)
        untracked_run = db.get(Run, untracked_run_id)
        assert tracked_run is not None and untracked_run is not None
        assert tracked_run.status == MODEL_STREAMING
        assert tracked_run.worker_id == executor._worker_id
        assert "workerRecoveryCount" not in tracked_run.snapshot_json
        assert untracked_run.status == QUEUED
        assert untracked_run.worker_id is None
        assert untracked_run.snapshot_json["workerRecoveryCount"] == 1


def test_recovered_run_is_not_reclaimed_by_executor_with_old_live_task(
    tmp_path: Path,
) -> None:
    key = "recovered-run-reclaim-fence"
    settings = _settings(tmp_path, key)
    run_id = _direct_run(tmp_path, key)
    old_executor = LocalRunExecutor(settings)
    new_executor = LocalRunExecutor(settings)
    expired_at = utc_now() - timedelta(minutes=1)

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        run.worker_id = old_executor._worker_id
        run.snapshot_json = {
            **run.snapshot_json,
            "workerId": old_executor._worker_id,
        }
        run.heartbeat_at = expired_at
        run.lease_expires_at = expired_at
        db.commit()

    async def exercise() -> None:
        async def hold_old_task() -> None:
            await asyncio.Event().wait()

        task = asyncio.create_task(hold_old_task())
        old_executor._tasks[run_id] = task
        try:
            with SessionLocal() as db:
                recovery = prepare_worker_recovery(db)
                db.commit()
                assert recovery.resumable_run_ids == (run_id,)

            assert await old_executor._claim_next() is None
            assert await new_executor._claim_next() == run_id
        finally:
            old_executor._tasks.pop(run_id, None)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        assert run.status == PREPARING
        assert run.worker_id == new_executor._worker_id
        assert run.snapshot_json["workerId"] == new_executor._worker_id


def test_periodic_recovery_cancels_local_task_after_owner_changes(
    tmp_path: Path,
) -> None:
    key = "owner-changed-periodic-recovery"
    settings = _settings(tmp_path, key)
    run_id = _direct_run(tmp_path, key)
    executor = LocalRunExecutor(settings)
    expired_at = utc_now() - timedelta(minutes=1)

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        run.worker_id = "second-worker-that-expired"
        run.heartbeat_at = expired_at
        run.lease_expires_at = expired_at
        db.commit()

    async def exercise() -> None:
        task = asyncio.create_task(asyncio.Event().wait())
        executor._tasks[run_id] = task
        try:
            executor._next_recovery_sweep_at = 0.0
            await executor._recover_expired_runs()
            assert task.cancelled()
            assert await executor._claim_next() == run_id
        finally:
            executor._tasks.pop(run_id, None)

    asyncio.run(exercise())


def test_paused_run_cannot_start_a_new_tool_side_effect(tmp_path: Path) -> None:
    key = "paused-tool-start-fence"
    settings = _settings(tmp_path, key)
    run_id = _direct_run(tmp_path, key)
    executor = LocalRunExecutor(settings)

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        transition_run(db, run, PAUSED)
        run.worker_id = executor._worker_id
        run.heartbeat_at = utc_now()
        run.lease_expires_at = utc_now() + timedelta(minutes=1)
        db.commit()

    with pytest.raises(_RunParked):
        asyncio.run(
            executor._execute_tool(
                run_id,
                {
                    "id": "paused-plan-update",
                    "name": "update_plan",
                    "arguments": json.dumps(
                        {"plan": [{"step": "must not run", "status": "in_progress"}]}
                    ),
                },
                "paused request",
            )
        )

    with SessionLocal() as db:
        assert (
            db.scalar(
                select(ToolExecution.id).where(ToolExecution.run_id == run_id)
            )
            is None
        )


def test_stale_executor_cannot_mutate_run_tool_events_or_live_draft(
    tmp_path: Path,
) -> None:
    key = "stale-owner-mutation-fence"
    settings = _settings(tmp_path, key)
    run_id = _direct_run(tmp_path, key)
    stale_executor = LocalRunExecutor(settings)
    current_executor = LocalRunExecutor(settings)

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        complete_plan_step(db, run, "model", reason="test_model_completed")
        transition_run(db, run, TOOLS_RUNNING)
        start_plan_step(db, run, "tools", reason="test_tools")
        run.worker_id = stale_executor._worker_id
        run.snapshot_json = {
            **run.snapshot_json,
            "workerId": stale_executor._worker_id,
        }
        run.heartbeat_at = utc_now()
        run.lease_expires_at = utc_now() + timedelta(minutes=1)
        tool = ToolExecution(
            run_id=run.id,
            tool_call_id="call-owned-by-new-worker",
            tool_name="web_fetch",
            validated_input_json={"title": "stable"},
            status="running",
            result_json={
                "providerContextIncludedChars": 10,
                "source": {"llmTextChars": 10},
            },
            started_at=utc_now(),
        )
        db.add(tool)
        db.commit()
        tool_id = tool.id
        message_id = str(run.snapshot_json["assistant_message_id"])

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        run.worker_id = current_executor._worker_id
        run.snapshot_json = {
            **run.snapshot_json,
            "workerId": current_executor._worker_id,
        }
        run.heartbeat_at = utc_now()
        run.lease_expires_at = utc_now() + timedelta(minutes=1)
        db.commit()

    def durable_state() -> dict[str, object]:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            tool = db.get(ToolExecution, tool_id)
            assert run is not None and tool is not None
            events = list(
                db.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id)
                    .order_by(RunEvent.sequence)
                )
            )
            return {
                "run": (
                    run.status,
                    run.assistant_draft,
                    deepcopy(run.snapshot_json),
                    deepcopy(run.usage_json),
                    run.last_sequence,
                    run.error_code,
                    run.error_message,
                    run.updated_at,
                ),
                "tool": (
                    tool.status,
                    deepcopy(tool.result_json),
                    tool.result_summary,
                    tool.artifact_id,
                    tool.error_code,
                    tool.error_message,
                    tool.finished_at,
                ),
                "events": tuple(
                    (
                        event.id,
                        event.sequence,
                        event.event_type,
                        deepcopy(event.payload_json),
                    )
                    for event in events
                ),
            }

    event_broker.discard(run_id)
    event_broker.seed_assistant_draft(run_id, message_id, "stable live draft")
    durable_before = durable_state()
    broker_before = (
        event_broker.revisions(run_id),
        event_broker.latest_assistant_draft(run_id),
    )

    async def attempt_stale_mutations() -> None:
        with pytest.raises(_RunParked):
            await stale_executor._set_status(run_id, TOOLS_RUNNING)
        with pytest.raises(_RunParked):
            await stale_executor._append_text(run_id, message_id, "stale text")
        with pytest.raises(_RunParked):
            await stale_executor._execute_tool(
                run_id,
                {
                    "id": "stale-plan-update",
                    "name": "update_plan",
                    "arguments": json.dumps(
                        {
                            "plan": [
                                {
                                    "step": "stale worker mutation",
                                    "status": "in_progress",
                                }
                            ]
                        }
                    ),
                },
                "stale worker request",
            )
        with pytest.raises(_RunParked):
            await stale_executor._complete_tool_execution(
                run_id,
                tool_id,
                {"mutated": True},
                "stale completion",
            )
        with pytest.raises(_RunParked):
            await stale_executor._fail_tool_execution(
                run_id,
                tool_id,
                ValueError("stale failure"),
            )
        with pytest.raises(_RunParked):
            _record_web_fetch_provider_context(
                run_id,
                {"call-owned-by-new-worker": 999},
                worker_id=stale_executor._worker_id,
            )

    try:
        asyncio.run(attempt_stale_mutations())
        assert durable_state() == durable_before
        assert (
            event_broker.revisions(run_id),
            event_broker.latest_assistant_draft(run_id),
        ) == broker_before
    finally:
        event_broker.discard(run_id)


def test_paused_worker_recovery_parks_then_resume_requeues_from_safe_checkpoint(
    tmp_path: Path,
) -> None:
    run_id = _direct_run(tmp_path, "paused-recovery")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        run.assistant_draft = "보존된 답변. "
        run.usage_json = {"model_turns": 2}
        mark_model_turn_inflight(db, run, turn_index=1)
        run.assistant_draft += "전송 중 일부"
        run.snapshot_json = {
            **run.snapshot_json,
            "resume_status": MODEL_STREAMING,
        }
        transition_run(db, run, PAUSED)
        pause_plan(db, run)
        run.worker_id = "worker-before-restart"
        run.heartbeat_at = utc_now() - timedelta(minutes=2)
        run.lease_expires_at = utc_now() - timedelta(minutes=1)
        db.commit()

    with SessionLocal() as db:
        batch = prepare_worker_recovery(db)
        db.commit()
        assert batch.resumable_run_ids == ()
        assert batch.waiting_run_ids == (run_id,)
        run = db.get(Run, run_id)
        assert run is not None and run.status == PAUSED
        assert run.worker_id is None
        assert run.snapshot_json["paused_worker_detached"]["reason"] == (
            "worker_recovery"
        )
        assert run.assistant_draft == "보존된 답변. 전송 중 일부"
        assert "model_turn_inflight" in run.snapshot_json

        assert queue_paused_run_for_resume(db, run) is True
        db.commit()
        assert run.status == QUEUED
        assert run.assistant_draft == "보존된 답변. "
        assert run.usage_json["model_turns"] == 1
        assert "model_turn_inflight" not in run.snapshot_json
        assert "paused_worker_detached" not in run.snapshot_json
        rewind_event = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "assistant_draft_rewound",
            )
        )
        assert rewind_event is not None
        assert rewind_event.payload_json == {
            "messageId": run.snapshot_json["assistant_message_id"],
            "text": "보존된 답변. ",
            "retainedCharacters": len("보존된 답변. "),
            "revision": 1,
        }
        plan = db.scalar(select(Plan).where(Plan.run_id == run.id))
        assert plan is not None and plan.status == "active"
        model_step = db.scalar(
            select(PlanStep).where(
                PlanStep.plan_id == plan.id,
                PlanStep.step_key == "model",
            )
        )
        assert model_step is not None and model_step.status == "queued"


def test_malformed_paused_tool_checkpoint_fails_without_replaying_tools(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "paused-checkpoint-invalid")
    run_id = _direct_run(tmp_path, "paused-checkpoint-invalid")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        complete_plan_step(db, run, "model", reason="test_model_completed")
        transition_run(db, run, TOOLS_RUNNING)
        start_plan_step(db, run, "tools", reason="test_tools")
        run.snapshot_json = {
            **run.snapshot_json,
            "resume_status": TOOLS_RUNNING,
            "tool_checkpoint": {
                "version": 1,
                "kind": "paused_tools",
                "assistant_content": None,
                "calls": [
                    {
                        "id": "call-invalid-paused-checkpoint",
                        "name": "update_plan",
                        "arguments": '{"plan":[]}',
                        "provider_metadata": {},
                    }
                ],
                "provider_tool_contents": [],
            },
        }
        transition_run(db, run, PAUSED)
        pause_plan(db, run)
        queue_paused_run_for_resume(db, run)
        db.commit()

    executor = LocalRunExecutor(settings)
    assert asyncio.run(executor._claim_next()) == run_id
    executor._started = True
    try:
        asyncio.run(executor._run_claimed(run_id))
    finally:
        executor._started = False

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None and run.status == FAILED
        assert run.error_code == "pause_checkpoint_invalid"
        assert (
            db.scalar(
                select(ToolExecution.id).where(ToolExecution.run_id == run_id)
            )
            is None
        )


def test_sqlite_database_allows_only_one_live_run_executor(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "single-live-executor")
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    owner = LocalRunExecutor(settings)
    contender = LocalRunExecutor(settings)

    async def exercise() -> None:
        await owner.start()
        try:
            with pytest.raises(RuntimeError, match="SQLite database"):
                await contender.start()
        finally:
            await owner.stop()

        await contender.start()
        await contender.stop()

    asyncio.run(exercise())


def test_executor_start_recovers_model_turn_and_parks_approval(tmp_path: Path) -> None:
    recovered_run_id = _direct_run(tmp_path, "executor-recovery")
    with SessionLocal() as db:
        recovered = db.get(Run, recovered_run_id)
        assert recovered is not None
        _move_to_model(db, recovered)
        recovered.assistant_draft = "전송 중 응답"
        recovered.usage_json = {"model_turns": 1}
        mark_model_turn_inflight(db, recovered, turn_index=0)
        db.commit()

    approval_run_id = _add_run_to_current_database("approval-parked")
    with SessionLocal() as db:
        approval = db.get(Run, approval_run_id)
        assert approval is not None
        _move_to_model(db, approval)
        transition_run(db, approval, AWAITING_APPROVAL)
        approval.snapshot_json = {
            **approval.snapshot_json,
            "tool_checkpoint": {"approval_ids": ["pending"]},
        }
        db.commit()

    executor = LocalRunExecutor(_settings(tmp_path, "executor-recovery"))

    async def exercise() -> None:
        await executor.start()
        for _ in range(200):
            with SessionLocal() as db:
                status = db.scalar(select(Run.status).where(Run.id == recovered_run_id))
            if status == COMPLETED:
                break
            await asyncio.sleep(0.01)
        assert status == COMPLETED
        with SessionLocal() as db:
            approval_status = db.scalar(
                select(Run.status).where(Run.id == approval_run_id)
            )
        assert approval_status == AWAITING_APPROVAL
        await executor.stop()

    asyncio.run(exercise())

    with SessionLocal() as db:
        recovered = db.get(Run, recovered_run_id)
        assert recovered is not None
        assert recovered.snapshot_json["workerId"] == executor._worker_id
        approval = db.get(Run, approval_run_id)
        assert approval is not None and approval.status == AWAITING_APPROVAL


def _direct_run(tmp_path: Path, key: str) -> str:
    settings = _settings(tmp_path, key)
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    return _add_run_to_current_database(key)


def _settings(tmp_path: Path, key: str) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / f'{key}.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _add_run_to_current_database(key: str) -> str:
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        project = db.scalar(select(Project).where(Project.owner_user_id == admin.id))
        assert admin is not None and project is not None
        conversation = Conversation(
            organization_id=admin.organization_id,
            project_id=project.id,
            owner_user_id=admin.id,
            title="Worker recovery",
        )
        db.add(conversation)
        db.flush()
        run, _message, _created = create_run(
            db,
            user=admin,
            conversation_id=conversation.id,
            payload=RunCreate(message=RunMessageInput(text="복구 테스트")),
            idempotency_key=f"run-{key}",
        )
        db.commit()
        return run.id


def _move_to_model(db, run: Run) -> None:
    transition_run(db, run, PREPARING)
    start_plan_step(db, run, "prepare", reason="test_preparing")
    complete_plan_step(db, run, "prepare", reason="test_prepared")
    transition_run(db, run, MODEL_STREAMING)
    start_plan_step(db, run, "model", reason="test_model")
