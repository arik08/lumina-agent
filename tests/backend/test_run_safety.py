from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
import threading
import time

from lumina.agent import executor as executor_module
from lumina.agent.executor import LocalRunExecutor, _run_limit_violation
from lumina.config import Settings
from lumina.models import Run, utc_now
from lumina.providers import (
    ProviderCapabilities,
    ProviderEvent,
    ProviderRequest,
    ProviderRequestError,
)
from lumina.runs.broker import RunEventBroker
from lumina.runs.safety import normalize_run_safety_settings, run_limit_snapshot


def _run(*, limits: dict[str, object], usage: dict[str, object]) -> Run:
    return Run(
        organization_id="organization",
        project_id="project",
        conversation_id="conversation",
        user_id="user",
        status="model_streaming",
        provider_id="mock",
        model_key="mock-agent",
        runtime_model_id="mock-agent",
        model_display_name="Mock Agent",
        snapshot_json={"limits": limits},
        usage_json=usage,
        started_at=utc_now(),
    )


def test_run_safety_defaults_are_generous_and_invalid_storage_falls_back() -> None:
    normalized = normalize_run_safety_settings(
        {
            "max_model_turns": -1,
            "max_total_tokens": "invalid",
            "max_elapsed_minutes": None,
            "max_cost_usd": 0,
        }
    )
    assert normalized == {
        "max_model_turns": 400,
        "max_total_tokens": 4_000_000,
        "max_elapsed_minutes": 10_080,
        "max_cost_usd": 100.0,
        "yolo_mode": True,
    }
    assert run_limit_snapshot(normalized)["maxElapsedSeconds"] == 604_800


def test_run_limit_violation_checks_turns_tokens_cost_and_elapsed_time() -> None:
    limits = {
        "maxModelTurns": 400,
        "maxTotalTokens": 4_000_000,
        "maxElapsedSeconds": 604_800,
        "maxCostUsd": 100.0,
    }
    turn_run = _run(limits=limits, usage={"model_turns": 400})
    assert _run_limit_violation(turn_run).code == "run_model_turn_limit_reached"

    token_run = _run(
        limits=limits,
        usage={"model_turns": 2, "input_tokens": 3_900_000, "output_tokens": 100_000},
    )
    assert _run_limit_violation(token_run).code == "run_token_limit_reached"

    cost_run = _run(
        limits=limits,
        usage={
            "model_turns": 2,
            "input_tokens": 1,
            "output_tokens": 1,
            "cost_usd": 100.0,
        },
    )
    assert _run_limit_violation(cost_run).code == "run_cost_limit_reached"

    elapsed_run = _run(
        limits=limits,
        usage={"model_turns": 2, "input_tokens": 1, "output_tokens": 1},
    )
    elapsed_run.started_at = utc_now() - timedelta(days=8)
    assert _run_limit_violation(elapsed_run).code == "run_deadline_reached"


def test_executor_cancel_many_actively_cancels_matching_tasks(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'cancel.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    executor = LocalRunExecutor(settings)

    async def exercise() -> None:
        blocker = asyncio.Event()
        first = asyncio.create_task(blocker.wait())
        second = asyncio.create_task(blocker.wait())
        executor._tasks = {"first": first, "second": second}
        assert executor.cancel_many(["first", "missing"]) == 1
        await asyncio.gather(first, return_exceptions=True)
        assert first.cancelled()
        assert not second.cancelled()
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)

    asyncio.run(exercise())


