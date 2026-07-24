from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.agent.executor import _ARTIFACT_CREATION_REQUEST, local_run_executor
from lumina.api.errors import ApiProblem
from lumina.artifacts.service import create_artifact
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Extension, ExtensionVersion, Run, User, new_uuid
from lumina.providers import MockProvider, MockToolCall
from lumina.runs.approvals import classify_tool_risk
from lumina.tools.python_execution import (
    MAX_PYTHON_OUTPUT_BYTES,
    PYTHON_EXECUTION_TOOL_SCHEMA,
    PreparedPythonExecution,
    PythonExecutionPolicy,
    execute_python,
    prepare_python_execution,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'python-execution.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"loginName": "admin", "loginDomain": "posco.com", "password": "1"},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def _run_context(
    client: TestClient, headers: dict[str, str], *, title: str
) -> tuple[str, str]:
    project_id = client.get("/api/projects").json()[0]["id"]
    conversation = client.post(
        "/api/conversations",
        headers=headers,
        json={"projectId": project_id, "title": title},
    ).json()
    response = client.post(
        f"/api/conversations/{conversation['id']}/runs",
        headers={**headers, "Idempotency-Key": f"{title}-run"},
        json={"message": {"text": "Python을 준비합니다."}},
    )
    assert response.status_code == 202, response.text
    return project_id, response.json()["run"]["runId"]


def _wait_for_status(
    client: TestClient, run_id: str, expected: set[str]
) -> dict[str, object]:
    deadline = time.monotonic() + 7
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in expected:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not reach {sorted(expected)}")


def test_python_tool_schema_and_approval_contract() -> None:
    assert PYTHON_EXECUTION_TOOL_SCHEMA["function"]["name"] == "run_python"
    schema = PYTHON_EXECUTION_TOOL_SCHEMA["function"]["parameters"]
    assert schema["allOf"][0]["then"]["required"] == [
        "artifact_id",
        "artifact_version",
    ]
    assert schema["properties"]["profile"]["enum"] == ["standard", "heavy"]
    assert schema["properties"]["input_json"]["type"] == "string"
    on_risk = classify_tool_risk("run_python", approval_mode="on_risk")
    assert on_risk.effect == "local_execution"
    assert on_risk.risk_level == "high"
    assert on_risk.approval_required is True
    assert (
        classify_tool_risk("run_python", approval_mode="confirm_all").approval_required
        is True
    )
    assert classify_tool_risk(
        "run_python", approval_mode="yolo"
    ).approval_required is False
    assert _ARTIFACT_CREATION_REQUEST.search("hello.py를 작성해 주세요")


