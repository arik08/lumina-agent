from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select

from lumina.agent import executor as executor_module
from lumina.agent.executor import local_run_executor
from lumina.api.dependencies import AuthContext
from lumina.api.routes.runs import stream_run
from lumina.auth.service import create_user
from lumina.config import REPOSITORY_ROOT, Settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.http_client import TrustManager
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
    ProviderMessage,
    ProviderRequestError,
    ProviderRequest,
)
from lumina.providers.openai_compatible import adapter as openai_compatible_module
from lumina.providers.openai_compatible import OpenAICompatibleAdapter
from lumina.runs.state import ACTIVE_STATUSES, TERMINAL_STATUSES
from lumina.runs.broker import event_broker
from lumina.runs.plans import pause_plan


def _settings(
    tmp_path: Path,
    name: str,
    *,
    user_concurrency_limit: int = 3,
    server_concurrency_limit: int = 12,
) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
        session_concurrency_limit=1,
        user_concurrency_limit=user_concurrency_limit,
        server_concurrency_limit=server_concurrency_limit,
    )


def _login(
    client: TestClient, login_name: str = "admin", password: str = "1111"
) -> str:
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


def _wait_for_detached_pause(run_id: str, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if (
                run is not None
                and run.status == "paused"
                and run.worker_id is None
                and isinstance(run.snapshot_json.get("paused_worker_detached"), dict)
            ):
                return
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not detach while paused")


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


class _PauseResumeProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self, markers: tuple[str, ...]) -> None:
        self.markers = markers
        self.attempts = {marker: 0 for marker in markers}
        self.entered = {
            (marker, attempt): threading.Event()
            for marker in markers
            for attempt in (1, 2, 3)
        }
        self.release = {marker: threading.Event() for marker in markers}
        self._lock = threading.Lock()

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
        raise AssertionError("No deterministic pause marker found in Provider request")

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        marker = self._marker(request)
        with self._lock:
            self.attempts[marker] += 1
            attempt = self.attempts[marker]
        self.entered[(marker, attempt)].set()
        while not self.release[marker].is_set():
            await asyncio.sleep(0.01)
        yield ProviderEvent(
            type="text_delta", text=f"completed:{marker}:attempt-{attempt}"
        )
        yield ProviderEvent(type="completed", stop_reason="stop")