def test_enqueue_keeps_large_waiting_queue_out_of_asyncio_tasks(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'bounded-queue.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    executor = LocalRunExecutor(settings)
    executor._started = True

    for index in range(10_000):
        executor.enqueue(f"queued-{index}")

    assert executor._tasks == {}
    assert executor._claim_revision == 10_000


def test_event_broker_releases_idle_channels_after_waiters_leave() -> None:
    broker = RunEventBroker()

    async def exercise() -> None:
        waiters = [
            asyncio.create_task(broker.wait("run-1", timeout=1)) for _ in range(3)
        ]
        await asyncio.sleep(0)
        await broker.notify("run-1")
        await asyncio.gather(*waiters)
        assert broker._conditions == {}
        assert broker._waiters == {}

        await broker.notify("run-without-listener")
        assert broker._conditions == {}

    asyncio.run(exercise())


def test_run_control_cache_avoids_database_poll_until_invalidated(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            database_url=f"sqlite:///{(tmp_path / 'control-cache.db').as_posix()}",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )
    run_id = "cached-run"
    executor._run_control_cache[run_id] = (
        time.monotonic(),
        "model_streaming",
        None,
        False,
        executor._worker_id,
    )

    def unexpected_database_poll():
        raise AssertionError("fresh control cache must avoid a database poll")

    monkeypatch.setattr(executor_module, "SessionLocal", unexpected_database_poll)
    assert executor._run_control_state(run_id) == (
        "model_streaming",
        None,
        False,
        executor._worker_id,
    )

    class SilentProvider:
        provider_id = "silent"
        capabilities = ProviderCapabilities()

        async def stream(self, _request: ProviderRequest):
            await asyncio.Event().wait()
            yield

    async def exercise_cached_provider_poll() -> None:
        async def consume() -> None:
            async for _event in executor._provider_events(
                run_id,
                SilentProvider(),
                ProviderRequest(model="silent", messages=()),
                first_output_timeout_seconds=0.03,
            ):
                raise AssertionError("A silent Provider must not emit an event")

        result = await asyncio.gather(
            asyncio.create_task(consume()),
            return_exceptions=True,
        )
        assert isinstance(result[0], ProviderRequestError)

    asyncio.run(exercise_cached_provider_poll())
    executor.invalidate_control(run_id)
    try:
        executor._run_control_state(run_id)
    except AssertionError as exc:
        assert "database poll" in str(exc)
    else:
        raise AssertionError("invalidation must force the next database poll")


def test_event_broker_bounds_idle_run_revisions_without_pruning_live_state() -> None:
    broker = RunEventBroker()

    async def exercise() -> None:
        await broker.publish_artifact_progress("live-run", {"tokens": 1})
        for index in range(5_000):
            await broker.notify(f"idle-{index}")

        assert len(broker._wake_revisions) == 4_096
        assert len(broker._durable_revisions) == 4_095
        assert broker.revisions("live-run")[0] > 0
        assert broker.latest_artifact_progress("live-run") == (1, {"tokens": 1})
        assert broker.revisions("idle-0") == (0, 0)
        assert broker.revisions("idle-4999")[0] > 0

    asyncio.run(exercise())


def test_event_broker_keeps_only_latest_transient_artifact_progress() -> None:
    broker = RunEventBroker()

    async def exercise() -> None:
        wake_revision, durable_revision = broker.revisions("run-1")
        assert (wake_revision, durable_revision) == (0, 0)
        await broker.publish_artifact_progress("run-1", {"tokens": 10, "lines": 2})
        transient_wake_revision, transient_durable_revision = broker.revisions("run-1")
        assert transient_wake_revision > wake_revision
        assert transient_durable_revision == durable_revision
        observed_revision, timed_out = await broker.wait(
            "run-1", timeout=1, after_revision=wake_revision
        )
        assert observed_revision == transient_wake_revision
        assert timed_out is False
        first = broker.latest_artifact_progress("run-1")
        assert first == (1, {"tokens": 10, "lines": 2})

        await broker.publish_artifact_progress("run-1", {"tokens": 20, "lines": 3})
        assert broker.latest_artifact_progress("run-1", after_revision=1) == (
            2,
            {"tokens": 20, "lines": 3},
        )
        assert broker.latest_artifact_progress("run-1", after_revision=2) is None
        await broker.notify("run-1")
        durable_wake_revision, next_durable_revision = broker.revisions("run-1")
        assert durable_wake_revision == next_durable_revision
        assert next_durable_revision > transient_durable_revision
        broker.clear_artifact_progress("run-1")
        assert broker.latest_artifact_progress("run-1") is None

    asyncio.run(exercise())


def test_event_broker_keeps_latest_complete_assistant_draft() -> None:
    broker = RunEventBroker()

    async def exercise() -> None:
        broker.seed_assistant_draft("run-1", "message-1", "recovered ")
        await broker.publish_assistant_draft("run-1", "message-1", "first")
        first = broker.latest_assistant_draft("run-1")
        assert first == (
            1,
            {
                "messageId": "message-1",
                "text": "recovered first",
                "append": False,
            },
        )

        await broker.publish_assistant_draft("run-1", "message-1", " second")
        assert broker.latest_assistant_draft("run-1", after_revision=1) == (
            2,
            {"messageId": "message-1", "text": " second", "append": True},
        )
        await broker.replace_assistant_draft("run-1", "message-1", "recovered ")
        assert broker.latest_assistant_draft("run-1", after_revision=2) == (
            3,
            {"messageId": "message-1", "text": "recovered ", "append": False},
        )
        await broker.publish_assistant_draft("run-1", "message-1", "resumed")
        assert broker.latest_assistant_draft("run-1", after_revision=2) == (
            4,
            {
                "messageId": "message-1",
                "text": "recovered resumed",
                "append": False,
            },
        )
        assert broker.latest_assistant_draft("run-1", after_revision=3) == (
            4,
            {"messageId": "message-1", "text": "resumed", "append": True},
        )
        assert broker.latest_assistant_draft("run-1", after_revision=4) is None
        broker.clear_assistant_draft("run-1")
        assert broker.latest_assistant_draft("run-1") is None

    asyncio.run(exercise())


def test_event_broker_compacts_tiny_draft_chunks_without_losing_replay() -> None:
    broker = RunEventBroker()

    async def exercise() -> None:
        for _index in range(1_100):
            await broker.publish_assistant_draft("run-1", "message-1", "x")

        current = broker._assistant_drafts["run-1"]
        assert len(current[3]) <= 1_024
        assert broker.latest_assistant_draft("run-1", after_revision=1) == (
            1_100,
            {"messageId": "message-1", "text": "x" * 1_100, "append": False},
        )
        assert broker.latest_assistant_draft("run-1", after_revision=1_099) == (
            1_100,
            {"messageId": "message-1", "text": "x", "append": True},
        )

    asyncio.run(exercise())


def test_dispatcher_wakes_on_signal_without_per_run_waiter_tasks(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'claim-wait.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    executor = LocalRunExecutor(settings)

    async def exercise() -> None:
        claim_count = 0

        async def claim_next():
            nonlocal claim_count
            claim_count += 1
            if claim_count > 1:
                executor._started = False
            return None

        executor._started = True
        executor._claim_next = claim_next  # type: ignore[method-assign]
        task = asyncio.create_task(executor._dispatch_runs())
        await asyncio.sleep(0.25)
        assert claim_count == 1
        assert executor._tasks == {}

        executor._signal_claim_change()
        await asyncio.wait_for(task, timeout=1)
        assert claim_count == 2
        if executor._background_tasks:
            await asyncio.gather(*executor._background_tasks)

    asyncio.run(exercise())


def test_dispatcher_backs_off_before_restart_after_database_failure(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=f"sqlite:///{(tmp_path / 'dispatcher-backoff.db').as_posix()}",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )
    attempts = 0
    observed_delays: list[float] = []

    async def exercise() -> None:
        nonlocal attempts
        delay_started = asyncio.Event()
        release_delay = asyncio.Event()

        async def fail_recovery() -> None:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("database unavailable")

        async def controlled_sleep(delay: float) -> None:
            observed_delays.append(delay)
            delay_started.set()
            await release_delay.wait()

        monkeypatch.setattr(executor, "_recover_expired_runs", fail_recovery)
        monkeypatch.setattr(executor_module.asyncio, "sleep", controlled_sleep)
        executor._started = True
        dispatcher = asyncio.create_task(executor._dispatch_runs())
        executor._dispatcher_task = dispatcher

        await delay_started.wait()
        assert attempts == 1
        assert observed_delays == [executor_module._DISPATCHER_RESTART_BACKOFF_SECONDS]
        assert executor._dispatcher_task is dispatcher

        executor._started = False
        release_delay.set()
        await dispatcher

    asyncio.run(exercise())


def test_heartbeat_backs_off_before_restart_after_database_failure(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=f"sqlite:///{(tmp_path / 'heartbeat-backoff.db').as_posix()}",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )
    attempts = 0
    observed_delays: list[float] = []

    async def exercise() -> None:
        nonlocal attempts
        backoff_started = asyncio.Event()
        release_backoff = asyncio.Event()

        def fail_session_scope():
            nonlocal attempts
            attempts += 1
            raise RuntimeError("database unavailable")

        async def controlled_sleep(delay: float) -> None:
            observed_delays.append(delay)
            if delay == executor_module._HEARTBEAT_RESTART_BACKOFF_SECONDS:
                backoff_started.set()
                await release_backoff.wait()

        monkeypatch.setattr(executor_module, "session_scope", fail_session_scope)
        monkeypatch.setattr(executor_module.asyncio, "sleep", controlled_sleep)
        executor._started = True
        heartbeat = asyncio.create_task(executor._heartbeat_worker_leases())
        executor._heartbeat_task = heartbeat

        await backoff_started.wait()
        assert attempts == 1
        assert observed_delays == [
            executor_module._WORKER_HEARTBEAT_SECONDS,
            executor_module._HEARTBEAT_RESTART_BACKOFF_SECONDS,
        ]
        assert executor._heartbeat_task is heartbeat

        executor._started = False
        release_backoff.set()
        await heartbeat

    asyncio.run(exercise())


def test_heartbeat_database_write_does_not_block_event_loop(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=f"sqlite:///{(tmp_path / 'heartbeat-offloop.db').as_posix()}",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )

    def slow_heartbeat() -> None:
        time.sleep(0.05)
        executor._started = False

    monkeypatch.setattr(executor, "_heartbeat_worker_leases_database", slow_heartbeat)
    monkeypatch.setattr(executor_module, "_WORKER_HEARTBEAT_SECONDS", 0)

    async def exercise() -> int:
        ticks = 0
        running = True

        async def ticker() -> None:
            nonlocal ticks
            while running:
                ticks += 1
                await asyncio.sleep(0.005)

        executor._started = True
        ticker_task = asyncio.create_task(ticker())
        await executor._heartbeat_worker_leases()
        running = False
        await ticker_task
        return ticks

    assert asyncio.run(exercise()) >= 3


def test_expired_run_recovery_database_work_does_not_block_event_loop(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=f"sqlite:///{(tmp_path / 'recovery-offloop.db').as_posix()}",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )

    def slow_recovery(
        _owned_run_ids: tuple[str, ...],
    ) -> tuple[tuple[str, ...], list[tuple[str, str, str]], bool]:
        time.sleep(0.05)
        return (), [], False

    monkeypatch.setattr(executor, "_recover_expired_runs_database", slow_recovery)

    async def exercise() -> int:
        ticks = 0
        running = True

        async def ticker() -> None:
            nonlocal ticks
            while running:
                ticks += 1
                await asyncio.sleep(0.005)

        ticker_task = asyncio.create_task(ticker())
        await executor._recover_expired_runs()
        running = False
        await ticker_task
        return ticks

    assert asyncio.run(exercise()) >= 3


def test_assistant_text_database_append_does_not_block_event_loop(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=f"sqlite:///{(tmp_path / 'append-offloop.db').as_posix()}",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )

    def slow_append(
        _run_id: str, _message_id: str, _text: str
    ) -> tuple[str | None, bool, bool]:
        time.sleep(0.05)
        return None, False, False

    monkeypatch.setattr(executor, "_append_text_database", slow_append)

    async def exercise() -> int:
        ticks = 0
        running = True

        async def ticker() -> None:
            nonlocal ticks
            while running:
                ticks += 1
                await asyncio.sleep(0.005)

        ticker_task = asyncio.create_task(ticker())
        await executor._append_text("run", "message", "delta")
        running = False
        await ticker_task
        return ticks

    assert asyncio.run(exercise()) >= 3


def test_usage_and_turn_metric_database_writes_do_not_block_event_loop(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=f"sqlite:///{(tmp_path / 'usage-offloop.db').as_posix()}",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )

    def slow_store(_run_id: str, _usage: dict[str, object]) -> None:
        time.sleep(0.05)

    def slow_metrics(_run_id: str, _payload: dict[str, object]) -> None:
        time.sleep(0.05)

    monkeypatch.setattr(executor, "_store_usage_database", slow_store)
    monkeypatch.setattr(executor, "_record_model_turn_metrics_database", slow_metrics)

    async def exercise() -> int:
        ticks = 0
        running = True

        async def ticker() -> None:
            nonlocal ticks
            while running:
                ticks += 1
                await asyncio.sleep(0.005)

        ticker_task = asyncio.create_task(ticker())
        assert await executor._store_usage("run", {"input_tokens": 1}) is None
        await executor._record_model_turn_metrics(
            "run",
            turn_index=0,
            attempt=1,
            requested_effort=None,
            effective_effort=None,
            started_at=utc_now(),
            duration_ms=1.0,
            ttft_ms=None,
            first_visible_text_ms=None,
            status="completed",
            stop_reason=None,
            usage=None,
            static_prefix_estimated_tokens=0,
            system_prompt_estimated_tokens=0,
            tool_schema_estimated_tokens=0,
        )
        running = False
        await ticker_task
        return ticks

    assert asyncio.run(exercise()) >= 6


def test_begin_model_turn_database_write_does_not_block_event_loop(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=(
                f"sqlite:///{(tmp_path / 'begin-turn-offloop.db').as_posix()}"
            ),
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )

    def slow_begin(_run_id: str) -> tuple[None, int, bool]:
        time.sleep(0.05)
        return None, 3, False

    monkeypatch.setattr(executor, "_begin_model_turn_database", slow_begin)

    async def exercise() -> tuple[int, tuple[object, int]]:
        ticks = 0
        running = True

        async def ticker() -> None:
            nonlocal ticks
            while running:
                ticks += 1
                await asyncio.sleep(0.005)

        ticker_task = asyncio.create_task(ticker())
        result = await executor._begin_model_turn("run")
        running = False
        await ticker_task
        return ticks, result

    ticks, result = asyncio.run(exercise())
    assert ticks >= 3
    assert result == (None, 3)


def test_provider_recovery_database_writes_do_not_block_event_loop(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=(
                f"sqlite:///{(tmp_path / 'provider-recovery-offloop.db').as_posix()}"
            ),
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )

    def slow_retry(*_args: object) -> bool:
        time.sleep(0.05)
        return True

    def slow_partial_recovery(*_args: object) -> bool:
        time.sleep(0.05)
        return True

    monkeypatch.setattr(executor, "_schedule_provider_retry_database", slow_retry)
    monkeypatch.setattr(
        executor,
        "_schedule_partial_provider_recovery_database",
        slow_partial_recovery,
    )
    monkeypatch.setattr(
        executor_module,
        "_provider_retry_delay_seconds",
        lambda *_args, **_kwargs: 0.0,
    )
    error = ProviderRequestError(
        "temporary",
        retryable=True,
        stage="network",
        status_code=503,
    )

    async def exercise() -> int:
        ticks = 0
        running = True

        async def ticker() -> None:
            nonlocal ticks
            while running:
                ticks += 1
                await asyncio.sleep(0.005)

        ticker_task = asyncio.create_task(ticker())
        assert await executor._retry_provider_request(
            "run",
            error,
            retry_index=0,
            round_index=0,
            output_started=False,
        )
        assert await executor._recover_partial_provider_response(
            "run",
            error,
            retry_index=0,
            preserved_chars=8,
            has_tool_calls=False,
            tool_call_count=0,
        )
        running = False
        await ticker_task
        return ticks

    assert asyncio.run(exercise()) >= 6


def test_api_and_executor_database_mutations_share_the_same_run_lock(
    tmp_path: Path,
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=f"sqlite:///{(tmp_path / 'shared-run-lock.db').as_posix()}",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )
    mutation_started = threading.Event()

    def mutation() -> None:
        mutation_started.set()

    async def exercise() -> None:
        async with executor.run_database_mutation_lock("run"):
            pending = asyncio.create_task(
                executor._run_database_mutation("run", mutation)
            )
            await asyncio.sleep(0.02)
            assert not mutation_started.is_set()
        await pending
        assert mutation_started.is_set()

    asyncio.run(exercise())


def test_run_control_database_read_does_not_block_event_loop(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=f"sqlite:///{(tmp_path / 'control-offloop.db').as_posix()}",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )

    def slow_control(
        _run_id: str,
    ) -> tuple[str | None, object, bool, str | None]:
        time.sleep(0.05)
        return "running", None, False, "worker"

    monkeypatch.setattr(executor, "_load_run_control_state", slow_control)

    async def exercise() -> int:
        ticks = 0
        running = True

        async def ticker() -> None:
            nonlocal ticks
            while running:
                ticks += 1
                await asyncio.sleep(0.005)

        ticker_task = asyncio.create_task(ticker())
        assert await executor._run_control_state_async("run") == (
            "running",
            None,
            False,
            "worker",
        )
        running = False
        await ticker_task
        return ticks

    assert asyncio.run(exercise()) >= 3


def test_run_control_read_retries_after_concurrent_invalidation(
    monkeypatch, tmp_path: Path
) -> None:
    executor = LocalRunExecutor(
        Settings(
            environment="test",
            DATABASE_URL=f"sqlite:///{(tmp_path / 'control-race.db').as_posix()}",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            cookie_secure=False,
        )
    )
    first_read_started = threading.Event()
    release_first_read = threading.Event()
    reads = 0

    def controlled_read(
        _run_id: str,
    ) -> tuple[str | None, object, bool, str | None]:
        nonlocal reads
        reads += 1
        if reads == 1:
            first_read_started.set()
            release_first_read.wait(timeout=2)
            return "running", None, False, "old-worker"
        return "paused", None, True, "new-worker"

    monkeypatch.setattr(executor, "_load_run_control_state", controlled_read)

    async def exercise() -> tuple[str | None, object, bool, str | None]:
        read_task = asyncio.create_task(executor._run_control_state_async("run"))
        await asyncio.to_thread(first_read_started.wait, 2)
        executor.invalidate_control("run")
        release_first_read.set()
        return await read_task

    assert asyncio.run(exercise()) == ("paused", None, True, "new-worker")
    assert reads == 2


def test_provider_wait_stops_when_database_run_becomes_terminal(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'provider-cancel.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    executor = LocalRunExecutor(settings)
    stream_closed = asyncio.Event()

    class SilentProvider:
        provider_id = "silent"
        capabilities = ProviderCapabilities()

        async def stream(self, _request: ProviderRequest):
            try:
                await asyncio.Event().wait()
                yield
            finally:
                stream_closed.set()

    async def exercise() -> None:
        terminal = False

        executor._run_control_state = lambda _run_id: (  # type: ignore[assignment]
            "completed" if terminal else "model_streaming",
            None,
            False,
            executor._worker_id,
        )

        async def consume() -> None:
            async for _event in executor._provider_events(
                "run-id",
                SilentProvider(),
                ProviderRequest(model="silent", messages=()),
            ):
                raise AssertionError("A silent Provider must not emit an event")

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        terminal = True
        result = await asyncio.wait_for(
            asyncio.gather(task, return_exceptions=True), timeout=0.5
        )
        assert isinstance(result[0], asyncio.CancelledError)
        assert stream_closed.is_set()

    asyncio.run(exercise())


def test_provider_wait_times_out_before_first_event(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'provider-timeout.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    executor = LocalRunExecutor(settings)
    stream_closed = asyncio.Event()

    class SilentProvider:
        provider_id = "silent"
        capabilities = ProviderCapabilities()

        async def stream(self, _request: ProviderRequest):
            try:
                await asyncio.Event().wait()
                yield
            finally:
                stream_closed.set()

    async def exercise() -> None:
        executor._run_control_state = lambda _run_id: (  # type: ignore[assignment]
            "model_streaming",
            None,
            False,
            executor._worker_id,
        )

        async def consume() -> None:
            async for _event in executor._provider_events(
                "run-id",
                SilentProvider(),
                ProviderRequest(model="silent", messages=()),
                first_output_timeout_seconds=0.03,
            ):
                raise AssertionError("A silent Provider must not emit an event")

        result = await asyncio.gather(
            asyncio.create_task(consume()), return_exceptions=True
        )
        assert isinstance(result[0], ProviderRequestError)
        assert result[0].retryable is True
        assert result[0].stage == "first_output"
        assert stream_closed.is_set()

    asyncio.run(exercise())


def test_provider_wait_times_out_after_stream_becomes_idle(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'provider-idle.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    executor = LocalRunExecutor(settings)
    stream_closed = asyncio.Event()

    class PartiallySilentProvider:
        provider_id = "partially-silent"
        capabilities = ProviderCapabilities()

        async def stream(self, _request: ProviderRequest):
            try:
                yield ProviderEvent(
                    type="tool_call_started",
                    tool_call_id="call-id",
                    tool_name="write_file",
                )
                await asyncio.Event().wait()
                yield
            finally:
                stream_closed.set()

    async def exercise() -> None:
        executor._run_control_state = lambda _run_id: (  # type: ignore[assignment]
            "model_streaming",
            None,
            False,
            executor._worker_id,
        )
        events: list[ProviderEvent] = []

        async def consume() -> None:
            async for event in executor._provider_events(
                "run-id",
                PartiallySilentProvider(),
                ProviderRequest(model="partially-silent", messages=()),
                first_output_timeout_seconds=1,
                event_idle_timeout_seconds=0.03,
            ):
                events.append(event)

        result = await asyncio.gather(
            asyncio.create_task(consume()), return_exceptions=True
        )
        assert [event.type for event in events] == ["tool_call_started"]
        assert isinstance(result[0], ProviderRequestError)
        assert result[0].retryable is True
        assert result[0].stage == "stream"
        assert stream_closed.is_set()

    asyncio.run(exercise())
