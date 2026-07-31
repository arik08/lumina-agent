from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from lumina.agent.executor import LocalRunExecutor
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.models import Conversation, Project, Run, User, utc_now
from lumina.runs.state import (
    AWAITING_APPROVAL,
    AWAITING_INPUT,
    PAUSED,
    PREPARING,
    QUEUED,
)


@pytest.mark.parametrize("waiting_status", [AWAITING_APPROVAL, AWAITING_INPUT, PAUSED])
def test_response_waiting_runs_do_not_exhaust_server_execution_slots(
    tmp_path: Path,
    waiting_status: str,
) -> None:
    settings = _settings(
        tmp_path,
        "server-capacity",
        user_concurrency_limit=3,
        server_concurrency_limit=1,
    )
    _prepare_database(settings)

    with SessionLocal.begin() as db:
        user, project = _admin_project(db)
        conversation = _conversation(db, user, project, "Waiting")
        _run(db, user, conversation, status=waiting_status)
        candidate_conversation = _conversation(db, user, project, "Candidate")
        candidate = _run(db, user, candidate_conversation, status=QUEUED)
        candidate_id = candidate.id

    claimed_id = asyncio.run(LocalRunExecutor(settings)._claim_next())

    assert claimed_id == candidate_id
    with SessionLocal() as db:
        claimed = db.get(Run, candidate_id)
        assert claimed is not None and claimed.status == PREPARING
        queue_metrics = claimed.snapshot_json["queueMetrics"]
        assert queue_metrics["claimCount"] == 1
        assert queue_metrics["lastWaitMs"] >= 0
        assert queue_metrics["totalWaitMs"] == queue_metrics["lastWaitMs"]
        assert queue_metrics["maxWaitMs"] == queue_metrics["lastWaitMs"]


@pytest.mark.parametrize("waiting_status", [AWAITING_APPROVAL, AWAITING_INPUT, PAUSED])
def test_response_waiting_runs_do_not_exhaust_user_execution_slots(
    tmp_path: Path,
    waiting_status: str,
) -> None:
    settings = _settings(
        tmp_path,
        "user-capacity",
        user_concurrency_limit=1,
        server_concurrency_limit=12,
    )
    _prepare_database(settings)

    with SessionLocal.begin() as db:
        user, project = _admin_project(db)
        conversation = _conversation(db, user, project, "User waiting")
        _run(db, user, conversation, status=waiting_status)
        candidate_conversation = _conversation(db, user, project, "User candidate")
        candidate = _run(db, user, candidate_conversation, status=QUEUED)
        candidate_id = candidate.id

    claimed_id = asyncio.run(LocalRunExecutor(settings)._claim_next())

    assert claimed_id == candidate_id


@pytest.mark.parametrize("waiting_status", [AWAITING_APPROVAL, AWAITING_INPUT, PAUSED])
def test_response_waiting_run_still_blocks_the_same_conversation(
    tmp_path: Path,
    waiting_status: str,
) -> None:
    settings = _settings(
        tmp_path,
        "conversation-waiting",
        user_concurrency_limit=3,
        server_concurrency_limit=12,
    )
    _prepare_database(settings)

    with SessionLocal.begin() as db:
        user, project = _admin_project(db)
        conversation = _conversation(db, user, project, "Conversation waiting")
        _run(db, user, conversation, status=waiting_status)
        _run(db, user, conversation, status=QUEUED)

    assert asyncio.run(LocalRunExecutor(settings)._claim_next()) is None


@pytest.mark.parametrize(
    ("user_concurrency_limit", "server_concurrency_limit"),
    [(3, 1), (1, 12)],
    ids=("server-slot", "user-slot"),
)
def test_attached_paused_run_keeps_slot_only_until_task_releases_ownership(
    tmp_path: Path,
    user_concurrency_limit: int,
    server_concurrency_limit: int,
) -> None:
    settings = _settings(
        tmp_path,
        "paused-capacity",
        user_concurrency_limit=user_concurrency_limit,
        server_concurrency_limit=server_concurrency_limit,
    )
    _prepare_database(settings)

    with SessionLocal.begin() as db:
        user, project = _admin_project(db)
        paused_conversation = _conversation(db, user, project, "Paused")
        paused = _run(db, user, paused_conversation, status=PAUSED)
        paused.worker_id = "worker-settling-at-safe-boundary"
        paused.heartbeat_at = utc_now()
        paused.lease_expires_at = utc_now() + timedelta(minutes=1)
        candidate_conversation = _conversation(db, user, project, "After paused")
        candidate = _run(db, user, candidate_conversation, status=QUEUED)
        candidate_id = candidate.id

    assert asyncio.run(LocalRunExecutor(settings)._claim_next()) is None

    with SessionLocal.begin() as db:
        paused = db.scalar(select(Run).where(Run.status == PAUSED))
        assert paused is not None
        paused.worker_id = None
        paused.heartbeat_at = None
        paused.lease_expires_at = None

    assert asyncio.run(LocalRunExecutor(settings)._claim_next()) == candidate_id


def test_expired_queued_worker_ownership_is_reclaimed(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        "expired-queued-owner",
        user_concurrency_limit=3,
        server_concurrency_limit=1,
    )
    _prepare_database(settings)

    with SessionLocal.begin() as db:
        user, project = _admin_project(db)
        conversation = _conversation(db, user, project, "Expired queued owner")
        candidate = _run(db, user, conversation, status=QUEUED)
        candidate.worker_id = "worker-that-did-not-finish-cleanup"
        candidate.heartbeat_at = utc_now() - timedelta(minutes=2)
        candidate.lease_expires_at = utc_now() - timedelta(minutes=1)
        candidate_id = candidate.id

    assert asyncio.run(LocalRunExecutor(settings)._claim_next()) == candidate_id


def _settings(
    tmp_path: Path,
    name: str,
    *,
    user_concurrency_limit: int,
    server_concurrency_limit: int,
) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / f'{name}.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
        session_concurrency_limit=1,
        user_concurrency_limit=user_concurrency_limit,
        server_concurrency_limit=server_concurrency_limit,
    )


def _prepare_database(settings: Settings) -> None:
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)


def _admin_project(db: Session) -> tuple[User, Project]:
    user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
    assert user is not None
    project = db.scalar(select(Project).where(Project.owner_user_id == user.id))
    assert project is not None
    return user, project


def _conversation(
    db: Session,
    user: User,
    project: Project,
    title: str,
) -> Conversation:
    conversation = Conversation(
        organization_id=user.organization_id,
        project_id=project.id,
        owner_user_id=user.id,
        title=title,
    )
    db.add(conversation)
    db.flush()
    return conversation


def _run(
    db: Session,
    user: User,
    conversation: Conversation,
    *,
    status: str,
) -> Run:
    run = Run(
        organization_id=user.organization_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        user_id=user.id,
        status=status,
        provider_id="mock",
        model_key="mock-agent",
        runtime_model_id="mock-agent",
        model_display_name="Mock Agent",
        snapshot_json={"user_message_text": conversation.title},
        usage_json={},
    )
    db.add(run)
    db.flush()
    return run