class _ToolPauseProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0
        self.requests: list[ProviderRequest] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        self.requests.append(request)
        if self.attempts == 1:
            arguments = json.dumps(
                {
                    "plan": [
                        {
                            "step": "안전한 일시 정지 경계를 검증합니다.",
                            "status": "in_progress",
                            "phase": "validation",
                        },
                        {
                            "step": "검증 결과를 답변으로 정리합니다.",
                            "status": "pending",
                            "phase": "drafting",
                        },
                    ]
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield ProviderEvent(
                type="tool_call_started",
                tool_call_id="call_pause_update_plan",
                tool_name="update_plan",
            )
            yield ProviderEvent(
                type="tool_call_completed",
                tool_call_id="call_pause_update_plan",
                tool_name="update_plan",
                arguments_json=arguments,
            )
            yield ProviderEvent(type="completed", stop_reason="tool_calls")
            return
        assert any(message.role == "tool" for message in request.messages)
        yield ProviderEvent(type="text_delta", text="tool checkpoint resumed once")
        yield ProviderEvent(type="completed", stop_reason="stop")


class _ToolBoundarySteerProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0
        self.boundary_reached = threading.Event()
        self.release_boundary = threading.Event()

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1:
            arguments = json.dumps(
                {
                    "plan": [
                        {
                            "step": "This tool must not run after steering.",
                            "status": "in_progress",
                            "phase": "execution",
                        }
                    ]
                },
                separators=(",", ":"),
            )
            yield ProviderEvent(
                type="tool_call_started",
                tool_call_id="call_before_steer",
                tool_name="update_plan",
            )
            yield ProviderEvent(
                type="tool_call_completed",
                tool_call_id="call_before_steer",
                tool_name="update_plan",
                arguments_json=arguments,
            )
            yield ProviderEvent(type="completed", stop_reason="tool_calls")
            self.boundary_reached.set()
            released = await asyncio.to_thread(self.release_boundary.wait, 5.0)
            if not released:
                raise AssertionError("Tool boundary was not released")
            return

        assert any(
            message.role == "user"
            and "reply-in-chat-instead" in (message.content or "")
            for message in request.messages
        )
        assert not any(
            message.role == "tool"
            or any(call.get("id") == "call_before_steer" for call in message.tool_calls)
            for message in request.messages
        )
        yield ProviderEvent(
            type="text_delta", text="steering applied before tool execution"
        )
        yield ProviderEvent(type="completed", stop_reason="stop")


class _OrderedToolSteerRecoveryProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0
        self.requests: list[ProviderRequest] = []
        self.prefix_gate = threading.Event()
        self.post_a_gate = threading.Event()
        self.post_b_gate = threading.Event()
        self.crash_gate = threading.Event()
        self.recovery_request: ProviderRequest | None = None

    @staticmethod
    def _plan_arguments(label: str) -> str:
        return json.dumps(
            {
                "plan": [
                    {
                        "step": label,
                        "status": "in_progress",
                        "phase": "validation",
                    },
                    {
                        "step": f"finish-{label}",
                        "status": "pending",
                        "phase": "drafting",
                    },
                ]
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _index(
        messages: tuple[ProviderMessage, ...],
        predicate: Callable[[ProviderMessage], bool],
    ) -> int:
        return next(
            index for index, message in enumerate(messages) if predicate(message)
        )

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        self.requests.append(request)
        if self.attempts in {1, 3, 5}:
            partial_label = {
                1: "partial-prefix|",
                3: "partial-post-a|",
                5: "partial-post-b|",
            }[self.attempts]
            yield ProviderEvent(type="text_delta", text=partial_label)
            {
                1: self.prefix_gate,
                3: self.post_a_gate,
                5: self.post_b_gate,
            }[self.attempts].set()
            while True:
                await asyncio.sleep(0.01)
        if self.attempts == 6:
            self.crash_gate.set()
            while True:
                await asyncio.sleep(0.01)
        if self.attempts in {2, 4}:
            suffix = "a" if self.attempts == 2 else "b"
            call_id = f"call_ordered_{suffix}"
            yield ProviderEvent(
                type="tool_call_started",
                tool_call_id=call_id,
                tool_name="update_plan",
            )
            yield ProviderEvent(
                type="tool_call_completed",
                tool_call_id=call_id,
                tool_name="update_plan",
                arguments_json=self._plan_arguments(f"round-{suffix}"),
            )
            yield ProviderEvent(type="completed", stop_reason="tool_calls")
            return

        self.recovery_request = request
        messages = request.messages
        partial_prefix_index = self._index(
            messages,
            lambda message: (
                message.role == "assistant" and message.content == "partial-prefix|"
            ),
        )
        prefix_index = self._index(
            messages,
            lambda message: (
                message.role == "user" and "prefix-steer" in (message.content or "")
            ),
        )
        assistant_a_index = self._index(
            messages,
            lambda message: (
                message.role == "assistant"
                and any(
                    call.get("id") == "call_ordered_a" for call in message.tool_calls
                )
            ),
        )
        tool_a_index = self._index(
            messages,
            lambda message: (
                message.role == "tool" and message.tool_call_id == "call_ordered_a"
            ),
        )
        partial_post_a_index = self._index(
            messages,
            lambda message: (
                message.role == "assistant" and message.content == "partial-post-a|"
            ),
        )
        post_a_index = self._index(
            messages,
            lambda message: (
                message.role == "user" and "post-a-steer" in (message.content or "")
            ),
        )
        assistant_b_index = self._index(
            messages,
            lambda message: (
                message.role == "assistant"
                and any(
                    call.get("id") == "call_ordered_b" for call in message.tool_calls
                )
            ),
        )
        tool_b_index = self._index(
            messages,
            lambda message: (
                message.role == "tool" and message.tool_call_id == "call_ordered_b"
            ),
        )
        partial_post_b_index = self._index(
            messages,
            lambda message: (
                message.role == "assistant" and message.content == "partial-post-b|"
            ),
        )
        post_b_index = self._index(
            messages,
            lambda message: (
                message.role == "user" and "post-b-steer" in (message.content or "")
            ),
        )
        assert (
            partial_prefix_index
            < prefix_index
            < assistant_a_index
            < tool_a_index
            < partial_post_a_index
            < post_a_index
            < assistant_b_index
            < tool_b_index
            < partial_post_b_index
            < post_b_index
        )
        for marker in ("prefix-steer", "post-a-steer", "post-b-steer"):
            assert (
                sum(
                    marker in (message.content or "")
                    for message in messages
                    if message.role == "user"
                )
                == 1
            )
        yield ProviderEvent(
            type="text_delta", text="ordered tool transcript recovered once"
        )
        yield ProviderEvent(type="completed", stop_reason="stop")


class _PrefixSteerRestartProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0
        self.steer_gate = threading.Event()
        self.crash_gate = threading.Event()

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1:
            yield ProviderEvent(type="text_delta", text="partial-prefix-crash|")
            self.steer_gate.set()
            while True:
                await asyncio.sleep(0.01)
        if self.attempts == 2:
            self.crash_gate.set()
            while True:
                await asyncio.sleep(0.01)

        partial_index = next(
            index
            for index, message in enumerate(request.messages)
            if message.role == "assistant"
            and message.content == "partial-prefix-crash|"
        )
        steer_indexes = [
            index
            for index, message in enumerate(request.messages)
            if message.role == "user"
            and "prefix-crash-steer" in (message.content or "")
        ]
        assert len(steer_indexes) == 1
        assert partial_index < steer_indexes[0]
        yield ProviderEvent(type="text_delta", text="prefix transcript restored once")
        yield ProviderEvent(type="completed", stop_reason="stop")


class _ContinuationRestartProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0
        self.crash_gate = threading.Event()

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1:
            yield ProviderEvent(type="text_delta", text="truncated-prefix|")
            yield ProviderEvent(type="completed", stop_reason="max_tokens")
            return
        if self.attempts == 2:
            self.crash_gate.set()
            while True:
                await asyncio.sleep(0.01)

        transcript = [
            (message.role, message.content)
            for message in request.messages
            if message.content
            in {"truncated-prefix|", executor_module._CONTINUATION_PROMPT}
        ]
        assert transcript == [
            ("assistant", "truncated-prefix|"),
            ("user", executor_module._CONTINUATION_PROMPT),
        ]
        yield ProviderEvent(type="text_delta", text="continuation restored once")
        yield ProviderEvent(type="completed", stop_reason="stop")


class _PartialPauseProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0
        self.partial_processed = threading.Event()
        self.second_entered = threading.Event()
        self.release_second = threading.Event()

    async def stream(self, _request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1:
            yield ProviderEvent(type="text_delta", text="partial-before-pause")
            self.partial_processed.set()
            while True:
                await asyncio.sleep(0.01)
        self.second_entered.set()
        while not self.release_second.is_set():
            await asyncio.sleep(0.01)
        yield ProviderEvent(type="text_delta", text="final-after-resume")
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


class _RetryableProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self, *, partial_output: bool = False) -> None:
        self.attempts = 0
        self.partial_output = partial_output
        self.requests: list[ProviderRequest] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        self.requests.append(request)
        if self.attempts == 1:
            if self.partial_output:
                yield ProviderEvent(type="text_delta", text="partial response")
            raise ProviderRequestError(
                "temporary upstream failure",
                retryable=True,
                stage="response",
                status_code=503,
            )
        if self.partial_output:
            assert request.messages[-2:] == (
                ProviderMessage(role="assistant", content="partial response"),
                ProviderMessage(
                    role="user",
                    content=executor_module._PARTIAL_RESPONSE_CONTINUATION_PROMPT,
                ),
            )
            yield ProviderEvent(
                type="text_delta", text="partial response recovered response"
            )
        else:
            yield ProviderEvent(type="text_delta", text="recovered response")
        yield ProviderEvent(type="completed", stop_reason="stop")


class _HiddenProgressThenSucceedProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0

    async def stream(self, _request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1:
            yield ProviderEvent(
                type="text_delta",
                text="<progress>보고서 작성 경로를 준비하고 있습니다.</progress>\n",
            )
            raise ProviderRequestError(
                "temporary stream stall after hidden progress",
                retryable=True,
                stage="stream",
            )
        yield ProviderEvent(type="text_delta", text="report generation recovered")
        yield ProviderEvent(type="completed", stop_reason="stop")


class _AlwaysRetryableProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0

    async def stream(self, _request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        raise ProviderRequestError(
            "temporary network failure",
            retryable=True,
            stage="network",
            status_code=503,
        )
        yield  # pragma: no cover - keeps this an async generator


class _ObservedContextThenCompletingProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0

    async def stream(self, _request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1:
            raise ProviderRequestError(
                "request exceeded the Provider context window",
                retryable=False,
                stage="context",
                status_code=400,
                context_window_tokens=4_096,
            )
        yield ProviderEvent(type="text_delta", text="recovered after calibration")
        yield ProviderEvent(type="completed", stop_reason="stop")


class _PartialReportToolCallThenResumingProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1:
            yield ProviderEvent(
                type="tool_call_started",
                tool_call_id="call_partial_report",
                tool_name="create_report",
            )
            yield ProviderEvent(
                type="tool_call_delta",
                tool_call_id="call_partial_report",
                tool_name="create_report",
                arguments_delta=(
                    '{"format":"html","html_source":"<!doctype html><html><head>'
                    "<meta charset='utf-8'><title>Recovered report</title></head>"
                    "<body><h1>Recovered"
                ),
            )
            raise ProviderRequestError(
                "temporary upstream failure during a report tool call",
                retryable=True,
                stage="stream",
                status_code=503,
            )
        if self.attempts == 2:
            recovery_prompt = request.messages[-1]
            assert recovery_prompt.role == "user"
            assert "Lumina preserved" in str(recovery_prompt.content)
            assert "only the exact HTML suffix" in str(recovery_prompt.content)
            arguments = json.dumps(
                {
                    "format": "html",
                    "title": "Recovered web research report",
                    "executive_summary": "The interrupted report was regenerated.",
                    "key_metrics": [],
                    "sections": [],
                    "action_items": [],
                    "html_source": (
                        " report</h1><p>Verified evidence.</p></body></html>"
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield ProviderEvent(
                type="tool_call_started",
                tool_call_id="call_partial_report",
                tool_name="create_report",
            )
            yield ProviderEvent(
                type="tool_call_delta",
                tool_call_id="call_partial_report",
                tool_name="create_report",
                arguments_delta=arguments,
            )
            yield ProviderEvent(
                type="tool_call_completed",
                tool_call_id="call_partial_report",
                tool_name="create_report",
                arguments_json=arguments,
            )
            yield ProviderEvent(type="completed", stop_reason="tool_calls")
            return
        yield ProviderEvent(type="text_delta", text="Recovered HTML report created.")
        yield ProviderEvent(type="completed", stop_reason="stop")


class _ValidReportWithDiscardedToolCallProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1:
            report_arguments = json.dumps(
                {
                    "format": "html",
                    "title": "Preserved report",
                    "executive_summary": "The valid report call was preserved.",
                    "key_metrics": [],
                    "sections": [],
                    "action_items": [],
                    "html_source": (
                        "<!doctype html><html><head><meta charset='utf-8'>"
                        "<title>Preserved report</title></head><body>"
                        "<h1>Preserved report</h1><p>Verified evidence.</p>"
                        "</body></html>"
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield ProviderEvent(
                type="tool_call_started",
                tool_call_id="call_valid_report",
                tool_name="create_report",
            )
            yield ProviderEvent(
                type="tool_call_delta",
                tool_call_id="call_valid_report",
                tool_name="create_report",
                arguments_delta=report_arguments,
            )
            yield ProviderEvent(
                type="tool_call_started",
                tool_call_id="call_malformed_search",
                tool_name="web_search",
            )
            yield ProviderEvent(
                type="tool_call_delta",
                tool_call_id="call_malformed_search",
                tool_name="web_search",
                arguments_delta='{"query":"POSCO"},{"query":"steel"}',
            )
            yield ProviderEvent(
                type="tool_call_discarded",
                tool_call_id="call_malformed_search",
                tool_name="web_search",
            )
            yield ProviderEvent(
                type="tool_call_completed",
                tool_call_id="call_valid_report",
                tool_name="create_report",
                arguments_json=report_arguments,
            )
            yield ProviderEvent(type="completed", stop_reason="tool_calls")
            return

        assert any(
            message.role == "tool" and message.tool_call_id == "call_valid_report"
            for message in request.messages
        )
        assert not any(
            message.tool_call_id == "call_malformed_search"
            for message in request.messages
        )
        yield ProviderEvent(type="text_delta", text="Preserved HTML report created.")
        yield ProviderEvent(type="completed", stop_reason="stop")


class _ReportThenRepeatedEmptyProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0

    async def stream(self, _request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1:
            arguments = json.dumps(
                {
                    "format": "html",
                    "title": "Completed report",
                    "executive_summary": "The report was created successfully.",
                    "key_metrics": [],
                    "sections": [],
                    "action_items": [],
                    "html_source": (
                        "<!doctype html><html><head><meta charset='utf-8'>"
                        "<title>Completed report</title></head><body>"
                        "<h1>Completed report</h1></body></html>"
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield ProviderEvent(
                type="tool_call_started",
                tool_call_id="call_completed_report",
                tool_name="create_report",
            )
            yield ProviderEvent(
                type="tool_call_delta",
                tool_call_id="call_completed_report",
                tool_name="create_report",
                arguments_delta=arguments,
            )
            yield ProviderEvent(
                type="tool_call_completed",
                tool_call_id="call_completed_report",
                tool_name="create_report",
                arguments_json=arguments,
            )
            yield ProviderEvent(type="completed", stop_reason="tool_calls")
            return
        yield ProviderEvent(type="completed", stop_reason="stop")


class _TruncatingThenCompletingProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.attempts = 0

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1:
            yield ProviderEvent(type="text_delta", text="first part ")
            yield ProviderEvent(type="completed", stop_reason="length")
            return
        assert request.messages[-2].role == "assistant"
        assert request.messages[-2].content == "first part "
        assert request.messages[-1].role == "user"
        assert "Continue exactly where" in str(request.messages[-1].content)
        yield ProviderEvent(type="text_delta", text="second part")
        yield ProviderEvent(type="completed", stop_reason="stop")


class _EmptyThenCompletingProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self, *, always_empty: bool = False) -> None:
        self.attempts = 0
        self.always_empty = always_empty

    async def stream(self, _request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.attempts += 1
        if self.attempts == 1 or self.always_empty:
            yield ProviderEvent(type="completed", stop_reason="stop")
            return
        yield ProviderEvent(type="text_delta", text="recovered from empty turn")
        yield ProviderEvent(type="completed", stop_reason="stop")


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


def test_health_ready_reports_stopped_executor(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path, "truthful-ready.db"))) as client:
        assert client.get("/api/health/ready").status_code == 200
        local_run_executor._started = False
        try:
            response = client.get("/api/health/ready")
        finally:
            local_run_executor._started = True

        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "database": "ready",
            "executor": "stopped",
        }


def test_health_startup_reports_completed_backend_phases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(create_app(_settings(tmp_path, "startup-phases.db"))) as client:
        response = client.get("/api/health/startup")
        pgpt_trust = local_run_executor.pgpt_provider._trust_profile
        mcp_trust = local_run_executor.mcp_runtime._trust_profile

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["phase"] == "ready"
    assert payload["executor"] == "ready"
    assert payload["errorCode"] is None
    assert payload["elapsedMs"] >= 0
    assert payload["startedAt"].endswith("+00:00")
    assert payload["trust"] is not None
    assert set(payload["trust"]) == {
        "source",
        "companyCaConfigured",
        "bundleConfigured",
        "tlsCompatMode",
    }
    assert pgpt_trust is not None
    assert pgpt_trust is mcp_trust
    assert TrustManager(env={}).repo_root == REPOSITORY_ROOT
    assert Path(Settings.model_config["env_file"]).resolve() == REPOSITORY_ROOT / ".env"
    completed = payload["completedPhases"]
    assert [item["phase"] for item in completed] == [
        "created",
        "initializing_trust",
        "configuring_database",
        "bootstrapping_database",
        "recovering_worker",
        "starting_scheduler",
    ]
    assert all(item["durationMs"] >= 0 for item in completed)


def test_optional_codex_warmup_does_not_block_backend_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, "background-warmup.db").model_copy(
        update={
            "environment": "development",
            "codex_cache_prewarm_enabled": True,
        }
    )
    configure_database(settings.database_url)
    create_schema()
    warmup_started = threading.Event()
    warmup_finished = threading.Event()
    release_warmup = threading.Event()

    async def blocking_warmup() -> None:
        warmup_started.set()
        try:
            await asyncio.to_thread(release_warmup.wait, 10)
        finally:
            warmup_finished.set()

    monkeypatch.setattr(local_run_executor.codex_provider, "warmup", blocking_warmup)
    with TestClient(create_app(settings)) as client:
        try:
            assert warmup_started.wait(timeout=1)
            assert not warmup_finished.is_set()
            assert client.get("/api/health/ready").status_code == 200
        finally:
            release_warmup.set()


def test_retryable_provider_failure_retries_only_before_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _RetryableProvider()
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )
    monkeypatch.setattr(
        executor_module,
        "_PROVIDER_RETRY_DELAYS_SECONDS",
        (0.0, 0.0),
        raising=False,
    )

    with TestClient(
        create_app(_settings(tmp_path, "retry-before-output.db"))
    ) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "Provider retry")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="retry-before-output",
            idempotency_key="retry-before-output-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "completed"
    assert provider.attempts == 2
    with SessionLocal() as db:
        retry_events = list(
            db.scalars(
                select(RunEvent)
                .where(
                    RunEvent.run_id == run_id,
                    RunEvent.event_type == "provider_retry_scheduled",
                )
                .order_by(RunEvent.sequence)
            )
        )
    assert len(retry_events) == 1
    assert retry_events[0].payload_json == {
        "attempt": 2,
        "maxAttempts": 3,
        "delaySeconds": 0.0,
        "stage": "response",
        "statusCode": 503,
    }


def test_hidden_progress_does_not_block_safe_provider_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _HiddenProgressThenSucceedProvider()
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )
    monkeypatch.setattr(
        executor_module,
        "_PROVIDER_RETRY_DELAYS_SECONDS",
        (0.0, 0.0),
        raising=False,
    )

    with TestClient(
        create_app(_settings(tmp_path, "retry-after-hidden-progress.db"))
    ) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "Hidden progress retry")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="retry-after-hidden-progress",
            idempotency_key="retry-after-hidden-progress-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "completed"
    assert snapshot["assistantDraft"]["text"] == "report generation recovered"
    assert provider.attempts == 2
    with SessionLocal() as db:
        retry_event = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "provider_retry_scheduled",
            )
        )
    assert retry_event is not None
    assert retry_event.payload_json["stage"] == "stream"


def test_exhausted_provider_retries_preserve_safe_failure_taxonomy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _AlwaysRetryableProvider()
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )
    monkeypatch.setattr(
        executor_module,
        "_PROVIDER_RETRY_DELAYS_SECONDS",
        (0.0, 0.0, 0.0),
        raising=False,
    )

    with TestClient(create_app(_settings(tmp_path, "retry-exhausted.db"))) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "Provider retry exhausted")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="retry-until-exhausted",
            idempotency_key="retry-until-exhausted-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "failed"
    assert snapshot["errorCode"] == "provider_network"
    assert provider.attempts == 4
    with SessionLocal() as db:
        failure = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "provider_failure_classified",
            )
        )
    assert failure is not None
    assert failure.payload_json == {
        "code": "provider_network",
        "stage": "network",
        "statusCode": 503,
        "retryable": True,
        "attemptCount": 4,
        "retryAfterSeconds": None,
    }


def test_retryable_provider_failure_continues_partial_text_without_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _RetryableProvider(partial_output=True)
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )
    monkeypatch.setattr(
        executor_module,
        "_PROVIDER_RETRY_DELAYS_SECONDS",
        (0.0, 0.0),
        raising=False,
    )

    with TestClient(
        create_app(_settings(tmp_path, "recover-after-output.db"))
    ) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "No partial replay")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="do-not-replay-partial-output",
            idempotency_key="do-not-replay-partial-output-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "completed"
    assert snapshot["assistantDraft"]["text"] == "partial response recovered response"
    assert provider.attempts == 2
    with SessionLocal() as db:
        recovery_event = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "provider_partial_response_recovery_scheduled",
            )
        )
        retry_event = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "provider_retry_scheduled",
            )
        )
    assert recovery_event is not None
    assert recovery_event.payload_json == {
        "attempt": 2,
        "maxAttempts": 3,
        "delaySeconds": 0.0,
        "stage": "response",
        "statusCode": 503,
        "preservedChars": 16,
    }
    assert retry_event is None


