from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.agent.executor import local_run_executor
from lumina.api.dependencies import AuthContext
from lumina.api.routes.runs import stream_run
from lumina.auth.service import create_user
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import (
    AuthSession,
    Conversation,
    Message,
    Project,
    ProjectMembership,
    QueuedMessage,
    Run,
    RunCommand,
    RunEvent,
    User,
    utc_now,
)
from lumina.providers import (
    MockProvider,
    MockToolCall,
    ProviderCapabilities,
    ProviderEvent,
    ProviderRequestError,
    ProviderRequest,
)
from lumina.runs.state import ACTIVE_STATUSES, TERMINAL_STATUSES
from lumina.runs.broker import event_broker


def _settings(tmp_path: Path, name: str) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
        session_concurrency_limit=1,
        user_concurrency_limit=3,
        server_concurrency_limit=12,
    )


def _login(client: TestClient, login_name: str = "admin", password: str = "1") -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": login_name,
            "loginDomain": "posco.com",
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def _conversation(
    client: TestClient,
    csrf: str,
    title: str,
    *,
    project_id: str | None = None,
) -> str:
    selected_project_id = project_id or client.get("/api/projects").json()[0]["id"]
    response = client.post(
        "/api/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"projectId": selected_project_id, "title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _start_run(
    client: TestClient,
    csrf: str,
    conversation_id: str,
    *,
    text: str,
    idempotency_key: str,
) -> str:
    response = client.post(
        f"/api/conversations/{conversation_id}/runs",
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": idempotency_key,
        },
        json={
            "message": {
                "text": text,
                "attachmentIds": [],
                "promptReferences": [],
            },
            "execution": {
                "providerId": "mock",
                "modelKey": "mock-agent",
                "effortId": "medium",
            },
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["run"]["runId"]


def _wait_for_terminal(
    client: TestClient, run_id: str, *, timeout: float = 5.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200, response.text
        snapshot = response.json()
        if snapshot["status"] in TERMINAL_STATUSES:
            return snapshot
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not reach a terminal state")


async def _skip_memory_extraction(_run_id: str) -> None:
    return None


class _GateProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self, markers: tuple[str, ...]) -> None:
        self.markers = markers
        self.entered = {marker: threading.Event() for marker in markers}
        self.release = {marker: threading.Event() for marker in markers}

    def release_all(self) -> None:
        for event in self.release.values():
            event.set()

    def _marker(self, request: ProviderRequest) -> str:
        for message in reversed(request.messages):
            if message.role != "user" or not message.content:
                continue
            for marker in self.markers:
                if marker in message.content:
                    return marker
        raise AssertionError("No deterministic gate marker found in Provider request")

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        marker = self._marker(request)
        self.entered[marker].set()
        released = await asyncio.to_thread(self.release[marker].wait, 5.0)
        if not released:
            raise AssertionError(f"Provider gate {marker} was not released")
        yield ProviderEvent(type="text_delta", text=f"completed:{marker}")
        yield ProviderEvent(type="completed", stop_reason="stop")


class _FailThenSucceedProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.failure_started = threading.Event()
        self.release_failure = threading.Event()
        self.success_started = threading.Event()

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        latest_user_text = next(
            (
                message.content or ""
                for message in reversed(request.messages)
                if message.role == "user"
            ),
            "",
        )
        if "queue-after-provider-failure" in latest_user_text:
            self.success_started.set()
            yield ProviderEvent(type="text_delta", text="queue recovered")
            yield ProviderEvent(type="completed", stop_reason="stop")
            return

        self.failure_started.set()
        released = await asyncio.to_thread(self.release_failure.wait, 5.0)
        if not released:
            raise AssertionError("Provider failure gate was not released")
        raise ProviderRequestError(
            "deterministic provider failure",
            retryable=False,
            stage="response",
        )


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def _gate_factory(provider: _GateProvider) -> Callable[..., _GateProvider]:
    def factory(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> _GateProvider:
        del wants_artifact, first_turn
        return provider

    return factory


def test_different_conversations_for_one_user_execute_in_parallel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _GateProvider(("parallel-A", "parallel-B"))
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(
        local_run_executor, "_learn_memory_background", _skip_memory_extraction
    )

    with TestClient(create_app(_settings(tmp_path, "parallel-runs.db"))) as client:
        try:
            csrf = _login(client)
            conversation_a = _conversation(client, csrf, "Parallel A")
            conversation_b = _conversation(client, csrf, "Parallel B")
            run_a = _start_run(
                client,
                csrf,
                conversation_a,
                text="parallel-A",
                idempotency_key="parallel-run-a-0001",
            )
            assert provider.entered["parallel-A"].wait(timeout=2)
            run_b = _start_run(
                client,
                csrf,
                conversation_b,
                text="parallel-B",
                idempotency_key="parallel-run-b-0001",
            )
            assert provider.entered["parallel-B"].wait(timeout=2)

            with SessionLocal() as db:
                rows = [db.get(Run, run_id) for run_id in (run_a, run_b)]
                assert all(run is not None for run in rows)
                concrete = [run for run in rows if run is not None]
                assert all(run.status in ACTIVE_STATUSES for run in concrete)
                assert all(run.started_at is not None for run in concrete)
                assert all(run.finished_at is None for run in concrete)

            provider.release_all()
            assert _wait_for_terminal(client, run_a)["status"] == "completed"
            assert _wait_for_terminal(client, run_b)["status"] == "completed"

            with SessionLocal() as db:
                completed = [db.get(Run, run_id) for run_id in (run_a, run_b)]
                assert all(run is not None for run in completed)
                concrete = [run for run in completed if run is not None]
                started = [run.started_at for run in concrete]
                finished = [run.finished_at for run in concrete]
                assert all(value is not None for value in started + finished)
                assert max(value for value in started if value is not None) < min(
                    value for value in finished if value is not None
                )
        finally:
            provider.release_all()


def test_same_conversation_second_run_stays_queued_until_first_finishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _GateProvider(("serial-first", "serial-second"))
    original_claim = local_run_executor._claim
    claim_attempts: defaultdict[str, list[str]] = defaultdict(list)
    claim_condition = threading.Condition()

    async def tracked_claim(run_id: str) -> str:
        result = await original_claim(run_id)
        with claim_condition:
            claim_attempts[run_id].append(result)
            claim_condition.notify_all()
        return result

    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(local_run_executor, "_claim", tracked_claim)
    monkeypatch.setattr(
        local_run_executor, "_learn_memory_background", _skip_memory_extraction
    )

    with TestClient(create_app(_settings(tmp_path, "serial-runs.db"))) as client:
        try:
            csrf = _login(client)
            conversation_id = _conversation(client, csrf, "Serial runs")
            first_run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text="serial-first",
                idempotency_key="serial-first-run-0001",
            )
            assert provider.entered["serial-first"].wait(timeout=2)
            second_run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text="serial-second",
                idempotency_key="serial-second-run-0001",
            )

            with claim_condition:
                attempted = claim_condition.wait_for(
                    lambda: bool(claim_attempts[second_run_id]), timeout=2
                )
                assert attempted
                assert claim_attempts[second_run_id][-1] == "wait"
            with SessionLocal() as db:
                first = db.get(Run, first_run_id)
                second = db.get(Run, second_run_id)
                assert first is not None and second is not None
                assert first.status in ACTIVE_STATUSES
                assert second.status == "queued"
                assert second.started_at is None
                assert second.finished_at is None

            provider.release["serial-first"].set()
            assert provider.entered["serial-second"].wait(timeout=3)
            first_snapshot = _wait_for_terminal(client, first_run_id)
            assert first_snapshot["status"] == "completed"
            with SessionLocal() as db:
                first = db.get(Run, first_run_id)
                second = db.get(Run, second_run_id)
                assert first is not None and second is not None
                assert first.finished_at is not None
                assert second.started_at is not None
                assert second.started_at >= first.finished_at
                assert second.status in ACTIVE_STATUSES

            provider.release["serial-second"].set()
            assert _wait_for_terminal(client, second_run_id)["status"] == "completed"
        finally:
            provider.release_all()


def test_queue_next_promotes_to_new_run_only_after_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _GateProvider(("queue-current", "queue-next"))
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(
        local_run_executor, "_learn_memory_background", _skip_memory_extraction
    )

    with TestClient(create_app(_settings(tmp_path, "queue-next.db"))) as client:
        try:
            csrf = _login(client)
            conversation_id = _conversation(client, csrf, "Queue next")
            current_run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text="queue-current",
                idempotency_key="queue-current-run-0001",
            )
            assert provider.entered["queue-current"].wait(timeout=2)

            queued_response = client.post(
                f"/api/runs/{current_run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "queue-next-action-0001",
                },
                json={
                    "type": "queue_next",
                    "message": {
                        "text": "queue-next",
                        "attachmentIds": [],
                        "promptReferences": [],
                    },
                },
            )
            assert queued_response.status_code == 200, queued_response.text
            assert queued_response.json()["command"]["status"] == "queued"
            with SessionLocal() as db:
                queued = db.scalar(
                    select(QueuedMessage).where(
                        QueuedMessage.conversation_id == conversation_id
                    )
                )
                assert queued is not None
                queued_message_id = queued.id
                assert queued.status == "queued"
                assert queued.position == 1
                assert queued.promoted_run_id is None
                assert queued.promoted_at is None
                assert db.scalars(
                    select(Run).where(Run.conversation_id == conversation_id)
                ).all() == [db.get(Run, current_run_id)]

            provider.release["queue-current"].set()
            assert provider.entered["queue-next"].wait(timeout=3)
            assert _wait_for_terminal(client, current_run_id)["status"] == "completed"

            with SessionLocal() as db:
                queued = db.get(QueuedMessage, queued_message_id)
                current = db.get(Run, current_run_id)
                assert queued is not None and current is not None
                assert queued.status == "promoted"
                assert queued.promoted_run_id is not None
                assert queued.promoted_at is not None
                promoted = db.get(Run, queued.promoted_run_id)
                assert promoted is not None
                promoted_run_id = promoted.id
                assert current.finished_at is not None
                assert promoted.started_at is not None
                assert promoted.started_at >= current.finished_at
                promotion_event = db.scalar(
                    select(RunEvent).where(
                        RunEvent.run_id == current.id,
                        RunEvent.event_type == "queued_message_promoted_to_run",
                    )
                )
                assert promotion_event is not None
                assert promotion_event.payload_json["queuedMessageId"] == queued.id
                assert promotion_event.payload_json["runId"] == promoted.id
                assert promotion_event.payload_json["command"]["status"] == "promoted"
                promotion_sequence = promotion_event.sequence

            source_snapshot = client.get(f"/api/runs/{current_run_id}/snapshot")
            assert source_snapshot.status_code == 200
            assert source_snapshot.json()["status"] == "completed"
            assert source_snapshot.json()["pendingCommands"] == []
            assert source_snapshot.json()["lastSequence"] == promotion_sequence

            provider.release["queue-next"].set()
            assert _wait_for_terminal(client, promoted_run_id)["status"] == "completed"
            with SessionLocal() as db:
                command = db.scalar(
                    select(RunCommand).where(
                        RunCommand.run_id == current_run_id,
                        RunCommand.command_type == "queue_next",
                    )
                )
                queued_user_messages = list(
                    db.scalars(
                        select(Message).where(
                            Message.conversation_id == conversation_id,
                            Message.role == "user",
                            Message.canonical_text == "queue-next",
                        )
                    )
                )
                assert command is not None
                assert (
                    command.status,
                    command.applied_at is not None,
                    len(queued_user_messages),
                    queued_user_messages[0].run_id,
                    queued_user_messages[0].status,
                ) == ("promoted", True, 1, promoted_run_id, "completed")
        finally:
            provider.release_all()


