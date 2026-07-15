from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lumina.agent.executor import local_run_executor
from lumina.api.errors import ApiProblem
from lumina.api.schemas import RunActionRequest, RunCreate, RunMessageInput
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.main import create_app
from lumina.models import (
    Conversation,
    Plan,
    PlanStep,
    PlanSubtask,
    Project,
    Run,
    RunCommand,
    RunEvent,
    ToolExecution,
    User,
    utc_now,
)
from lumina.providers import ProviderConfigurationError
from lumina.runs.service import (
    align_work_plan_for_tool_start,
    apply_run_action,
    complete_plan_step,
    create_run,
    fail_plan,
    plan_snapshot,
    start_plan_step,
    transition_run,
    update_work_plan,
)
from lumina.runs.state import (
    CANCELLED,
    COMPLETED,
    FAILED,
    MODEL_STREAMING,
    PAUSED,
    PREPARING,
    QUEUED,
    TOOLS_RUNNING,
)
from lumina.runs.subtasks import (
    bind_tool_subtask,
    ensure_tool_subtasks,
    finish_tool_subtask,
    list_step_subtasks,
)


def _settings(tmp_path: Path, name: str = "plan.db") -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrfToken"])


def _wait_for_status(
    client: TestClient, run_id: str, statuses: set[str], timeout: float = 5
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in statuses:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"Run did not reach one of {sorted(statuses)}")


def _direct_run(tmp_path: Path, *, key: str) -> tuple[str, str]:
    settings = _settings(tmp_path, f"{key}.db")
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        project = db.scalar(select(Project).where(Project.owner_user_id == admin.id))
        assert admin is not None and project is not None
        conversation = Conversation(
            organization_id=admin.organization_id,
            project_id=project.id,
            owner_user_id=admin.id,
            title="Plan 상태 테스트",
        )
        db.add(conversation)
        db.flush()
        run, _message, _created = create_run(
            db,
            user=admin,
            conversation_id=conversation.id,
            payload=RunCreate(
                message=RunMessageInput(text="점검 결과를 정리해 주세요.")
            ),
            idempotency_key=f"run-{key}",
        )
        db.commit()
        return run.id, admin.id


def _move_to_model(db: Session, run: Run) -> dict[str, PlanStep]:
    transition_run(db, run, PREPARING)
    start_plan_step(db, run, "prepare", reason="test_preparing")
    complete_plan_step(db, run, "prepare", reason="test_prepared")
    transition_run(db, run, MODEL_STREAMING)
    start_plan_step(db, run, "model", reason="test_model")
    plan = db.scalar(select(Plan).where(Plan.run_id == run.id))
    assert plan is not None
    return {
        step.step_key: step
        for step in db.scalars(
            select(PlanStep)
            .where(PlanStep.plan_id == plan.id)
            .order_by(PlanStep.position)
        )
    }


def test_model_authored_work_plan_is_persisted_with_stable_step_ids(
    tmp_path: Path,
) -> None:
    run_id, _user_id = _direct_run(tmp_path, key="work-plan")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        initial = update_work_plan(
            db,
            run,
            steps=[
                {"step": "설비 이력에서 반복 고장 구간 추출", "status": "in_progress"},
                {"step": "고장 원인별 근거와 빈도 비교", "status": "pending"},
                {"step": "우선 정비 대상과 판단 근거 정리", "status": "pending"},
            ],
        )
        updated = update_work_plan(
            db,
            run,
            steps=[
                {"step": "설비 이력에서 반복 고장 구간 추출", "status": "completed"},
                {"step": "고장 원인별 근거와 빈도 비교", "status": "in_progress"},
                {"step": "우선 정비 대상과 판단 근거 정리", "status": "pending"},
            ],
        )
        db.commit()

        assert [step["id"] for step in updated] == [step["id"] for step in initial]
        assert [step["status"] for step in updated] == [
            "completed",
            "in_progress",
            "pending",
        ]
        assert run.snapshot_json["work_plan"] == updated
        events = list(
            db.scalars(
                select(RunEvent)
                .where(
                    RunEvent.run_id == run.id,
                    RunEvent.event_type == "work_plan_updated",
                )
                .order_by(RunEvent.sequence)
            )
        )
        assert len(events) == 2
        assert events[-1].payload_json["steps"] == updated