def test_provider_context_error_lowers_run_window_before_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _ObservedContextThenCompletingProvider()
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )

    with TestClient(
        create_app(_settings(tmp_path, "observed-context-window.db"))
    ) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "Observed context window")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="calibrate-context-window",
            idempotency_key="calibrate-context-window-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "completed"
    assert provider.attempts == 2
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        capabilities = run.snapshot_json["execution"]["capabilities"]
        assert capabilities["context_window"] == 4_096
        assert capabilities["observed_context_window"] == 4_096
        adjustment = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "provider_context_window_adjusted",
            )
        )
    assert adjustment is not None
    assert adjustment.payload_json["observedContextWindow"] == 4_096


def test_retryable_failure_resumes_unexecuted_partial_report_tool_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _PartialReportToolCallThenResumingProvider()
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )
    monkeypatch.setattr(
        executor_module,
        "_PROVIDER_RETRY_DELAYS_SECONDS",
        (0.0, 0.0),
        raising=False,
    )

    with TestClient(
        create_app(_settings(tmp_path, "partial-report-regeneration.db"))
    ) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "Partial report regeneration")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="인터넷 조사 결과를 HTML 보고서 파일로 만들어 주세요.",
            idempotency_key="regenerate-partial-report-tool-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "completed"
    assert provider.attempts == 3
    assert len(snapshot["artifacts"]) == 1
    assert [
        (tool["toolName"], tool["status"]) for tool in snapshot["toolExecutions"]
    ] == [("create_report", "completed")]
    with SessionLocal() as db:
        recovery_event = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "provider_partial_response_recovery_scheduled",
            )
        )
        discarded_event = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "provider_partial_tool_calls_discarded",
            )
        )
    assert recovery_event is not None
    assert recovery_event.payload_json["discardedToolCalls"] == 1
    assert recovery_event.payload_json["preservedReportChars"] > 0
    assert discarded_event is not None
    assert discarded_event.payload_json == {
        "toolCallCount": 1,
        "toolNames": ["create_report"],
    }