def test_python_artifact_is_frozen_and_executed_with_utf8_output(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    prepared = None
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id, run_id = _run_context(client, headers, title="python-artifact")
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert run is not None and user is not None
            artifact, version = create_artifact(
                db,
                local_run_executor.storage,
                user=user,
                project_id=project_id,
                conversation_id=run.conversation_id,
                source_run_id=run.id,
                display_name="hello.py",
                kind="py",
                mime_type="text/x-python",
                content=(
                    "import sys\n"
                    "print('한글 출력')\n"
                    "print(sys.argv[1])\n"
                    "print(\"api_key='secret-value-123'\")\n"
                ).encode("utf-8"),
                change_type="agent_generated",
            )
            with pytest.raises(ValueError, match="artifact_version"):
                prepare_python_execution(
                    db,
                    local_run_executor.storage,
                    run=run,
                    user=user,
                    arguments={
                        "source": "artifact",
                        "artifact_id": artifact.id,
                    },
                )
            with pytest.raises(ValueError, match="활성 Skill"):
                prepare_python_execution(
                    db,
                    local_run_executor.storage,
                    run=run,
                    user=user,
                    arguments={
                        "source": "artifact",
                        "artifact_id": artifact.id,
                        "artifact_version": version.version_number,
                        "profile": "heavy",
                    },
                    policy=PythonExecutionPolicy(heavy_enabled=True),
                )
            prepared = prepare_python_execution(
                db,
                local_run_executor.storage,
                run=run,
                user=user,
                arguments={
                    "source": "artifact",
                    "artifact_id": artifact.id,
                    "artifact_version": version.version_number,
                    "args": ["argument-ok"],
                    "timeout_seconds": 10,
                },
            )
            db.commit()

    assert prepared is not None
    result = asyncio.run(
        execute_python(prepared, secrets=("secret-value-123",))
    )

    assert result["ok"] is True
    assert result["returnCode"] == 0
    assert result["source"]["artifactVersion"] == 1
    assert "한글 출력" in result["stdout"]
    assert "argument-ok" in result["stdout"]
    assert "secret-value-123" not in result["stdout"]
    assert "[REDACTED]" in result["stdout"]


def test_agent_run_exposes_python_and_resumes_after_high_risk_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    artifact_id = ""
    requests = []

    class RecordingProvider(MockProvider):
        async def stream(self, request):
            requests.append(request)
            async for event in super().stream(request):
                yield event

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        del wants_artifact
        if first_turn:
            return RecordingProvider(
                tool_call=MockToolCall(
                    name="run_python",
                    arguments={
                        "source": "artifact",
                        "artifact_id": artifact_id,
                        "artifact_version": 1,
                        "args": [],
                        "timeout_seconds": 10,
                    },
                    call_id="run-python-approved",
                )
            )
        return RecordingProvider(text_chunks=("Python 실행을 확인했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        safety = client.get("/api/admin/run-safety").json()
        updated = client.patch(
            "/api/admin/run-safety",
            headers=headers,
            json={**safety, "yoloMode": False},
        )
        assert updated.status_code == 200, updated.text
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "approved Python"},
        ).json()
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert user is not None
            artifact, _version = create_artifact(
                db,
                local_run_executor.storage,
                user=user,
                project_id=project_id,
                conversation_id=conversation["id"],
                source_run_id=None,
                display_name="approved.py",
                kind="py",
                mime_type="text/x-python",
                content=b"print('approved-ok')\n",
                change_type="agent_generated",
            )
            artifact_id = artifact.id
            db.commit()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                **headers,
                "Idempotency-Key": "approved-python-run",
            },
            json={"message": {"text": "이 Python 파일을 실행해 주세요."}},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]
        waiting = _wait_for_status(client, run_id, {"awaiting_approval"})
        approval = waiting["pendingApprovals"][0]
        assert approval["toolName"] == "run_python"
        assert approval["effect"] == "local_execution"
        approved = client.post(
            f"/api/runs/{run_id}/actions",
            headers={
                **headers,
                "Idempotency-Key": "approve-python-run",
            },
            json={"type": "approve", "approvalId": approval["id"]},
        )
        assert approved.status_code == 200, approved.text
        completed = _wait_for_status(client, run_id, {"completed"})

    assert completed["toolExecutions"][0]["result"]["ok"] is True
    assert "approved-ok" in completed["toolExecutions"][0]["result"]["stdout"]
    assert requests
    tool_names = {
        schema["function"]["name"]
        for schema in requests[0].tools
        if isinstance(schema.get("function"), dict)
    }
    assert "run_python" in tool_names
    assert len(requests) >= 2
    tool_result_message = next(
        message for message in requests[-1].messages if message.role == "tool"
    )
    assert tool_result_message.content is not None
    assert "approved-ok" in tool_result_message.content
    assert "<untrusted_tool_result" in tool_result_message.content


