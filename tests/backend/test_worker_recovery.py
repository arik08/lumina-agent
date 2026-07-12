from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from lumina.api.schemas import RunCreate, RunMessageInput
from lumina.agent.executor import LocalRunExecutor, _parse_session_title_line
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.models import (
    Conversation,
    Plan,
    PlanStep,
    PlanSubtask,
    Project,
    Run,
    ToolExecution,
    User,
    utc_now,
)
from lumina.runs.recovery import mark_model_turn_inflight, prepare_worker_recovery
from lumina.runs.recovery import mark_worker_shutdown_interrupted
from lumina.runs.service import (
    complete_plan_step,
    create_run,
    start_plan_step,
    transition_run,
)
from lumina.runs.state import (
    AWAITING_APPROVAL,
    COMPLETED,
    MODEL_STREAMING,
    PREPARING,
    QUEUED,
    TOOLS_RUNNING,
)
from lumina.runs.subtasks import bind_tool_subtask, ensure_tool_subtasks


def test_session_title_control_line_parser_is_strict_and_bounded() -> None:
    assert _parse_session_title_line('{"session_title":"  검색   품질 개선  "}') == "검색 품질 개선"
    assert _parse_session_title_line('{"session_title":"' + "가" * 80 + '"}') == "가" * 60
    assert _parse_session_title_line('{"session_title":""}') is None
    assert _parse_session_title_line('{"session_title":"제목","answer":"본문"}') is None
    assert _parse_session_title_line("일반 답변") is None


def test_worker_recovery_rewinds_only_the_inflight_model_draft(tmp_path: Path) -> None:
    run_id = _direct_run(tmp_path, "model-recovery")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        run.assistant_draft = "이전 단계 설명. "
        run.usage_json = {"model_turns": 2, "input_tokens": 30}
        mark_model_turn_inflight(db, run, turn_index=1)
        run.assistant_draft += "전송 중이던 일부 응답"
        db.commit()

    with SessionLocal() as db:
        batch = prepare_worker_recovery(db)
        db.commit()
        assert batch.resumable_run_ids == (run_id,)
        run = db.get(Run, run_id)
        assert run is not None
        assert run.status == QUEUED
        assert run.assistant_draft == "이전 단계 설명. "
        assert run.usage_json["model_turns"] == 1
        assert "model_turn_inflight" not in run.snapshot_json
        assert run.snapshot_json["workerRecoveryCount"] == 1


def test_worker_recovery_never_replays_an_unknown_tool_outcome(tmp_path: Path) -> None:
    run_id = _direct_run(tmp_path, "tool-recovery")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        complete_plan_step(db, run, "model", reason="test_model_completed")
        transition_run(db, run, TOOLS_RUNNING)
        start_plan_step(db, run, "tools", reason="test_tools")
        ensure_tool_subtasks(
            db,
            run,
            [
                {
                    "id": "call-running",
                    "name": "create_report",
                    "arguments": '{"title":"secret-free"}',
                },
                {
                    "id": "call-not-started",
                    "name": "web_search",
                    "arguments": '{"query":"status"}',
                },
            ],
        )
        tool = ToolExecution(
            run_id=run.id,
            tool_call_id="call-running",
            tool_name="create_report",
            validated_input_json={"title": "secret-free"},
            status="running",
            started_at=utc_now(),
        )
        db.add(tool)
        db.flush()
        bind_tool_subtask(db, run.id, tool)
        db.commit()

    with SessionLocal() as db:
        batch = prepare_worker_recovery(db)
        db.commit()
        assert batch.resumable_run_ids == (run_id,)
        run = db.get(Run, run_id)
        assert run is not None and run.status == QUEUED
        tool = db.scalar(select(ToolExecution).where(ToolExecution.run_id == run_id))
        assert tool is not None
        assert tool.status == "failed"
        assert tool.error_code == "worker_restarted_unknown_outcome"
        plan = db.scalar(select(Plan).where(Plan.run_id == run_id))
        assert plan is not None
        tools_step = db.scalar(
            select(PlanStep).where(
                PlanStep.plan_id == plan.id,
                PlanStep.step_key == "tools",
            )
        )
        assert tools_step is not None and tools_step.status == "queued"
        subtasks = list(
            db.scalars(
                select(PlanSubtask)
                .where(PlanSubtask.plan_step_id == tools_step.id)
                .order_by(PlanSubtask.position)
            )
        )
        assert [subtask.status for subtask in subtasks] == ["failed", "failed"]
        assert subtasks[0].error_code == "worker_restarted_unknown_outcome"
        assert subtasks[1].error_code == "worker_restarted_before_execution"