def test_valid_report_survives_discarded_malformed_sibling_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _ValidReportWithDiscardedToolCallProvider()
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )

    with TestClient(
        create_app(_settings(tmp_path, "preserved-valid-report.db"))
    ) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "Preserved valid report")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="조사 결과를 HTML 보고서 파일로 만들어 주세요.",
            idempotency_key="preserve-valid-report-tool-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "completed"
    assert provider.attempts == 2
    assert len(snapshot["artifacts"]) == 1
    assert [
        (tool["toolName"], tool["status"]) for tool in snapshot["toolExecutions"]
    ] == [("create_report", "completed")]
    with SessionLocal() as db:
        discarded_event = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "provider_partial_tool_calls_discarded",
            )
        )
        recovery_event = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "provider_partial_response_recovery_scheduled",
            )
        )
    assert discarded_event is not None
    assert discarded_event.payload_json == {
        "toolCallCount": 1,
        "toolNames": ["web_search"],
    }
    assert recovery_event is None


def test_provider_retry_delay_prefers_retry_after_and_caps_it() -> None:
    retry_after = ProviderRequestError(
        "rate limited",
        retryable=True,
        stage="rate_limit",
        retry_after_seconds=12.5,
    )
    excessive = ProviderRequestError(
        "rate limited",
        retryable=True,
        stage="rate_limit",
        retry_after_seconds=10_000,
    )

    assert executor_module._provider_retry_delay_seconds(retry_after, 0) == 12.5
    assert executor_module._provider_retry_delay_seconds(excessive, 0) == 600.0
    assert executor_module._PROVIDER_RETRY_DELAYS_SECONDS == (1.0, 2.0, 4.0)


def test_provider_retry_delay_jitters_clients_without_violating_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(executor_module.random, "uniform", lambda low, high: high)
    transient = ProviderRequestError(
        "temporary",
        retryable=True,
        stage="network",
    )
    retry_after = ProviderRequestError(
        "rate limited",
        retryable=True,
        stage="response",
        retry_after_seconds=12.0,
    )

    assert executor_module._provider_retry_delay_seconds(
        transient, 0, jitter=True
    ) == pytest.approx(executor_module._PROVIDER_RETRY_DELAYS_SECONDS[0])
    assert executor_module._provider_retry_delay_seconds(
        retry_after, 0, jitter=True
    ) == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_provider_failure_log_includes_safe_run_diagnostics(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run-safe-diagnostic"
    error = ProviderRequestError(
        "public error",
        retryable=False,
        stage="response",
        diagnostic_code="final_empty_text",
        safe_diagnostic=(
            "response_present=True response_type=str response_length=48 "
            "payload_type=dict kind=final text_type=str text_length=0 "
            "tool_calls_type=list tool_call_count=0"
        ),
    )

    async def fail_execute(_run_id: str) -> None:
        raise error

    async def no_op(_run_id: str, *_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(local_run_executor, "_execute", fail_execute)
    monkeypatch.setattr(local_run_executor, "_fail_run", no_op)
    monkeypatch.setattr(local_run_executor, "_sync_deep_analysis", no_op)
    monkeypatch.setattr(local_run_executor, "_promote_next_message", no_op)
    monkeypatch.setattr(local_run_executor, "_release_parked_ownership", no_op)

    with caplog.at_level(logging.WARNING, logger=executor_module.__name__):
        await local_run_executor._run_claimed(run_id)

    message = next(
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("Provider run failed")
    )
    assert f"run_id={run_id}" in message
    assert "stage=response" in message
    assert "diagnostic_code=final_empty_text" in message
    assert "text_length=0" in message


def test_retry_after_parser_accepts_nested_json_scalars_only() -> None:
    assert (
        openai_compatible_module._retry_after_seconds(
            {"errors": [{"metadata": {"retry_after_seconds": "12.5"}}]}
        )
        == 12.5
    )
    assert (
        openai_compatible_module._retry_after_seconds({"retry_after": 10_000}) == 600.0
    )
    for invalid in (None, True, -1, "nan", "inf", object(), {"status": 429}):
        assert openai_compatible_module._retry_after_seconds(invalid) is None


def test_continuation_deduper_handles_overlap_split_across_stream_chunks() -> None:
    deduper = executor_module._ContinuationDeduper("partial response")
    visible = (
        "".join(
            deduper.feed(chunk)
            for chunk in ("partial ", "response", " recovered", " response")
        )
        + deduper.finish()
    )

    assert visible == " recovered response"
    assert deduper.suppressed_chars == len("partial response")


@pytest.mark.asyncio
async def test_openai_compatible_propagates_retry_after_without_leaking_body() -> None:
    leaked = "provider-secret-body"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "12.5"},
            json={"error": {"message": leaked}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleAdapter(
            provider_id="openai_compatible",
            base_url="https://compatible.test/v1",
            headers={"Authorization": "Bearer local-secret"},
            client=client,
        )
        with pytest.raises(ProviderRequestError) as captured:
            _ = [
                event
                async for event in adapter.stream(
                    ProviderRequest(
                        model="model-a",
                        messages=(ProviderMessage(role="user", content="Hello"),),
                    )
                )
            ]

    assert captured.value.retry_after_seconds == 12.5
    assert leaked not in str(captured.value)


@pytest.mark.asyncio
async def test_openai_compatible_extracts_actual_context_window_safely() -> None:
    leaked = "provider-context-secret"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": ("maximum context length is 400000 tokens; " + leaked)
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleAdapter(
            provider_id="openai_compatible",
            base_url="https://compatible.test/v1",
            headers={"Authorization": "Bearer local-secret"},
            client=client,
        )
        with pytest.raises(ProviderRequestError) as captured:
            _ = [
                event
                async for event in adapter.stream(
                    ProviderRequest(
                        model="model-a",
                        messages=(ProviderMessage(role="user", content="Hello"),),
                    )
                )
            ]

    assert captured.value.stage == "context"
    assert captured.value.context_window_tokens == 400_000
    assert leaked not in str(captured.value)


def test_output_limit_continues_without_losing_or_repeating_partial_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _TruncatingThenCompletingProvider()
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )

    with TestClient(
        create_app(_settings(tmp_path, "output-continuation.db"))
    ) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "Output continuation")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="continue-output-limit",
            idempotency_key="continue-output-limit-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "completed"
    assert snapshot["assistantDraft"]["text"] == "first part second part"
    assert provider.attempts == 2


