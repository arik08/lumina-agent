from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from lumina.agent.executor import LocalRunExecutor
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.models import Conversation, Project, Run, User
from lumina.runs.state import (
    AWAITING_APPROVAL,
    AWAITING_INPUT,
    PAUSED,
    PREPARING,
    QUEUED,
)


def test_response_waiting_runs_do_not_exhaust_server_execution_slots(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        "server-capacity",
        user_concurrency_limit=20,
        server_concurrency_limit=12,
    )
    _prepare_database(settings)

    with SessionLocal.begin() as db:
        user, project = _admin_project(db)
        waiting_statuses = (AWAITING_APPROVAL, AWAITING_INPUT)
        for index in range(12):
            conversation = _conversation(db, user, project, f"Waiting {index}")
            _run(
                db,
                user,
                conversation,
                status=waiting_statuses[index % len(waiting_statuses)],
            )
        candidate_conversation = _conversation(db, user, project, "Candidate")
        candidate = _run(db, user, candidate_conversation, status=QUEUED)
        candidate_id = candidate.id

    claimed_id = asyncio.run(LocalRunExecutor(settings)._claim_next())

    assert claimed_id == candidate_id
    with SessionLocal() as db:
        claimed = db.get(Run, candidate_id)
        assert claimed is not None and claimed.status == PREPARING


def test_response_waiting_runs_do_not_exhaust_user_execution_slots(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        "user-capacity",
        user_concurrency_limit=3,
        server_concurrency_limit=12,
    )
    _prepare_database(settings)

    with SessionLocal.begin() as db:
        user, project = _admin_project(db)
        waiting_statuses = (AWAITING_APPROVAL, AWAITING_INPUT, AWAITING_APPROVAL)
        for index, status in enumerate(waiting_statuses):
            conversation = _conversation(db, user, project, f"User waiting {index}")
            _run(db, user, conversation, status=status)
        candidate_conversation = _conversation(db, user, project, "User candidate")
        candidate = _run(db, user, candidate_conversation, status=QUEUED)
        candidate_id = candidate.id

    claimed_id = asyncio.run(LocalRunExecutor(settings)._claim_next())

    assert claimed_id == candidate_id


def test_response_waiting_run_still_blocks_the_same_conversation(
    tmp_path: Path,
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
        _run(db, user, conversation, status=AWAITING_INPUT)
        _run(db, user, conversation, status=QUEUED)

    assert asyncio.run(LocalRunExecutor(settings)._claim_next()) is None


def test_paused_run_keeps_its_server_slot_until_its_task_can_be_released(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        "paused-capacity",
        user_concurrency_limit=3,
        server_concurrency_limit=1,
    )
    _prepare_database(settings)

    with SessionLocal.begin() as db:
        user, project = _admin_project(db)
        paused_conversation = _conversation(db, user, project, "Paused")
        _run(db, user, paused_conversation, status=PAUSED)
        candidate_conversation = _conversation(db, user, project, "After paused")
        _run(db, user, candidate_conversation, status=QUEUED)

    assert asyncio.run(LocalRunExecutor(settings)._claim_next()) is None


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