def test_work_plan_stays_active_until_the_run_completes(tmp_path: Path) -> None:
    run_id, _user_id = _direct_run(tmp_path, key="work-plan-final-stream")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        transition_run(db, run, PREPARING)
        transition_run(db, run, MODEL_STREAMING)

        initial_plan = update_work_plan(
            db,
            run,
            steps=[
                {"step": "근거를 확인합니다", "status": "in_progress"},
                {"step": "최종 답변을 작성합니다", "status": "pending"},
            ],
        )

        with pytest.raises(ValueError, match="최종 답변 작성"):
            update_work_plan(
                db,
                run,
                steps=[
                    {"step": "근거를 확인합니다", "status": "completed"},
                    {"step": "최종 답변을 작성합니다", "status": "completed"},
                ],
            )
        assert run.snapshot_json["work_plan"] == initial_plan

        streaming_plan = update_work_plan(
            db,
            run,
            steps=[
                {"step": "근거를 확인합니다", "status": "completed"},
                {"step": "최종 답변을 작성합니다", "status": "in_progress"},
            ],
        )
        assert [item["status"] for item in streaming_plan] == ["completed", "in_progress"]

        transition_run(db, run, COMPLETED, event_type="run_completed")

        assert [item["status"] for item in run.snapshot_json["work_plan"]] == [
            "completed",
            "completed",
        ]
        event_types = list(
            db.scalars(
                select(RunEvent.event_type)
                .where(RunEvent.run_id == run.id)
                .order_by(RunEvent.sequence)
            )
        )
        assert event_types[-2:] == ["work_plan_updated", "run_completed"]


def test_create_report_start_aligns_legacy_work_plan_to_report_drafting(
    tmp_path: Path,
) -> None:
    run_id, _user_id = _direct_run(tmp_path, key="report-plan-alignment")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        update_work_plan(
            db,
            run,
            steps=[
                {"step": "국내외 기사 원문 근거를 확인합니다", "status": "completed"},
                {
                    "step": "보도 이슈를 리스크 관점으로 분류합니다",
                    "status": "in_progress",
                },
                {
                    "step": "확인된 자료로 HTML 보고서를 작성합니다",
                    "status": "pending",
                },
                {
                    "step": "보고서의 근거와 누락 여부를 점검합니다",
                    "status": "pending",
                },
            ],
        )
        db.commit()

    asyncio.run(
        local_run_executor._start_streaming_artifact_tool(
            run_id,
            {"id": "call-create-report", "name": "create_report", "arguments": ""},
        )
    )

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        assert [item["status"] for item in run.snapshot_json["work_plan"]] == [
            "completed",
            "completed",
            "in_progress",
            "pending",
        ]
        assert run.snapshot_json["work_plan"][2]["phase"] == "drafting"
        events = list(
            db.scalars(
                select(RunEvent)
                .where(
                    RunEvent.run_id == run_id,
                    RunEvent.event_type.in_(["work_plan_updated", "tool_started"]),
                )
                .order_by(RunEvent.sequence)
            )
        )
        assert [event.event_type for event in events[-2:]] == [
            "work_plan_updated",
            "tool_started",
        ]
        assert events[-1].payload_json["execution"]["toolName"] == "create_report"


def test_create_report_alignment_does_not_advance_past_active_drafting(
    tmp_path: Path,
) -> None:
    run_id, _user_id = _direct_run(tmp_path, key="report-plan-already-drafting")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        initial = update_work_plan(
            db,
            run,
            steps=[
                {
                    "step": "자료를 분석합니다",
                    "status": "completed",
                    "phase": "analysis",
                },
                {
                    "step": "HTML 보고서를 작성합니다",
                    "status": "in_progress",
                    "phase": "drafting",
                },
                {
                    "step": "완성된 보고서를 검수합니다",
                    "status": "pending",
                    "phase": "validation",
                },
            ],
        )
        event_count = db.scalar(
            select(func.count(RunEvent.id)).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "work_plan_updated",
            )
        )

        aligned = align_work_plan_for_tool_start(
            db, run, tool_name="create_report"
        )

        assert aligned is None
        assert run.snapshot_json["work_plan"] == initial
        assert db.scalar(
            select(func.count(RunEvent.id)).where(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "work_plan_updated",
            )
        ) == event_count


def test_tool_calls_are_durable_plan_subtasks_without_raw_arguments(
    tmp_path: Path,
) -> None:
    run_id, _user_id = _direct_run(tmp_path, key="subtasks")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        created = ensure_tool_subtasks(
            db,
            run,
            [
                {
                    "id": "call-search",
                    "name": "web_search",
                    "arguments": '{"query":"secret query"}',
                },
                {
                    "id": "call-report",
                    "name": "create_report",
                    "arguments": '{"title":"private title"}',
                },
            ],
        )
        assert [item["status"] for item in created] == ["queued", "queued"]
        assert all(item["dependsOn"] == [] for item in created)
        assert "secret query" not in str(created)
        assert "private title" not in str(created)

        tool = ToolExecution(
            run_id=run.id,
            tool_call_id="call-search",
            tool_name="web_search",
            validated_input_json={"queryLength": 12},
            status="running",
            started_at=utc_now(),
        )
        db.add(tool)
        db.flush()
        running = bind_tool_subtask(db, run.id, tool)
        assert running is not None and running["status"] == "running"

        tool.status = "completed"
        tool.result_summary = "검색 결과 2건"
        tool.finished_at = utc_now()
        completed = finish_tool_subtask(db, tool)
        assert completed is not None and completed["status"] == "completed"
        db.commit()

        plan = db.scalar(select(Plan).where(Plan.run_id == run.id))
        assert plan is not None
        tools_step = db.scalar(
            select(PlanStep).where(
                PlanStep.plan_id == plan.id, PlanStep.step_key == "tools"
            )
        )
        assert tools_step is not None
        subtasks = list_step_subtasks(db, tools_step.id)
        assert [item["toolCallId"] for item in subtasks] == [
            "call-search",
            "call-report",
        ]
        assert db.scalar(select(func.count(PlanSubtask.id))) == 2