def test_empty_provider_turn_retries_instead_of_completing_blank_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _EmptyThenCompletingProvider()
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )

    with TestClient(create_app(_settings(tmp_path, "empty-turn-retry.db"))) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "Empty turn retry")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="retry-empty-provider-turn",
            idempotency_key="retry-empty-provider-turn-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "completed"
    assert snapshot["assistantDraft"]["text"] == "recovered from empty turn"
    assert provider.attempts == 2


def test_repeated_empty_provider_turn_fails_visibly_instead_of_completing_blank(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _EmptyThenCompletingProvider(always_empty=True)
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )

    with TestClient(
        create_app(_settings(tmp_path, "repeated-empty-turn.db"))
    ) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "Repeated empty turn")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="fail-repeated-empty-provider-turn",
            idempotency_key="fail-repeated-empty-provider-turn-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "failed"
    assert snapshot["assistantDraft"] is None
    assert provider.attempts == 2
    with SessionLocal() as db:
        failed_run = db.get(Run, run_id)
        assert failed_run is not None
        assert "내용 없는 응답" in str(failed_run.error_message)


def test_repeated_empty_provider_turn_preserves_completed_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _ReportThenRepeatedEmptyProvider()
    monkeypatch.setattr(
        local_run_executor, "_provider", lambda *_args, **_kwargs: provider
    )

    with TestClient(
        create_app(_settings(tmp_path, "artifact-empty-turn-recovery.db"))
    ) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "Artifact empty turn recovery")
        run_id = _start_run(
            client,
            csrf,
            conversation_id,
            text="HTML 보고서 파일을 만들어 주세요.",
            idempotency_key="artifact-empty-turn-recovery-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["status"] == "completed"
    assert snapshot["assistantDraft"]["text"] == (
        executor_module._ARTIFACT_EMPTY_RESPONSE_FALLBACK
    )
    assert len(snapshot["artifacts"]) == 1
    assert provider.attempts == 3
    with SessionLocal() as db:
        recovery_event = db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type
                == "provider_empty_response_recovered_with_artifact",
            )
        )
    assert recovery_event is not None
    assert recovery_event.payload_json == {
        "attemptCount": 2,
        "stopReason": "stop",
    }


def test_different_conversations_for_one_user_execute_in_parallel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _GateProvider(("parallel-A", "parallel-B"))
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))

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


def test_live_pause_releases_capacity_and_resume_requeues_same_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _PauseResumeProvider(("pause-capacity-A", "pause-capacity-B"))
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    settings = _settings(
        tmp_path,
        "pause-capacity.db",
        user_concurrency_limit=1,
        server_concurrency_limit=1,
    )

    with TestClient(create_app(settings)) as client:
        try:
            csrf = _login(client)
            conversation_a = _conversation(client, csrf, "Paused capacity A")
            conversation_b = _conversation(client, csrf, "Paused capacity B")
            run_a = _start_run(
                client,
                csrf,
                conversation_a,
                text="pause-capacity-A",
                idempotency_key="pause-capacity-run-a",
            )
            assert provider.entered[("pause-capacity-A", 1)].wait(timeout=2)

            paused = client.post(
                f"/api/runs/{run_a}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "pause-capacity-action",
                },
                json={"type": "pause"},
            )
            assert paused.status_code == 200, paused.text
            assert paused.json()["run"]["status"] == "paused"
            _wait_for_detached_pause(run_a)

            run_b = _start_run(
                client,
                csrf,
                conversation_b,
                text="pause-capacity-B",
                idempotency_key="pause-capacity-run-b",
            )
            assert provider.entered[("pause-capacity-B", 1)].wait(timeout=2)
            provider.release["pause-capacity-B"].set()
            assert _wait_for_terminal(client, run_b)["status"] == "completed"

            resumed = client.post(
                f"/api/runs/{run_a}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "resume-capacity-action",
                },
                json={"type": "resume"},
            )
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["run"]["status"] == "queued"
            assert provider.entered[("pause-capacity-A", 2)].wait(timeout=2)
            provider.release["pause-capacity-A"].set()
            completed = _wait_for_terminal(client, run_a)
            assert completed["status"] == "completed"
            assert completed["assistantDraft"]["text"] == (
                "completed:pause-capacity-A:attempt-2"
            )
            assert provider.attempts["pause-capacity-A"] == 2
        finally:
            provider.release_all()


def test_preparing_run_pauses_before_plan_advances_and_resumes_from_queue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preparing_entered = threading.Event()
    release_preparing = threading.Event()
    execute_attempts = 0
    original_execute = local_run_executor._execute

    async def gated_execute(run_id: str) -> None:
        nonlocal execute_attempts
        execute_attempts += 1
        if execute_attempts == 1:
            preparing_entered.set()
            released = await asyncio.to_thread(release_preparing.wait, 5.0)
            if not released:
                raise AssertionError("Preparing pause gate was not released")
        await original_execute(run_id)

    monkeypatch.setattr(local_run_executor, "_execute", gated_execute)
    settings = _settings(tmp_path, "pause-preparing.db")

    with TestClient(create_app(settings)) as client:
        try:
            csrf = _login(client)
            conversation_id = _conversation(client, csrf, "Pause preparing")
            run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text="pause while preparing",
                idempotency_key="pause-preparing-run",
            )
            assert preparing_entered.wait(timeout=2)
            paused = client.post(
                f"/api/runs/{run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "pause-preparing-action",
                },
                json={"type": "pause"},
            )
            assert paused.status_code == 200, paused.text
            assert paused.json()["run"]["status"] == "paused"
            prepare_step = next(
                step
                for step in paused.json()["run"]["plan"]["steps"]
                if step["key"] == "prepare"
            )
            assert prepare_step["status"] == "blocked"

            release_preparing.set()
            _wait_for_detached_pause(run_id)
            resumed = client.post(
                f"/api/runs/{run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "resume-preparing-action",
                },
                json={"type": "resume"},
            )
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["run"]["status"] == "queued"
            completed = _wait_for_terminal(client, run_id)
            assert completed["status"] == "completed"
            assert execute_attempts == 2
        finally:
            release_preparing.set()


def test_resume_requested_before_pause_task_exits_requeues_after_safe_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = "pause-resume-race"
    provider = _PauseResumeProvider((marker,))
    release_started = threading.Event()
    allow_release = threading.Event()
    target_run_id: str | None = None
    original_release = local_run_executor._release_parked_ownership

    async def gated_release(run_id: str) -> None:
        if run_id == target_run_id and not allow_release.is_set():
            release_started.set()
            released = await asyncio.to_thread(allow_release.wait, 5.0)
            if not released:
                raise AssertionError("Paused ownership release gate timed out")
        await original_release(run_id)

    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(local_run_executor, "_release_parked_ownership", gated_release)
    settings = _settings(tmp_path, "pause-resume-race.db")

    with TestClient(create_app(settings)) as client:
        try:
            csrf = _login(client)
            conversation_id = _conversation(client, csrf, "Pause resume race")
            target_run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text=marker,
                idempotency_key="pause-resume-race-run",
            )
            assert provider.entered[(marker, 1)].wait(timeout=2)
            paused = client.post(
                f"/api/runs/{target_run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "pause-resume-race-pause",
                },
                json={"type": "pause"},
            )
            assert paused.status_code == 200, paused.text
            assert release_started.wait(timeout=2)

            resumed = client.post(
                f"/api/runs/{target_run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "pause-resume-race-resume",
                },
                json={"type": "resume"},
            )
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["run"]["status"] == "paused"
            with SessionLocal() as db:
                run = db.get(Run, target_run_id)
                assert run is not None
                assert run.snapshot_json["resume_requested"] is True
                assert run.worker_id == local_run_executor._worker_id

            allow_release.set()
            assert provider.entered[(marker, 2)].wait(timeout=3)
            provider.release[marker].set()
            completed = _wait_for_terminal(client, target_run_id)
            assert completed["status"] == "completed"
            assert provider.attempts[marker] == 2
            with SessionLocal() as db:
                run = db.get(Run, target_run_id)
                assert run is not None
                assert "resume_requested" not in run.snapshot_json
        finally:
            allow_release.set()
            provider.release_all()


