from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from lumina.agent.executor import LocalRunExecutor, _run_limit_violation
from lumina.config import Settings
from lumina.models import Run, utc_now
from lumina.providers import (
    ProviderCapabilities,
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
        waiters = [asyncio.create_task(broker.wait("run-1", timeout=1)) for _ in range(3)]
        await asyncio.sleep(0)
        await broker.notify("run-1")
        await asyncio.gather(*waiters)
        assert broker._conditions == {}
        assert broker._waiters == {}

        await broker.notify("run-without-listener")
        assert broker._conditions == {}

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

        def run_is_terminal(_run_id: str) -> bool:
            return terminal

        executor._run_is_terminal = run_is_terminal  # type: ignore[assignment]

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
        executor._run_is_terminal = lambda _run_id: False  # type: ignore[assignment]
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