def test_executor_persists_db_owned_plan_timeline_and_events(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "Plan 통합"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={**headers, "Idempotency-Key": "plan-integration-0001"},
            json={
                "message": {
                    "text": "점검 결과를 HTML 보고서 Artifact로 만들어 주세요.",
                    "attachmentIds": [],
                    "promptReferences": [],
                }
            },
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]
        snapshot = _wait_for_status(client, run_id, {"completed"})
        plan = snapshot["plan"]
        assert plan["status"] == "completed"
        steps = {step["key"]: step for step in plan["steps"]}
        assert list(steps) == ["prepare", "model", "tools", "final"]
        assert {step["status"] for step in steps.values()} == {"completed"}
        assert steps["tools"]["artifactIds"] == [snapshot["artifacts"][0]["id"]]
        assert steps["tools"]["effect"] == "side_effect"

        plan_response = client.get(f"/api/runs/{run_id}/plan")
        assert plan_response.status_code == 200
        assert plan_response.json()["id"] == plan["id"]

        replay = client.get(f"/stream/runs/{run_id}?after_sequence=0")
        events = [
            json.loads(line.removeprefix("data: "))
            for line in replay.text.splitlines()
            if line.startswith("data: ")
        ]
        plan_changes = [
            (event["payload"]["step"]["key"], event["payload"]["step"]["status"])
            for event in events
            if event["type"] == "plan_step_changed"
        ]
        assert all(
            "plan" not in event["payload"]
            for event in events
            if event["type"] == "plan_step_changed"
        )
        for expected in (
            ("prepare", "running"),
            ("prepare", "completed"),
            ("model", "running"),
            ("model", "completed"),
            ("tools", "running"),
            ("tools", "completed"),
            ("final", "running"),
            ("final", "completed"),
        ):
            assert expected in plan_changes

        plain = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={**headers, "Idempotency-Key": "plan-integration-0002"},
            json={
                "message": {
                    "text": "간단히 인사해 주세요.",
                    "attachmentIds": [],
                    "promptReferences": [],
                }
            },
        )
        plain_snapshot = _wait_for_status(
            client, plain.json()["run"]["runId"], {"completed"}
        )
        plain_tools = next(
            step for step in plain_snapshot["plan"]["steps"] if step["key"] == "tools"
        )
        assert plain_tools["status"] == "completed"
        assert plain_tools["result"] == {"tool_execution_count": 0, "skipped": True}
        assert plain_tools["attempt"] == 0

    with SessionLocal() as db:
        assert db.scalar(select(func.count(Plan.id))) == 2
        assert db.scalar(select(func.count(PlanStep.id))) == 8


def test_pause_resume_cancel_and_retry_keep_plan_consistent(tmp_path: Path) -> None:
    run_id, admin_id = _direct_run(tmp_path, key="actions")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        admin = db.get(User, admin_id)
        assert run is not None and admin is not None
        steps = _move_to_model(db, run)

        _run, _command, _message, changed = apply_run_action(
            db,
            user=admin,
            run_id=run.id,
            payload=RunActionRequest(type="pause"),
            idempotency_key="pause-action-1",
        )
        assert changed is True and run.status == PAUSED
        assert steps["model"].status == "blocked"
        assert plan_snapshot(db, run)["status"] == "paused"

        apply_run_action(
            db,
            user=admin,
            run_id=run.id,
            payload=RunActionRequest(type="resume"),
            idempotency_key="resume-action-1",
        )
        assert run.status == MODEL_STREAMING
        assert steps["model"].status == "running"

        apply_run_action(
            db,
            user=admin,
            run_id=run.id,
            payload=RunActionRequest(type="cancel"),
            idempotency_key="cancel-action-1",
        )
        assert run.status == CANCELLED
        assert steps["prepare"].status == "completed"
        assert {steps[key].status for key in ("model", "tools", "final")} == {
            "cancelled"
        }
        assert plan_snapshot(db, run)["status"] == "cancelled"

        _run, command, _message, retried = apply_run_action(
            db,
            user=admin,
            run_id=run.id,
            payload=RunActionRequest(type="retry_step", step_id=steps["model"].id),
            idempotency_key="retry-action-1",
        )
        assert retried is True and command.status == "applied"
        assert run.status == QUEUED
        assert {steps[key].status for key in ("model", "tools", "final")} == {"queued"}
        assert steps["prepare"].status == "completed"
        assert plan_snapshot(db, run)["status"] == "active"

        _run, duplicate, _message, duplicate_changed = apply_run_action(
            db,
            user=admin,
            run_id=run.id,
            payload=RunActionRequest(type="retry_step", step_id=steps["model"].id),
            idempotency_key="retry-action-1",
        )
        assert duplicate_changed is False and duplicate.id == command.id
        assert (
            db.scalar(
                select(func.count(RunCommand.id)).where(
                    RunCommand.idempotency_key == "retry-action-1"
                )
            )
            == 1
        )
        event_types = list(
            db.scalars(
                select(RunEvent.event_type)
                .where(RunEvent.run_id == run.id)
                .order_by(RunEvent.sequence)
            )
        )
        assert "retry_scheduled" in event_types