def test_model_pause_rewinds_partial_draft_and_publishes_full_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _PartialPauseProvider()
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    settings = _settings(tmp_path, "pause-partial-draft.db")

    with TestClient(create_app(settings)) as client:
        try:
            csrf = _login(client)
            conversation_id = _conversation(client, csrf, "Pause partial draft")
            run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text="pause partial draft",
                idempotency_key="pause-partial-draft-run",
            )
            assert provider.partial_processed.wait(timeout=2)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with SessionLocal() as db:
                    run = db.get(Run, run_id)
                    if (
                        run is not None
                        and run.assistant_draft == "partial-before-pause"
                    ):
                        break
                time.sleep(0.02)
            else:
                raise AssertionError("Partial assistant draft was not persisted")

            paused = client.post(
                f"/api/runs/{run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "pause-partial-draft-action",
                },
                json={"type": "pause"},
            )
            assert paused.status_code == 200, paused.text
            _wait_for_detached_pause(run_id)
            previous_transient = event_broker.latest_assistant_draft(run_id)
            assert previous_transient is not None
            previous_revision = previous_transient[0]

            resumed = client.post(
                f"/api/runs/{run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "resume-partial-draft-action",
                },
                json={"type": "resume"},
            )
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["run"]["assistantDraft"] is None
            assert provider.second_entered.wait(timeout=2)
            replacement = event_broker.latest_assistant_draft(
                run_id, after_revision=previous_revision
            )
            assert replacement is not None
            assert replacement[1] == {
                "messageId": previous_transient[1]["messageId"],
                "text": "",
                "append": False,
            }

            provider.release_second.set()
            completed = _wait_for_terminal(client, run_id)
            assert completed["status"] == "completed"
            assert completed["assistantDraft"]["text"] == "final-after-resume"
            assert provider.attempts == 2
        finally:
            provider.release_second.set()


def test_pause_after_provider_completed_event_parks_before_final_transition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = "pause-after-provider-completed"
    provider = _PauseResumeProvider((marker,))
    provider.release[marker].set()
    metrics_boundary = threading.Event()
    release_metrics_boundary = threading.Event()
    metric_calls = 0
    original_record_metrics = local_run_executor._record_model_turn_metrics

    async def gated_record_metrics(*args, **kwargs):
        nonlocal metric_calls
        await original_record_metrics(*args, **kwargs)
        metric_calls += 1
        if metric_calls == 1:
            metrics_boundary.set()
            released = await asyncio.to_thread(release_metrics_boundary.wait, 5.0)
            if not released:
                raise AssertionError("Provider completion boundary was not released")

    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(
        local_run_executor, "_record_model_turn_metrics", gated_record_metrics
    )
    settings = _settings(tmp_path, "pause-after-provider-completed.db")

    with TestClient(create_app(settings)) as client:
        try:
            csrf = _login(client)
            conversation_id = _conversation(
                client, csrf, "Pause after provider completion"
            )
            run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text=marker,
                idempotency_key="pause-after-provider-completed-run",
            )
            assert metrics_boundary.wait(timeout=5)
            paused = client.post(
                f"/api/runs/{run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "pause-after-provider-completed-action",
                },
                json={"type": "pause"},
            )
            assert paused.status_code == 200, paused.text
            assert paused.json()["run"]["status"] == "paused"
            release_metrics_boundary.set()
            _wait_for_detached_pause(run_id)
            with SessionLocal() as db:
                run = db.get(Run, run_id)
                assert run is not None and run.status == "paused"
                assert "model_turn_inflight" in run.snapshot_json

            resumed = client.post(
                f"/api/runs/{run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "resume-after-provider-completed-action",
                },
                json={"type": "resume"},
            )
            assert resumed.status_code == 200, resumed.text
            completed = _wait_for_terminal(client, run_id)
            assert completed["status"] == "completed"
            assert completed["assistantDraft"]["text"] == (
                f"completed:{marker}:attempt-2"
            )
        finally:
            release_metrics_boundary.set()

    assert provider.attempts[marker] == 2


def test_paused_run_resumes_after_worker_restart_without_duplicate_draft(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = "pause-worker-restart"
    provider = _PauseResumeProvider((marker,))
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    settings = _settings(tmp_path, "pause-worker-restart.db")

    with TestClient(create_app(settings)) as first_client:
        csrf = _login(first_client)
        conversation_id = _conversation(first_client, csrf, "Pause restart")
        run_id = _start_run(
            first_client,
            csrf,
            conversation_id,
            text=marker,
            idempotency_key="pause-worker-restart-run",
        )
        assert provider.entered[(marker, 1)].wait(timeout=2)
        paused = first_client.post(
            f"/api/runs/{run_id}/actions",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "pause-before-worker-restart",
            },
            json={"type": "pause"},
        )
        assert paused.status_code == 200, paused.text
        _wait_for_detached_pause(run_id)

    with SessionLocal() as db:
        parked = db.get(Run, run_id)
        assert parked is not None and parked.status == "paused"
        assert parked.worker_id is None

    with TestClient(create_app(settings)) as second_client:
        try:
            csrf = _login(second_client)
            resumed = second_client.post(
                f"/api/runs/{run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "resume-after-worker-restart",
                },
                json={"type": "resume"},
            )
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["run"]["status"] == "queued"
            assert provider.entered[(marker, 2)].wait(timeout=2)
            provider.release[marker].set()
            completed = _wait_for_terminal(second_client, run_id)
            assert completed["status"] == "completed"
            assert completed["assistantDraft"]["text"] == (
                f"completed:{marker}:attempt-2"
            )
            assert provider.attempts[marker] == 2
            with SessionLocal() as db:
                assistant_messages = list(
                    db.scalars(
                        select(Message).where(
                            Message.run_id == run_id,
                            Message.role == "assistant",
                        )
                    )
                )
                assert len(assistant_messages) == 1
                assert assistant_messages[0].canonical_text == (
                    f"completed:{marker}:attempt-2"
                )
        finally:
            provider.release_all()


def test_steer_after_provider_tool_response_applies_before_tool_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _ToolBoundarySteerProvider()
    update_plan_invocations = 0
    original_update_work_plan = executor_module.update_work_plan

    def counting_update_work_plan(*args, **kwargs):
        nonlocal update_plan_invocations
        update_plan_invocations += 1
        return original_update_work_plan(*args, **kwargs)

    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(executor_module, "update_work_plan", counting_update_work_plan)
    settings = _settings(tmp_path, "steer-before-tool-execution.db")

    with TestClient(create_app(settings)) as client:
        try:
            csrf = _login(client)
            conversation_id = _conversation(client, csrf, "Steer before tool execution")
            run_id = _start_run(
                client,
                csrf,
                conversation_id,
                text="prepare a tool call",
                idempotency_key="steer-before-tool-run",
            )
            assert provider.boundary_reached.wait(timeout=2)
            steered = client.post(
                f"/api/runs/{run_id}/actions",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": "steer-before-tool-action",
                },
                json={
                    "type": "steer",
                    "message": {
                        "text": "reply-in-chat-instead",
                        "attachmentIds": [],
                        "promptReferences": [],
                    },
                },
            )
            assert steered.status_code == 200, steered.text
            assert steered.json()["command"]["status"] == "waiting_safe_boundary"
            provider.release_boundary.set()

            completed = _wait_for_terminal(client, run_id)
            assert completed["status"] == "completed"
            assert completed["assistantDraft"]["text"] == (
                "steering applied before tool execution"
            )
            assert provider.attempts == 2
            assert update_plan_invocations == 0
            with SessionLocal() as db:
                command = db.scalar(
                    select(RunCommand).where(
                        RunCommand.run_id == run_id,
                        RunCommand.command_type == "steer",
                    )
                )
                assert command is not None and command.status == "applied"
        finally:
            provider.release_boundary.set()