def test_graceful_shutdown_records_interrupted_then_schedules_recovery(
    tmp_path: Path,
) -> None:
    run_id = _direct_run(tmp_path, "graceful-recovery")
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        _move_to_model(db, run)
        interrupted = mark_worker_shutdown_interrupted(db)
        db.commit()
        assert interrupted == (run_id,)
        assert run.status == "interrupted"
        assert run.error_code == "worker_interrupted"
        assert run.snapshot_json["workerRecoverable"] is True

    with SessionLocal() as db:
        batch = prepare_worker_recovery(db)
        db.commit()
        assert batch.resumable_run_ids == (run_id,)
        run = db.get(Run, run_id)
        assert run is not None
        assert run.status == QUEUED
        assert run.error_code is None
        assert "workerRecoverable" not in run.snapshot_json


def test_executor_start_recovers_model_turn_and_parks_approval(tmp_path: Path) -> None:
    recovered_run_id = _direct_run(tmp_path, "executor-recovery")
    with SessionLocal() as db:
        recovered = db.get(Run, recovered_run_id)
        assert recovered is not None
        _move_to_model(db, recovered)
        recovered.assistant_draft = "전송 중 응답"
        recovered.usage_json = {"model_turns": 1}
        mark_model_turn_inflight(db, recovered, turn_index=0)
        db.commit()

    approval_run_id = _add_run_to_current_database("approval-parked")
    with SessionLocal() as db:
        approval = db.get(Run, approval_run_id)
        assert approval is not None
        _move_to_model(db, approval)
        transition_run(db, approval, AWAITING_APPROVAL)
        approval.snapshot_json = {
            **approval.snapshot_json,
            "tool_checkpoint": {"approval_ids": ["pending"]},
        }
        db.commit()

    executor = LocalRunExecutor(_settings(tmp_path, "executor-recovery"))

    async def exercise() -> None:
        await executor.start()
        for _ in range(200):
            with SessionLocal() as db:
                status = db.scalar(select(Run.status).where(Run.id == recovered_run_id))
            if status == COMPLETED:
                break
            await asyncio.sleep(0.01)
        assert status == COMPLETED
        with SessionLocal() as db:
            approval_status = db.scalar(
                select(Run.status).where(Run.id == approval_run_id)
            )
        assert approval_status == AWAITING_APPROVAL
        await executor.stop()

    asyncio.run(exercise())

    with SessionLocal() as db:
        approval = db.get(Run, approval_run_id)
        assert approval is not None and approval.status == AWAITING_APPROVAL


def _direct_run(tmp_path: Path, key: str) -> str:
    settings = _settings(tmp_path, key)
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    return _add_run_to_current_database(key)


def _settings(tmp_path: Path, key: str) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / f'{key}.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _add_run_to_current_database(key: str) -> str:
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        project = db.scalar(select(Project).where(Project.owner_user_id == admin.id))
        assert admin is not None and project is not None
        conversation = Conversation(
            organization_id=admin.organization_id,
            project_id=project.id,
            owner_user_id=admin.id,
            title="Worker recovery",
        )
        db.add(conversation)
        db.flush()
        run, _message, _created = create_run(
            db,
            user=admin,
            conversation_id=conversation.id,
            payload=RunCreate(message=RunMessageInput(text="복구 테스트")),
            idempotency_key=f"run-{key}",
        )
        db.commit()
        return run.id


def _move_to_model(db, run: Run) -> None:
    transition_run(db, run, PREPARING)
    start_plan_step(db, run, "prepare", reason="test_preparing")
    complete_plan_step(db, run, "prepare", reason="test_prepared")
    transition_run(db, run, MODEL_STREAMING)
    start_plan_step(db, run, "model", reason="test_model")