def test_queue_next_is_promoted_after_provider_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _FailThenSucceedProvider()
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )
    monkeypatch.setattr(
        local_run_executor, "_learn_memory_background", _skip_memory_extraction
    )

    with TestClient(
        create_app(_settings(tmp_path, "queue-provider-failure.db"))
    ) as client:
        try:
            csrf = _login(client)
            conversation_id = _conversation(
                client, csrf, "Queue after provider failure"
            )
            current_run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text="provider-failure-source",
                idempotency_key="provider-failure-source-0001",
            )
            assert provider.failure_started.wait(timeout=2)

            queued_response = client.post(
                f"/api/runs/{current_run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "queue-provider-failure-action-0001",
                },
                json={
                    "type": "queue_next",
                    "message": {
                        "text": "queue-after-provider-failure",
                        "attachmentIds": [],
                        "promptReferences": [],
                    },
                },
            )
            assert queued_response.status_code == 200, queued_response.text

            provider.release_failure.set()
            assert _wait_for_terminal(client, current_run_id)["status"] == "failed"
            assert provider.success_started.wait(timeout=3)

            with SessionLocal() as db:
                queued = db.scalar(
                    select(QueuedMessage).where(
                        QueuedMessage.conversation_id == conversation_id
                    )
                )
                assert queued is not None
                assert queued.status == "promoted"
                assert queued.promoted_run_id is not None
                promoted_run_id = queued.promoted_run_id
                command = db.scalar(
                    select(RunCommand).where(
                        RunCommand.run_id == current_run_id,
                        RunCommand.command_type == "queue_next",
                    )
                )
                assert command is not None
                assert command.status == "promoted"

            assert _wait_for_terminal(client, promoted_run_id)["status"] == "completed"
        finally:
            provider.release_failure.set()