def test_completed_tool_batch_is_checkpointed_once_across_pause_and_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _ToolPauseProvider()
    tool_batch_completed = threading.Event()
    release_tool_boundary = threading.Event()
    tool_batch_invocations = 0
    update_plan_invocations = 0
    original_run_tool_calls = local_run_executor._run_tool_calls
    original_update_work_plan = executor_module.update_work_plan

    def counting_update_work_plan(*args, **kwargs):
        nonlocal update_plan_invocations
        update_plan_invocations += 1
        return original_update_work_plan(*args, **kwargs)

    async def gated_run_tool_calls(*args, **kwargs):
        nonlocal tool_batch_invocations
        result = await original_run_tool_calls(*args, **kwargs)
        tool_batch_invocations += 1
        if tool_batch_invocations == 1:
            tool_batch_completed.set()
            released = await asyncio.to_thread(release_tool_boundary.wait, 5.0)
            if not released:
                raise AssertionError("Tool safe-boundary gate was not released")
        return result

    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(local_run_executor, "_run_tool_calls", gated_run_tool_calls)
    monkeypatch.setattr(executor_module, "update_work_plan", counting_update_work_plan)
    settings = _settings(tmp_path, "pause-tool-restart.db")

    with TestClient(create_app(settings)) as first_client:
        csrf = _login(first_client)
        conversation_id = _conversation(first_client, csrf, "Pause tool restart")
        run_id = _start_run(
            first_client,
            csrf,
            conversation_id,
            text="pause a completed tool batch",
            idempotency_key="pause-tool-restart-run",
        )
        assert tool_batch_completed.wait(timeout=2)
        paused = first_client.post(
            f"/api/runs/{run_id}/actions",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "pause-completed-tool-batch",
            },
            json={"type": "pause"},
        )
        assert paused.status_code == 200, paused.text
        release_tool_boundary.set()
        _wait_for_detached_pause(run_id)
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            checkpoint = run.snapshot_json.get("tool_checkpoint")
            assert isinstance(checkpoint, dict)
            assert checkpoint["kind"] == "completed_tools"
            assert checkpoint["provider_tool_contents"]

    with TestClient(create_app(settings)) as second_client:
        csrf = _login(second_client)
        resumed = second_client.post(
            f"/api/runs/{run_id}/actions",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "resume-completed-tool-batch",
            },
            json={"type": "resume"},
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["run"]["status"] == "queued"
        completed = _wait_for_terminal(second_client, run_id)
        assert completed["status"] == "completed"
        assert completed["assistantDraft"]["text"] == ("tool checkpoint resumed once")

    assert provider.attempts == 2
    assert tool_batch_invocations == 1
    assert update_plan_invocations == 1
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        assert "tool_checkpoint" not in run.snapshot_json


def test_tool_and_steer_transcript_order_survives_worker_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _OrderedToolSteerRecoveryProvider()
    update_plan_invocations = 0
    original_update_work_plan = executor_module.update_work_plan

    def counting_update_work_plan(*args, **kwargs):
        nonlocal update_plan_invocations
        update_plan_invocations += 1
        return original_update_work_plan(*args, **kwargs)

    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(executor_module, "update_work_plan", counting_update_work_plan)
    settings = _settings(tmp_path, "ordered-tool-steer-restart.db")

    def steer(
        client: TestClient, csrf: str, run_id: str, marker: str, key: str
    ) -> None:
        response = client.post(
            f"/api/runs/{run_id}/actions",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
            json={
                "type": "steer",
                "message": {
                    "text": marker,
                    "attachmentIds": [],
                    "promptReferences": [],
                },
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["command"]["status"] == "waiting_safe_boundary"

    with TestClient(create_app(settings)) as first_client:
        csrf = _login(first_client)
        conversation_id = _conversation(
            first_client, csrf, "Ordered tool and steer recovery"
        )
        run_id = _start_run(
            first_client,
            csrf,
            conversation_id,
            text="preserve the exact tool and steer transcript",
            idempotency_key="ordered-tool-steer-run",
        )
        assert provider.prefix_gate.wait(timeout=5)
        steer(
            first_client,
            csrf,
            run_id,
            "prefix-steer",
            "ordered-prefix-steer",
        )
        assert provider.post_a_gate.wait(timeout=5)
        steer(
            first_client,
            csrf,
            run_id,
            "post-a-steer",
            "ordered-post-a-steer",
        )
        assert provider.post_b_gate.wait(timeout=5)
        steer(
            first_client,
            csrf,
            run_id,
            "post-b-steer",
            "ordered-post-b-steer",
        )
        assert provider.crash_gate.wait(timeout=5)
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            checkpoint = run.snapshot_json.get("tool_checkpoint")
            assert isinstance(checkpoint, dict)
            assert checkpoint["captures_applied_steers"] is True
            assert len(checkpoint["prefix_user_message_ids"]) == 1
            assert [entry["role"] for entry in checkpoint["prefix_transcript"]] == [
                "assistant",
                "user",
            ]
            assert len(checkpoint["completed_batches"]) == 1
            assert (
                len(checkpoint["completed_batches"][0]["post_batch_user_message_ids"])
                == 1
            )
            assert [
                entry["role"]
                for entry in checkpoint["completed_batches"][0]["post_batch_transcript"]
            ] == ["assistant", "user"]
            assert len(checkpoint["post_batch_user_message_ids"]) == 1
            assert [entry["role"] for entry in checkpoint["post_batch_transcript"]] == [
                "assistant",
                "user",
            ]

    with TestClient(create_app(settings)) as second_client:
        _login(second_client)
        completed = _wait_for_terminal(second_client, run_id)
        assert completed["status"] == "completed"
        assert completed["assistantDraft"]["text"] == (
            "partial-prefix|partial-post-a|partial-post-b|"
            "ordered tool transcript recovered once"
        )

    assert provider.attempts == 7
    assert provider.recovery_request is not None
    assert update_plan_invocations == 2


def test_prefix_steer_transcript_survives_restart_before_first_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _PrefixSteerRestartProvider()
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    settings = _settings(tmp_path, "prefix-steer-restart.db")

    with TestClient(create_app(settings)) as first_client:
        csrf = _login(first_client)
        conversation_id = _conversation(
            first_client, csrf, "Prefix steer recovery before any tool"
        )
        run_id = _start_run(
            first_client,
            csrf,
            conversation_id,
            text="preserve a steer before the first tool",
            idempotency_key="prefix-steer-restart-run",
        )
        assert provider.steer_gate.wait(timeout=5)
        steered = first_client.post(
            f"/api/runs/{run_id}/actions",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "prefix-steer-before-tool",
            },
            json={
                "type": "steer",
                "message": {
                    "text": "prefix-crash-steer",
                    "attachmentIds": [],
                    "promptReferences": [],
                },
            },
        )
        assert steered.status_code == 200, steered.text
        assert provider.crash_gate.wait(timeout=5)
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            assert "tool_checkpoint" not in run.snapshot_json
            assert [
                entry["role"]
                for entry in run.snapshot_json["tool_checkpoint_prefix_transcript"]
            ] == ["assistant", "user"]
            marker = run.snapshot_json["model_turn_inflight"]
            assert marker["draftCheckpoint"] == len("partial-prefix-crash|")

    with TestClient(create_app(settings)) as second_client:
        _login(second_client)
        completed = _wait_for_terminal(second_client, run_id)
        assert completed["status"] == "completed"
        assert completed["assistantDraft"]["text"] == (
            "partial-prefix-crash|prefix transcript restored once"
        )

    assert provider.attempts == 3


def test_auto_continuation_transcript_survives_worker_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _ContinuationRestartProvider()
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    settings = _settings(tmp_path, "continuation-restart.db")

    with TestClient(create_app(settings)) as first_client:
        csrf = _login(first_client)
        conversation_id = _conversation(
            first_client, csrf, "Automatic continuation recovery"
        )
        run_id = _start_run(
            first_client,
            csrf,
            conversation_id,
            text="continue a truncated answer exactly once",
            idempotency_key="continuation-restart-run",
        )
        assert provider.crash_gate.wait(timeout=5)
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            transcript = run.snapshot_json["tool_checkpoint_prefix_transcript"]
            assert [entry["role"] for entry in transcript] == ["assistant", "user"]
            assert transcript[1]["content"] == executor_module._CONTINUATION_PROMPT
            assert run.snapshot_json["model_turn_inflight"]["draftCheckpoint"] == len(
                "truncated-prefix|"
            )

    with TestClient(create_app(settings)) as second_client:
        _login(second_client)
        completed = _wait_for_terminal(second_client, run_id)
        assert completed["status"] == "completed"
        assert completed["assistantDraft"]["text"] == (
            "truncated-prefix|continuation restored once"
        )

    assert provider.attempts == 3


def test_pending_tool_checkpoint_reuses_inline_result_after_worker_stops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _ToolPauseProvider()
    checkpoint_crash = threading.Event()
    completed_checkpoint_attempts = 0
    update_plan_invocations = 0
    original_store_checkpoint = local_run_executor._store_tool_checkpoint
    original_update_work_plan = executor_module.update_work_plan

    def counting_update_work_plan(*args, **kwargs):
        nonlocal update_plan_invocations
        update_plan_invocations += 1
        return original_update_work_plan(*args, **kwargs)

    async def crash_before_first_completed_checkpoint(*args, **kwargs):
        nonlocal completed_checkpoint_attempts
        if kwargs.get("kind") == "completed_tools":
            completed_checkpoint_attempts += 1
            if completed_checkpoint_attempts == 1:
                checkpoint_crash.set()
                raise asyncio.CancelledError
        return await original_store_checkpoint(*args, **kwargs)

    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    monkeypatch.setattr(
        local_run_executor,
        "_store_tool_checkpoint",
        crash_before_first_completed_checkpoint,
    )
    monkeypatch.setattr(executor_module, "update_work_plan", counting_update_work_plan)
    settings = _settings(tmp_path, "pending-tool-worker-stop.db")

    with TestClient(create_app(settings)) as first_client:
        csrf = _login(first_client)
        conversation_id = _conversation(first_client, csrf, "Pending tool recovery")
        run_id = _start_run(
            first_client,
            csrf,
            conversation_id,
            text="recover a pending tool call",
            idempotency_key="pending-tool-worker-stop-run",
        )
        assert checkpoint_crash.wait(timeout=5)
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            checkpoint = run.snapshot_json.get("tool_checkpoint")
            assert isinstance(checkpoint, dict)
            assert checkpoint["kind"] == "pending_tools"
            assert checkpoint["calls"][0]["id"] == "call_pause_update_plan"

    with TestClient(create_app(settings)) as second_client:
        csrf = _login(second_client)
        completed = _wait_for_terminal(second_client, run_id)
        assert completed["status"] == "completed"
        assert completed["assistantDraft"]["text"] == ("tool checkpoint resumed once")

    assert provider.attempts == 2
    assert completed_checkpoint_attempts == 2
    assert update_plan_invocations == 1


def test_expired_crashed_worker_lease_is_recovered_without_another_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = "crashed-worker-lease-recovery"
    provider = _PauseResumeProvider((marker,))
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))
    settings = _settings(tmp_path, "expired-crashed-worker.db")

    with TestClient(create_app(settings)) as first_client:
        csrf = _login(first_client)
        conversation_id = _conversation(first_client, csrf, "Crash lease recovery")
        run_id = _start_run(
            first_client,
            csrf,
            conversation_id,
            text=marker,
            idempotency_key="crashed-worker-lease-run",
        )
        assert provider.entered[(marker, 1)].wait(timeout=5)

    with SessionLocal.begin() as db:
        run = db.get(Run, run_id)
        assert run is not None
        run.status = "paused"
        run.finished_at = None
        run.error_code = None
        run.error_message = None
        pause_plan(db, run)
        run.snapshot_json = {
            **run.snapshot_json,
            "resume_status": "model_streaming",
            "resume_requested": True,
            "resume_requested_at": utc_now().isoformat(),
        }
        run.worker_id = "worker-process-that-crashed"
        run.heartbeat_at = utc_now()
        # App startup can exceed a few hundred milliseconds under the full suite.
        # Keep the lease live long enough to observe the paused state before the
        # same executor recovers it after expiry.
        run.lease_expires_at = utc_now() + timedelta(seconds=2)

    provider.release[marker].set()
    with TestClient(create_app(settings)) as second_client:
        _login(second_client)
        initial = second_client.get(f"/api/runs/{run_id}/snapshot")
        assert initial.status_code == 200, initial.text
        assert initial.json()["status"] == "paused"
        completed = _wait_for_terminal(second_client, run_id)
        assert completed["status"] == "completed"

    assert provider.attempts[marker] == 2