def test_failed_step_retry_and_unsafe_tool_retry_contract(tmp_path: Path) -> None:
    run_id, admin_id = _direct_run(tmp_path, key="failed")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        admin = db.get(User, admin_id)
        assert run is not None and admin is not None
        steps = _move_to_model(db, run)
        fail_plan(db, run, code="provider_failed", message="Provider 실패")
        transition_run(db, run, FAILED, event_type="run_failed")
        assert steps["model"].status == "failed"
        assert steps["tools"].status == "cancelled"
        apply_run_action(
            db,
            user=admin,
            run_id=run.id,
            payload=RunActionRequest(type="retry_step", step_id=steps["model"].id),
            idempotency_key="retry-failed-model",
        )
        assert run.status == QUEUED

    unsafe_run_id, unsafe_admin_id = _direct_run(tmp_path, key="unsafe")
    with SessionLocal() as db:
        run = db.get(Run, unsafe_run_id)
        admin = db.get(User, unsafe_admin_id)
        assert run is not None and admin is not None
        steps = _move_to_model(db, run)
        complete_plan_step(db, run, "model", reason="test_model_completed")
        start_plan_step(db, run, "tools", reason="test_tool_started")
        transition_run(db, run, TOOLS_RUNNING)
        fail_plan(db, run, code="tool_failed", message="부작용 Tool 실패")
        transition_run(db, run, FAILED, event_type="run_failed")
        assert steps["tools"].status == "failed"
        assert steps["tools"].attempt == 1
        with pytest.raises(ApiProblem) as error:
            apply_run_action(
                db,
                user=admin,
                run_id=run.id,
                payload=RunActionRequest(type="retry_step", step_id=steps["tools"].id),
                idempotency_key="retry-unsafe-tool",
            )
        assert error.value.code == "step_retry_checkpoint_unavailable"
        assert db.scalar(select(func.count(RunCommand.id))) == 0


def test_retry_requested_before_old_executor_task_finishes_is_reenqueued(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, "retry-race.db")
    first_failure_stored = threading.Event()
    release_first_task = threading.Event()
    original_fail_run = local_run_executor._fail_run
    failure_count = 0

    def failing_provider(*_args, **_kwargs):
        raise ProviderConfigurationError("의도한 Provider 실패")

    async def blocking_first_fail(run_id: str, code: str, message: str) -> None:
        nonlocal failure_count
        await original_fail_run(run_id, code, message)
        failure_count += 1
        if failure_count == 1:
            first_failure_stored.set()
            await asyncio.to_thread(release_first_task.wait)

    monkeypatch.setattr(local_run_executor, "_provider", failing_provider)
    monkeypatch.setattr(local_run_executor, "_fail_run", blocking_first_fail)

    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "retry race"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={**headers, "Idempotency-Key": "retry-race-run"},
            json={"message": {"text": "실패해 주세요."}},
        )
        run_id = started.json()["run"]["runId"]
        first = _wait_for_status(client, run_id, {"failed"})
        assert first_failure_stored.wait(timeout=2)
        model_step = next(
            step for step in first["plan"]["steps"] if step["key"] == "model"
        )

        retried = client.post(
            f"/api/runs/{run_id}/actions",
            headers={**headers, "Idempotency-Key": "retry-race-action"},
            json={"type": "retry_step", "stepId": model_step["id"]},
        )
        assert retried.status_code == 200, retried.text
        assert retried.json()["run"]["status"] == "queued"
        release_first_task.set()

        second = _wait_for_status(client, run_id, {"failed"})
        second_model = next(
            step for step in second["plan"]["steps"] if step["key"] == "model"
        )
        assert second_model["attempt"] == 2
        assert failure_count >= 2