def test_queued_message_is_recovered_once_after_executor_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, "queue-restart.db")
    provider = _GateProvider(("restart-current", "restart-next"))
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(
        local_run_executor, "_learn_memory_background", _skip_memory_extraction
    )

    with TestClient(create_app(settings)) as first_client:
        csrf = _login(first_client)
        conversation_id = _conversation(first_client, csrf, "Queue restart")
        current_run_id = _start_run(
            first_client,
            csrf,
            conversation_id,
            text="restart-current",
            idempotency_key="restart-current-run-0001",
        )
        assert provider.entered["restart-current"].wait(timeout=2)
        queued_response = first_client.post(
            f"/api/runs/{current_run_id}/actions",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "restart-next-action-0001",
            },
            json={
                "type": "queue_next",
                "message": {
                    "text": "restart-next",
                    "attachmentIds": [],
                    "promptReferences": [],
                },
            },
        )
        assert queued_response.status_code == 200, queued_response.text

    provider.release["restart-current"].set()
    with SessionLocal() as db:
        interrupted = db.get(Run, current_run_id)
        queued = db.scalar(
            select(QueuedMessage).where(
                QueuedMessage.conversation_id == conversation_id
            )
        )
        assert interrupted is not None and interrupted.status == "interrupted"
        assert queued is not None and queued.status == "queued"
        queued_message_id = queued.id

    with TestClient(create_app(settings)) as second_client:
        try:
            _login(second_client)
            with SessionLocal() as db:
                queued = db.get(QueuedMessage, queued_message_id)
                assert queued is not None
                assert queued.status == "promoted"
                assert queued.promoted_run_id is not None
                promoted_run_id = queued.promoted_run_id
                assert (
                    len(
                        db.scalars(
                            select(Run).where(Run.conversation_id == conversation_id)
                        ).all()
                    )
                    == 2
                )
            assert provider.entered["restart-next"].wait(timeout=2)
            provider.release["restart-next"].set()
            assert (
                _wait_for_terminal(second_client, promoted_run_id)["status"]
                == "completed"
            )
            with SessionLocal() as db:
                queued_messages = list(
                    db.scalars(
                        select(Message).where(
                            Message.conversation_id == conversation_id,
                            Message.role == "user",
                            Message.canonical_text == "restart-next",
                        )
                    )
                )
                assert len(queued_messages) == 1
                assert queued_messages[0].run_id == promoted_run_id
                promotion_events = list(
                    db.scalars(
                        select(RunEvent).where(
                            RunEvent.run_id == current_run_id,
                            RunEvent.event_type == "queued_message_promoted_to_run",
                        )
                    )
                )
                assert len(promotion_events) == 1
        finally:
            provider.release_all()

    with TestClient(create_app(settings)) as third_client:
        _login(third_client)
        with SessionLocal() as db:
            assert (
                len(
                    db.scalars(
                        select(Run).where(Run.conversation_id == conversation_id)
                    ).all()
                )
                == 2
            )
            assert (
                len(
                    db.scalars(
                        select(Message).where(
                            Message.conversation_id == conversation_id,
                            Message.role == "user",
                            Message.canonical_text == "restart-next",
                        )
                    ).all()
                )
                == 1
            )
            assert (
                len(
                    db.scalars(
                        select(RunEvent).where(
                            RunEvent.run_id == current_run_id,
                            RunEvent.event_type == "queued_message_promoted_to_run",
                        )
                    ).all()
                )
                == 1
            )