def test_same_conversation_second_run_stays_queued_until_first_finishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _GateProvider(("serial-first", "serial-second"))
    monkeypatch.setattr(local_run_executor, "_provider", _gate_factory(provider))

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

            time.sleep(0.1)
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
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with SessionLocal() as db:
                    queued = db.get(QueuedMessage, queued_message_id)
                    if queued is not None and queued.status == "promoted":
                        break
                time.sleep(0.01)
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
        "html_source": (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<title>Replay contract report</title></head><body><main>"
            "<h1>Replay contract report</h1>"
            "<p>Replay must preserve every persisted event.</p>"
            "<section><h2>Replay</h2><p>Text, tool, and artifact state remains "
            "canonical.</p><ul><li>No gaps</li><li>No duplicates</li></ul></section>"
            "<p>Reconnect from the last applied sequence.</p></main></body></html>"
        ),
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

    async def no_wait(
        _run_id: str,
        timeout: float = 15.0,
        *,
        after_revision: int | None = None,
    ) -> tuple[int, bool]:
        del timeout
        return after_revision or 0, True

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


def test_sse_transient_draft_wake_does_not_poll_the_database(tmp_path: Path) -> None:
    with TestClient(
        create_app(_settings(tmp_path, "sse-transient-draft.db"))
    ) as client:
        csrf = _login(client)
        conversation_id = _conversation(client, csrf, "SSE transient draft")
        session_token = client.cookies.get("lumina_session")
        assert session_token

        with SessionLocal() as db:
            conversation = db.get(Conversation, conversation_id)
            auth_session = db.scalar(
                select(AuthSession).where(AuthSession.revoked_at.is_(None))
            )
            assert conversation is not None and auth_session is not None
            user = db.get(User, auth_session.user_id)
            assert user is not None
            run = Run(
                organization_id=conversation.organization_id,
                project_id=conversation.project_id,
                conversation_id=conversation.id,
                user_id=user.id,
                status="model_streaming",
                provider_id="mock",
                model_key="mock-agent",
                runtime_model_id="mock-agent",
                model_display_name="Mock Agent",
                snapshot_json={},
                usage_json={},
            )
            db.add(run)
            db.commit()
            run_id = run.id
            response = asyncio.run(
                stream_run(
                    run_id,
                    _ConnectedRequest(),  # type: ignore[arg-type]
                    0,
                    None,
                    AuthContext(user, auth_session, session_token),
                    db,
                )
            )
            bind = db.get_bind()

        statement_count = 0

        def count_statement(*_args: object) -> None:
            nonlocal statement_count
            statement_count += 1

        async def exercise() -> None:
            iterator = response.body_iterator
            first = await anext(iterator)
            assert first == ": keep-alive\n\n"
            initial_statement_count = statement_count

            next_chunk = asyncio.create_task(anext(iterator))
            await asyncio.sleep(0)
            await event_broker.publish_assistant_draft(
                run_id,
                "message-1",
                "실시간 초안",
            )
            chunk = await asyncio.wait_for(next_chunk, timeout=1)
            assert isinstance(chunk, str)
            assert chunk.startswith("event: assistant_draft")
            payload = json.loads(chunk.split("data: ", maxsplit=1)[1])
            assert payload["draft"] == {
                "messageId": "message-1",
                "text": "실시간 초안",
                "append": False,
            }
            next_chunk = asyncio.create_task(anext(iterator))
            await asyncio.sleep(0)
            await event_broker.publish_assistant_draft(
                run_id,
                "message-1",
                " 추가",
            )
            chunk = await asyncio.wait_for(next_chunk, timeout=1)
            assert isinstance(chunk, str)
            payload = json.loads(chunk.split("data: ", maxsplit=1)[1])
            assert payload["draft"] == {
                "messageId": "message-1",
                "text": " 추가",
                "append": True,
            }
            assert statement_count == initial_statement_count
            await iterator.aclose()

        sqlalchemy_event.listen(bind, "before_cursor_execute", count_statement)
        try:
            asyncio.run(exercise())
        finally:
            sqlalchemy_event.remove(bind, "before_cursor_execute", count_statement)
            event_broker.discard(run_id)


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
            stored_run = db.get(Run, run_id)
            assert stored_run is not None
            assert stored_run.snapshot_json["artifact_usage"]["tokens"] > 0
            assert stored_run.snapshot_json["artifact_usage"]["lines"] > 0
            stored_run.snapshot_json = {
                key: value
                for key, value in stored_run.snapshot_json.items()
                if key != "artifact_usage"
            }
            db.commit()
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
        assert progress[0] == {"tokens": 0, "lines": 0, "estimated": True}
        assert any(item.get("modelOutputTokens", 0) > 0 for item in progress)
        assert progress[-1]["tokens"] > 0
        assert progress[-1]["lines"] > 0
        assert snapshot_json["artifactUsage"] == progress[-1]