def test_active_skill_module_uses_exact_version_package(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    prepared = None
    heavy_prepared = None
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        _project_id, run_id = _run_context(client, headers, title="python-skill")
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert run is not None and user is not None
            extension = Extension(
                kind="skill",
                slug="python-fixture",
                name="python-fixture",
                description="Python fixture",
                owner_user_id=user.id,
                creator_user_id=user.id,
                organization_id=user.organization_id,
                visibility="private",
            )
            db.add(extension)
            db.flush()
            package = {
                "SKILL.md": (
                    "---\nname: python-fixture\ndescription: fixture\n---\n"
                ),
                "engine/__init__.py": "VALUE = 'snapshot-ok'\n",
                "engine/__main__.py": (
                    "import sys\n"
                    "from pydantic import BaseModel\n"
                    "from . import VALUE\n"
                    "class ProgramInput(BaseModel):\n"
                    "    amount: int\n"
                    "print(VALUE)\n"
                    "print(sys.argv[1])\n"
                    "payload = sys.stdin.read()\n"
                    "if payload:\n"
                    "    print(ProgramInput.model_validate_json(payload).amount * 2)\n"
                ),
            }
            version = ExtensionVersion(
                extension_id=extension.id,
                version_number=1,
                package_json=package,
                package_digest="a" * 64,
                manifest_json={},
                status="published",
                created_by_user_id=user.id,
            )
            db.add(version)
            db.flush()
            run.snapshot_json = {
                **run.snapshot_json,
                "extensions": [
                    {
                        "extension_id": extension.id,
                        "slug": extension.slug,
                        "name": extension.name,
                        "source": "version",
                        "version_id": version.id,
                        "version": 1,
                        "digest": version.package_digest,
                        "instructions": package["SKILL.md"],
                    }
                ],
                "auto_selected_skill_ids": [extension.id],
            }
            prepared = prepare_python_execution(
                db,
                local_run_executor.storage,
                run=run,
                user=user,
                arguments={
                    "source": "skill",
                    "skill_id": extension.id,
                    "module": "engine",
                    "args": ["module-argument"],
                    "timeout_seconds": 10,
                },
            )
            heavy_prepared = prepare_python_execution(
                db,
                local_run_executor.storage,
                run=run,
                user=user,
                arguments={
                    "source": "skill",
                    "skill_id": extension.id,
                    "module": "engine",
                    "profile": "heavy",
                    "args": ["heavy-argument"],
                    "input_json": '{"amount": 21}',
                    "timeout_seconds": 3_600,
                },
                policy=PythonExecutionPolicy(
                    heavy_enabled=True,
                    heavy_max_timeout_seconds=7_200,
                    executable=sys.executable,
                ),
            )
            db.commit()

    assert prepared is not None
    result = asyncio.run(execute_python(prepared))

    assert result["ok"] is True
    assert result["stdout"].splitlines() == ["snapshot-ok", "module-argument"]
    assert result["source"]["digest"] == "a" * 64
    assert result["source"]["version"] == 1
    assert heavy_prepared is not None
    assert heavy_prepared.profile == "heavy"
    assert heavy_prepared.timeout_seconds == 3_600
    assert Path(heavy_prepared.executable).resolve() == Path(sys.executable).resolve()
    heavy_result = asyncio.run(execute_python(heavy_prepared))
    assert heavy_result["ok"] is True
    assert heavy_result["profile"] == "heavy"
    assert heavy_result["stdout"].splitlines() == [
        "snapshot-ok",
        "heavy-argument",
        "42",
    ]


def test_inactive_skill_and_unsafe_entrypoint_are_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        _project_id, run_id = _run_context(client, headers, title="python-rejected")
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert run is not None and user is not None
            with pytest.raises(ApiProblem, match="활성화"):
                prepare_python_execution(
                    db,
                    local_run_executor.storage,
                    run=run,
                    user=user,
                    arguments={
                        "source": "skill",
                        "skill_id": new_uuid(),
                        "path": "../outside.py",
                    },
                )
            with pytest.raises(ValueError, match="관리자가 활성화"):
                prepare_python_execution(
                    db,
                    local_run_executor.storage,
                    run=run,
                    user=user,
                    arguments={
                        "source": "skill",
                        "skill_id": new_uuid(),
                        "module": "engine",
                        "profile": "heavy",
                    },
                )
            with pytest.raises(ValueError, match="실행 파일"):
                prepare_python_execution(
                    db,
                    local_run_executor.storage,
                    run=run,
                    user=user,
                    arguments={
                        "source": "skill",
                        "skill_id": new_uuid(),
                        "module": "engine",
                    },
                    policy=PythonExecutionPolicy(
                        executable=str(tmp_path / "missing-python")
                    ),
                )
            with pytest.raises(ValueError, match="올바른 JSON"):
                prepare_python_execution(
                    db,
                    local_run_executor.storage,
                    run=run,
                    user=user,
                    arguments={
                        "source": "skill",
                        "skill_id": new_uuid(),
                        "module": "engine",
                        "input_json": "{broken",
                    },
                )
            with pytest.raises(ValueError, match="최상위 값은 object"):
                prepare_python_execution(
                    db,
                    local_run_executor.storage,
                    run=run,
                    user=user,
                    arguments={
                        "source": "skill",
                        "skill_id": new_uuid(),
                        "module": "engine",
                        "input_json": "[1, 2]",
                    },
                )


def test_python_timeout_and_output_limit() -> None:
    timed = PreparedPythonExecution(
        source_type="artifact",
        files={"slow.py": "import time\ntime.sleep(5)\n"},
        entrypoint="slow.py",
        module=None,
        args=(),
        timeout_seconds=1,
        source_metadata={"artifactId": "fixture", "artifactVersion": 1},
    )
    timed_result = asyncio.run(execute_python(timed))
    assert timed_result["ok"] is False
    assert timed_result["timedOut"] is True
    assert timed_result["durationMs"] < 5_000

    noisy = PreparedPythonExecution(
        source_type="artifact",
        files={"noisy.py": f"print('x' * {MAX_PYTHON_OUTPUT_BYTES + 50_000})\n"},
        entrypoint="noisy.py",
        module=None,
        args=(),
        timeout_seconds=10,
        source_metadata={"artifactId": "fixture", "artifactVersion": 1},
    )
    noisy_result = asyncio.run(execute_python(noisy))
    assert noisy_result["ok"] is True
    assert noisy_result["stdoutTruncated"] is True
    assert len(noisy_result["stdout"].encode("utf-8")) <= MAX_PYTHON_OUTPUT_BYTES


def test_heavy_python_cancellation_stops_the_process() -> None:
    prepared = PreparedPythonExecution(
        source_type="skill",
        files={"worker.py": "import time\ntime.sleep(60)\n"},
        entrypoint="worker.py",
        module=None,
        args=(),
        timeout_seconds=3_600,
        source_metadata={"skillId": "fixture", "digest": "a" * 64},
        profile="heavy",
    )

    async def cancel_execution() -> None:
        task = asyncio.create_task(execute_python(prepared))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    started = time.monotonic()
    asyncio.run(cancel_execution())
    assert time.monotonic() - started < 5