@pytest.mark.parametrize(
    "failure_mode", ["inactive_user", "deleted_conversation", "revoked_access"]
)
def test_queue_promotion_fails_safe_when_access_is_no_longer_valid(
    failure_mode: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _GateProvider((f"failure-current-{failure_mode}",))
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(
        local_run_executor, "_learn_memory_background", _skip_memory_extraction
    )

    with TestClient(
        create_app(_settings(tmp_path, f"queue-{failure_mode}.db"))
    ) as client:
        try:
            revoked_membership_id: str | None = None
            if failure_mode == "revoked_access":
                with SessionLocal() as db:
                    admin = db.scalar(
                        select(User).where(User.login_id == "admin@posco.com")
                    )
                    assert admin is not None
                    shared_project = db.scalar(
                        select(Project).where(
                            Project.owner_user_id == admin.id,
                            Project.is_default.is_(True),
                        )
                    )
                    assert shared_project is not None
                    worker = create_user(
                        db,
                        login_name="queue-worker",
                        password="password",
                        organization_id=admin.organization_id,
                        display_name="Queue Worker",
                    )
                    membership = ProjectMembership(
                        project_id=shared_project.id,
                        user_id=worker.id,
                        role="member",
                        status="active",
                        created_by_user_id=admin.id,
                    )
                    db.add(membership)
                    db.commit()
                    revoked_membership_id = membership.id
                    shared_project_id = shared_project.id
                csrf = _login(client, "queue-worker", "password")
                conversation_id = _conversation(
                    client,
                    csrf,
                    f"Queue {failure_mode}",
                    project_id=shared_project_id,
                )
            else:
                csrf = _login(client)
                conversation_id = _conversation(client, csrf, f"Queue {failure_mode}")
            current_run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text=f"failure-current-{failure_mode}",
                idempotency_key=f"failure-current-{failure_mode}-0001",
            )
            assert provider.entered[f"failure-current-{failure_mode}"].wait(timeout=2)
            queued_response = client.post(
                f"/api/runs/{current_run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": f"failure-next-{failure_mode}-0001",
                },
                json={
                    "type": "queue_next",
                    "message": {
                        "text": f"failure-next-{failure_mode}",
                        "attachmentIds": [],
                        "promptReferences": [],
                    },
                },
            )
            assert queued_response.status_code == 200, queued_response.text
            with SessionLocal() as db:
                queued = db.scalar(
                    select(QueuedMessage).where(
                        QueuedMessage.conversation_id == conversation_id
                    )
                )
                assert queued is not None
                queued_message_id = queued.id
                if failure_mode == "inactive_user":
                    user = db.scalar(
                        select(User).where(User.login_id == "admin@posco.com")
                    )
                    assert user is not None
                    user.status = "disabled"
                elif failure_mode == "deleted_conversation":
                    conversation = db.get(Conversation, conversation_id)
                    assert conversation is not None
                    conversation.deleted_at = utc_now()
                else:
                    assert revoked_membership_id is not None
                    revoked_membership = db.get(
                        ProjectMembership, revoked_membership_id
                    )
                    assert revoked_membership is not None
                    revoked_membership.status = "revoked"
                db.commit()

            provider.release_all()
            deadline = time.monotonic() + 3
            queued_status: str | None = None
            while time.monotonic() < deadline:
                with SessionLocal() as db:
                    queued_status = db.scalar(
                        select(QueuedMessage.status).where(
                            QueuedMessage.id == queued_message_id
                        )
                    )
                if queued_status == "failed":
                    break
                time.sleep(0.02)
            assert queued_status == "failed"

            with SessionLocal() as db:
                current = db.get(Run, current_run_id)
                command = db.scalar(
                    select(RunCommand).where(
                        RunCommand.run_id == current_run_id,
                        RunCommand.command_type == "queue_next",
                    )
                )
                pending_message = db.scalar(
                    select(Message).where(
                        Message.conversation_id == conversation_id,
                        Message.canonical_text == f"failure-next-{failure_mode}",
                    )
                )
                failure_event = db.scalar(
                    select(RunEvent).where(
                        RunEvent.run_id == current_run_id,
                        RunEvent.event_type == "queued_message_promotion_failed",
                    )
                )
                assert current is not None and current.status == "completed"
                assert command is not None and command.status == "failed"
                assert command.payload_json["failure_code"] in {
                    "queued_user_unavailable",
                    "not_found",
                }
                assert (
                    pending_message is not None and pending_message.status == "failed"
                )
                assert failure_event is not None
                assert failure_event.payload_json["command"]["status"] == "failed"
                assert (
                    len(
                        db.scalars(
                            select(Run).where(Run.conversation_id == conversation_id)
                        ).all()
                    )
                    == 1
                )
        finally:
            provider.release_all()


