from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from lumina.agent.executor import LocalRunExecutor, _run_limit_violation
from lumina.config import Settings
from lumina.models import Run, utc_now
from lumina.providers import ProviderCapabilities, ProviderRequest
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


def test_sqlite_claim_waiter_wakes_on_signal_without_polling(tmp_path: Path) -> None:
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

        async def claim(_run_id: str):
            nonlocal claim_count
            claim_count += 1
            return "wait" if claim_count == 1 else "stop"

        executor._started = True
        executor._claim = claim  # type: ignore[method-assign]
        task = asyncio.create_task(executor._run_when_claimable("queued-run"))
        await asyncio.sleep(0.25)
        assert claim_count == 1

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
