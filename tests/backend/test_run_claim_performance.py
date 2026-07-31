from __future__ import annotations

import asyncio
from pathlib import Path
import threading
import time
import uuid

import pytest
from sqlalchemy import insert, select

from lumina.agent.executor import LocalRunExecutor
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.models import Conversation, Project, Run, User, utc_now


def test_queue_claim_handles_same_timestamp_burst(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'queue-burst.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
        session_concurrency_limit=1,
        user_concurrency_limit=3,
        server_concurrency_limit=12,
    )
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    queued_at = utc_now()
    count = 5_000

    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert user is not None
        project = db.scalar(select(Project).where(Project.owner_user_id == user.id))
        assert project is not None
        conversations: list[dict[str, object]] = []
        runs: list[dict[str, object]] = []
        for index in range(count):
            conversation_id = str(uuid.uuid4())
            conversations.append(
                {
                    "id": conversation_id,
                    "organization_id": user.organization_id,
                    "project_id": project.id,
                    "owner_user_id": user.id,
                    "title": f"Queue burst {index}",
                    "created_at": queued_at,
                    "updated_at": queued_at,
                }
            )
            runs.append(
                {
                    "id": str(uuid.uuid4()),
                    "organization_id": user.organization_id,
                    "project_id": project.id,
                    "conversation_id": conversation_id,
                    "user_id": user.id,
                    "status": "queued",
                    "provider_id": "mock",
                    "model_key": "mock-agent",
                    "runtime_model_id": "mock-agent",
                    "model_display_name": "Mock Agent",
                    "snapshot_json": {},
                    "usage_json": {},
                    "queued_at": queued_at,
                }
            )
        db.execute(insert(Conversation), conversations)
        db.execute(insert(Run), runs)

    started = time.perf_counter()
    claimed_id = asyncio.run(LocalRunExecutor(settings)._claim_next())
    claim_seconds = time.perf_counter() - started

    assert claimed_id is not None
    assert claim_seconds < 2.0


def test_queue_claim_database_work_does_not_block_event_loop(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'queue-offloop.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    executor = LocalRunExecutor(settings)

    def slow_claim(_live_run_ids: tuple[str, ...]) -> None:
        time.sleep(0.05)

    monkeypatch.setattr(executor, "_claim_next_database", slow_claim)

    async def exercise() -> int:
        ticks = 0
        running = True

        async def ticker() -> None:
            nonlocal ticks
            while running:
                ticks += 1
                await asyncio.sleep(0.005)

        ticker_task = asyncio.create_task(ticker())
        assert await executor._claim_next() is None
        running = False
        await ticker_task
        return ticks

    assert asyncio.run(exercise()) >= 3


def test_queue_claim_cancellation_waits_for_database_transaction(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'queue-cancel.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    executor = LocalRunExecutor(settings)
    claim_started = threading.Event()
    release_claim = threading.Event()

    def slow_claim(_live_run_ids: tuple[str, ...]) -> None:
        claim_started.set()
        release_claim.wait(timeout=2)

    monkeypatch.setattr(executor, "_claim_next_database", slow_claim)

    async def exercise() -> None:
        claim_task = asyncio.create_task(executor._claim_next())
        await asyncio.to_thread(claim_started.wait, 2)
        claim_task.cancel()
        await asyncio.sleep(0.01)
        assert not claim_task.done()
        release_claim.set()
        with pytest.raises(asyncio.CancelledError):
            await claim_task

    asyncio.run(exercise())