def _report_arguments() -> dict[str, object]:
    return {
        "format": "html",
        "title": "Replay contract report",
        "executive_summary": "Replay must preserve every persisted event.",
        "key_metrics": [{"label": "events", "value": "lossless"}],
        "sections": [
            {
                "heading": "Replay",
                "body": "Text, tool, and artifact state remains canonical.",
                "bullets": ["No gaps", "No duplicates"],
            }
        ],
        "action_items": ["Reconnect from the last applied sequence"],
    }


def _read_sse_events(
    response: Any, *, stop_at: int | None = None
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in response.iter_lines():
        if not line.startswith("data: "):
            continue
        event = json.loads(line.removeprefix("data: "))
        events.append(event)
        if stop_at is not None and event["sequence"] >= stop_at:
            break
    return events


def test_sse_stops_before_delivering_events_after_session_revocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _GateProvider(("stream-session-revocation",))
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(
        local_run_executor, "_learn_memory_background", _skip_memory_extraction
    )

    async def no_wait(_run_id: str, timeout: float = 15.0) -> None:
        del timeout

    monkeypatch.setattr(event_broker, "wait", no_wait)

    with TestClient(
        create_app(_settings(tmp_path, "sse-session-revocation.db"))
    ) as client:
        try:
            csrf = _login(client)
            conversation_id = _conversation(client, csrf, "SSE session revocation")
            run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text="stream-session-revocation",
                idempotency_key="stream-session-revocation-0001",
            )
            assert provider.entered["stream-session-revocation"].wait(timeout=2)
            session_token = client.cookies.get("lumina_session")
            assert session_token

            with SessionLocal() as db:
                auth_session = db.scalar(
                    select(AuthSession).where(AuthSession.revoked_at.is_(None))
                )
                assert auth_session is not None
                user = db.get(User, auth_session.user_id)
                assert user is not None
                context = AuthContext(user, auth_session, session_token)
                response = asyncio.run(
                    stream_run(
                        run_id,
                        _ConnectedRequest(),  # type: ignore[arg-type]
                        0,
                        None,
                        context,
                        db,
                    )
                )

            async def consume_until_revoked() -> list[dict[str, Any]]:
                delivered: list[dict[str, Any]] = []
                iterator = response.body_iterator
                while True:
                    chunk = await anext(iterator)
                    assert isinstance(chunk, str)
                    for line in chunk.splitlines():
                        if line.startswith("data: "):
                            delivered.append(json.loads(line.removeprefix("data: ")))
                    if chunk.startswith(": keep-alive"):
                        break

                with SessionLocal.begin() as db:
                    active_session = db.get(AuthSession, auth_session.id)
                    assert active_session is not None
                    active_session.revoked_at = utc_now()

                with pytest.raises(StopAsyncIteration):
                    await anext(iterator)
                return delivered

            delivered = asyncio.run(consume_until_revoked())
            assert delivered
            assert all(event["type"] != "assistant_text_delta" for event in delivered)
        finally:
            provider.release_all()


def test_sse_disconnect_snapshot_and_last_event_id_replay_are_lossless(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        assert wants_artifact
        if first_turn:
            return MockProvider(
                text_chunks=("draft-before-tool",),
                tool_call=MockToolCall(
                    name="create_report",
                    arguments=_report_arguments(),
                    call_id="replay-report-tool",
                ),
            )
        return MockProvider(text_chunks=("final-after-artifact",))

    monkeypatch.setattr(local_run_executor, "_provider", fake_provider)
    monkeypatch.setattr(
        local_run_executor, "_learn_memory_background", _skip_memory_extraction
    )

    with TestClient(create_app(_settings(tmp_path, "sse-replay.db"))) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "SSE replay")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="Create a report artifact for replay verification",
            idempotency_key="sse-replay-run-0001",
        )
        terminal = _wait_for_terminal(client, run_id)
        assert terminal["status"] == "completed"

        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id)
                    .order_by(RunEvent.sequence)
                )
            )
            canonical = [
                (event.sequence, event.event_type, event.payload_json) for event in rows
            ]
        cut_sequence = next(
            sequence
            for sequence, event_type, _payload in canonical
            if event_type == "assistant_text_delta"
        )

        with client.stream("GET", f"/stream/runs/{run_id}?after_sequence=0") as first:
            assert first.status_code == 200
            prefix = _read_sse_events(first, stop_at=cut_sequence)
        assert prefix[-1]["sequence"] == cut_sequence

        snapshot = client.get(f"/api/runs/{run_id}/snapshot")
        assert snapshot.status_code == 200
        snapshot_json = snapshot.json()
        assert snapshot_json["lastSequence"] == canonical[-1][0]
        assert snapshot_json["assistantDraft"]["text"] == (
            "draft-before-toolfinal-after-artifact"
        )
        assert [tool["status"] for tool in snapshot_json["toolExecutions"]] == [
            "completed"
        ]
        assert len(snapshot_json["artifacts"]) == 1
        assert snapshot_json["artifactProgress"] is None

        replay_response = client.get(
            f"/stream/runs/{run_id}",
            headers={"Last-Event-ID": str(cut_sequence)},
            params={"after_sequence": cut_sequence - 1},
        )
        assert replay_response.status_code == 200
        replay = [
            json.loads(line.removeprefix("data: "))
            for line in replay_response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert replay
        assert all(event["sequence"] > cut_sequence for event in replay)

        delivered = [
            (event["sequence"], event["type"], event["payload"])
            for event in [*prefix, *replay]
        ]
        assert delivered == canonical
        sequences = [sequence for sequence, _type, _payload in delivered]
        assert sequences == sorted(set(sequences))
        assert {event_type for _sequence, event_type, _payload in delivered} >= {
            "assistant_text_delta",
            "artifact_progress",
            "tool_started",
            "tool_completed",
            "artifact_created",
            "run_completed",
        }
        progress = [
            payload
            for _sequence, event_type, payload in delivered
            if event_type == "artifact_progress"
        ]
        assert progress[0] == {"tokens": 0, "lines": 0}
        assert progress[-1]["tokens"] > 0
        assert progress[-1]["lines"] > 0
