from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lumina.api.errors import ApiProblem, install_error_handlers
from lumina.api.routes import auth, composer
from lumina.api.schemas import (
    MessageReferenceInput,
    RunActionRequest,
    RunCreate,
    RunMessageInput,
)
from lumina.auth import bootstrap_database, create_user
from lumina.agent.executor import _skill_activation_tool_schema
from lumina.config import Settings, get_settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.extensions.service import create_skill, resolve_skill_snapshot, update_draft
from lumina.models import (
    Artifact,
    ArtifactVersion,
    Attachment,
    Conversation,
    MessageReference,
    Organization,
    Project,
    ProjectMembership,
    QueuedMessage,
    RunCommand,
    User,
)
from lumina.runs.approvals import classify_tool_risk
from lumina.runs.service import (
    _skill_activities,
    activate_run_skill,
    append_event,
    apply_run_action,
    create_run,
    run_snapshot,
)


def test_implicit_skill_activation_requires_a_model_tool_choice() -> None:
    extensions = [
        {
            "extension_id": "visual-id",
            "slug": "visual-artifact",
            "name": "Visual Artifact",
            "description": "HTML 시각 보고서를 제작합니다.",
            "instructions": "Create a polished standalone HTML report.",
            "version": 1,
            "digest": "visual-digest",
        },
        {
            "extension_id": "pptx-id",
            "slug": "pptx-writer",
            "name": "PPTX Writer",
            "description": "프레젠테이션을 제작합니다.",
            "instructions": "Create a presentation.",
            "version": 1,
            "digest": "pptx-digest",
        },
    ]
    run = SimpleNamespace(
        snapshot_json={
            "extensions": extensions,
            "extension_application": "explicit_references",
            "prompt_references": [],
        }
    )

    assert _skill_activities(run) == []
    schema = _skill_activation_tool_schema(run.snapshot_json)
    assert schema is not None
    assert schema["function"]["name"] == "activate_skill"
    assert schema["function"]["parameters"]["properties"]["skillId"]["enum"] == [
        "visual-id",
        "pptx-id",
    ]
    assert (
        classify_tool_risk("activate_skill", approval_mode="on_risk").approval_required
        is False
    )

    selected = activate_run_skill(
        run,
        skill_id="visual-id",
        reason="요청한 시장 동향을 읽기 쉬운 HTML 보고서로 구성하기 위해 선택했습니다.",
    )

    assert selected["extension_id"] == "visual-id"
    assert run.snapshot_json["auto_selected_skill_ids"] == ["visual-id"]
    assert _skill_activities(run)[0]["reason"] == (
        "요청한 시장 동향을 읽기 쉬운 HTML 보고서로 구성하기 위해 선택했습니다."
    )


def test_skill_activities_show_which_skill_was_actually_applied() -> None:
    extensions = [
        {
            "extension_id": "visual-id",
            "slug": "visual-artifact",
            "name": "Visual Artifact",
            "version": 3,
            "digest": "visual-digest",
        },
        {
            "extension_id": "explicit-id",
            "slug": "inspection-report",
            "name": "점검 보고서",
            "draft_revision": 4,
            "digest": "draft-digest",
        },
        {
            "extension_id": "unused-id",
            "slug": "unused-skill",
            "name": "사용 안 함",
            "version": 1,
            "digest": "unused-digest",
        },
    ]
    run = SimpleNamespace(
        snapshot_json={
            "extensions": extensions,
            "extension_application": "explicit_and_auto",
            "auto_selected_skill_ids": ["visual-id"],
            "prompt_references": [{"kind": "skill", "reference_id": "explicit-id"}],
        }
    )

    assert _skill_activities(run) == [
        {
            "id": "skill:visual-id:visual-digest",
            "type": "skill",
            "sequence": -3,
            "skillId": "visual-id",
            "name": "Visual Artifact",
            "slug": "visual-artifact",
            "versionLabel": "v3",
            "appliedBy": "auto",
            "reason": "보고서 HTML 시각 산출물 제작",
        },
        {
            "id": "skill:explicit-id:draft-digest",
            "type": "skill",
            "sequence": -2,
            "skillId": "explicit-id",
            "name": "점검 보고서",
            "slug": "inspection-report",
            "versionLabel": "Draft r4",
            "appliedBy": "explicit",
            "reason": "요청에 맞는 작업 절차 적용",
        },
    ]


def _setup(tmp_path: Path) -> tuple[FastAPI, dict[str, str]]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)

    with SessionLocal() as db:
        organization = db.scalar(select(Organization))
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert organization is not None and admin is not None
        project = db.scalar(select(Project).where(Project.owner_user_id == admin.id))
        assert project is not None
        other_project = Project(
            organization_id=organization.id,
            owner_user_id=admin.id,
            name="다른 프로젝트",
            concept="격리 검증",
        )
        db.add(other_project)
        db.flush()
        conversation = Conversation(
            organization_id=organization.id,
            project_id=project.id,
            owner_user_id=admin.id,
            title="참조 검증",
        )
        other_conversation = Conversation(
            organization_id=organization.id,
            project_id=other_project.id,
            owner_user_id=admin.id,
            title="다른 프로젝트 대화",
        )
        db.add_all([conversation, other_conversation])
        db.flush()

        member = create_user(
            db,
            login_name="member",
            password="pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        db.add(
            ProjectMembership(
                project_id=project.id,
                user_id=member.id,
                role="member",
                status="active",
                created_by_user_id=admin.id,
            )
        )

        attachment = Attachment(
            organization_id=organization.id,
            project_id=project.id,
            conversation_id=conversation.id,
            owner_user_id=admin.id,
            kind="document",
            original_filename="점검표.xlsx",
            sniffed_mime_type="application/vnd.ms-excel",
            size_bytes=128,
            content_hash="file-sha256-v1",
            storage_key="attachments/project-a/checklist.xlsx",
            status="ready",
        )
        other_attachment = Attachment(
            organization_id=organization.id,
            project_id=other_project.id,
            conversation_id=other_conversation.id,
            owner_user_id=admin.id,
            kind="document",
            original_filename="비공개.xlsx",
            sniffed_mime_type="application/vnd.ms-excel",
            size_bytes=64,
            content_hash="other-file-sha256-v1",
            storage_key="attachments/project-b/private.xlsx",
            status="ready",
        )
        db.add_all([attachment, other_attachment])

        artifact = Artifact(
            organization_id=organization.id,
            project_id=project.id,
            conversation_id=conversation.id,
            created_by_user_id=admin.id,
            display_name="설비 점검 보고서",
            kind="html",
            mime_type="text/html",
            current_version_number=1,
        )
        other_artifact = Artifact(
            organization_id=organization.id,
            project_id=other_project.id,
            conversation_id=other_conversation.id,
            created_by_user_id=admin.id,
            display_name="다른 보고서",
            kind="html",
            mime_type="text/html",
            current_version_number=1,
        )
        db.add_all([artifact, other_artifact])
        db.flush()
        artifact_version = ArtifactVersion(
            artifact_id=artifact.id,
            version_number=1,
            storage_key="artifacts/project-a/report-v1.html",
            content_hash="artifact-sha256-v1",
            size_bytes=256,
            change_type="create",
            validation_status="valid",
            created_by_user_id=admin.id,
        )
        other_artifact_version = ArtifactVersion(
            artifact_id=other_artifact.id,
            version_number=1,
            storage_key="artifacts/project-b/report-v1.html",
            content_hash="other-artifact-sha256-v1",
            size_bytes=128,
            change_type="create",
            validation_status="valid",
            created_by_user_id=admin.id,
        )
        db.add_all([artifact_version, other_artifact_version])

        skill, draft = create_skill(
            db,
            user=admin,
            name="점검 보고서 작성",
            slug="inspection-report",
            description="설비 점검 보고서를 작성합니다.",
            package_files={"SKILL.md": "# 점검 보고서\n\n초기 절차를 따릅니다."},
            project_id=project.id,
        )
        db.commit()
        ids = {
            "admin_id": admin.id,
            "member_id": member.id,
            "project_id": project.id,
            "other_project_id": other_project.id,
            "conversation_id": conversation.id,
            "other_conversation_id": other_conversation.id,
            "attachment_id": attachment.id,
            "other_attachment_id": other_attachment.id,
            "artifact_id": artifact.id,
            "other_artifact_id": other_artifact.id,
            "artifact_digest": artifact_version.content_hash,
            "skill_id": skill.id,
            "draft_id": draft.id,
            "draft_digest": draft.current_digest,
        }

    application = FastAPI()
    application.state.settings = settings
    application.dependency_overrides[get_settings] = lambda: settings
    install_error_handlers(application)
    for module in (auth, composer):
        application.include_router(module.router, prefix="/api")
    return application, ids


def test_model_selected_skill_keeps_its_event_sequence_in_run_snapshot(
    tmp_path: Path,
) -> None:
    _app, ids = _setup(tmp_path)
    with SessionLocal() as db:
        admin = db.get(User, ids["admin_id"])
        assert admin is not None
        run, _message, created = create_run(
            db,
            user=admin,
            conversation_id=ids["conversation_id"],
            payload=RunCreate(
                message=RunMessageInput(
                    text="시장 동향 보고서를 작성해 주세요.",
                    attachment_ids=[],
                    prompt_references=[],
                )
            ),
            idempotency_key="model-skill-selection-1",
        )
        assert created is True
        assert "auto_selected_skill_ids" not in run.snapshot_json

        selected = activate_run_skill(
            run,
            skill_id=ids["skill_id"],
            reason="설비 점검 보고서 절차가 요청에 적합합니다.",
        )
        activity = next(
            item
            for item in _skill_activities(run)
            if item["skillId"] == selected["extension_id"]
        )
        event = append_event(db, run, "skill_selected", {"activity": activity})
        db.flush()

        snapshot = run_snapshot(db, run)
        selected_activity = next(
            item for item in snapshot["activities"] if item["type"] == "skill"
        )
        assert selected_activity["sequence"] == event.sequence
        assert (
            selected_activity["reason"] == "설비 점검 보고서 절차가 요청에 적합합니다."
        )


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1",
        },
    )
    assert response.status_code == 200, response.text


def _references(ids: dict[str, str]) -> list[MessageReferenceInput]:
    return [
        MessageReferenceInput(
            kind="file",
            reference_id=ids["attachment_id"],
            display_snapshot={"name": "클라이언트가 위조한 파일명"},
        ),
        MessageReferenceInput(
            kind="artifact",
            reference_id=ids["artifact_id"],
            version_or_digest="v1",
            display_snapshot={"name": "클라이언트가 위조한 산출물명"},
        ),
        MessageReferenceInput(
            kind="skill",
            reference_id=ids["skill_id"],
            version_or_digest="r1",
            display_snapshot={"name": "클라이언트가 위조한 Skill명"},
        ),
    ]


def _reference_map(references: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["kind"]): item for item in references}


def test_composer_candidates_are_project_scoped_and_version_pinned(
    tmp_path: Path,
) -> None:
    app, ids = _setup(tmp_path)
    with TestClient(app) as client:
        _login(client)
        context = client.get(
            "/api/composer/suggestions",
            params={"project_id": ids["project_id"], "trigger": "@"},
        )
        assert context.status_code == 200, context.text
        context_items = {item["id"]: item for item in context.json()["items"]}
        for reference_id in (ids["attachment_id"], ids["artifact_id"]):
            item = context_items[reference_id]
            assert item["referenceId"] == reference_id
            assert item["insertText"].startswith("@")
            assert item["status"] == "available"
            assert item["projectId"] == ids["project_id"]
            assert item["scope"] == {"type": "project", "id": ids["project_id"]}
        assert (
            context_items[ids["artifact_id"]]["versionOrDigest"]
            == ids["artifact_digest"]
        )
        assert context_items[ids["artifact_id"]]["displaySnapshot"]["version"] == 1

        skills = client.get(
            "/api/composer/suggestions",
            params={"project_id": ids["project_id"], "trigger": "$"},
        )
        assert skills.status_code == 200, skills.text
        skill = skills.json()["items"][0]
        assert skill["id"] == ids["skill_id"]
        assert skill["referenceId"] == ids["skill_id"]
        assert skill["versionOrDigest"] == ids["draft_digest"]
        assert skill["subtitle"] == "Draft r1 · 저장 안 됨"
        assert skill["description"] == "설비 점검 보고서를 작성합니다."
        assert skill["insertText"] == "$skill:inspection-report"
        assert skill["scope"] == {
            "type": "project",
            "id": ids["project_id"],
        }

        other_context = client.get(
            "/api/composer/suggestions",
            params={"project_id": ids["other_project_id"], "trigger": "@"},
        )
        other_ids = {item["id"] for item in other_context.json()["items"]}
        assert ids["attachment_id"] not in other_ids
        assert ids["artifact_id"] not in other_ids
        other_skills = client.get(
            "/api/composer/suggestions",
            params={"project_id": ids["other_project_id"], "trigger": "$"},
        )
        assert other_skills.json()["items"] == []


def test_run_snapshot_and_message_references_are_canonical_and_reproducible(
    tmp_path: Path,
) -> None:
    _app, ids = _setup(tmp_path)
    with SessionLocal() as db:
        admin = db.get(User, ids["admin_id"])
        assert admin is not None
        run, message, created = create_run(
            db,
            user=admin,
            conversation_id=ids["conversation_id"],
            payload=RunCreate(
                message=RunMessageInput(
                    text="@자료와 $Skill로 보고서를 작성해 주세요.",
                    attachment_ids=[ids["attachment_id"], ids["attachment_id"]],
                    prompt_references=_references(ids),
                )
            ),
            idempotency_key="canonical-run-1",
        )
        assert created is True
        db.commit()

        references = _reference_map(run.snapshot_json["prompt_references"])
        assert "auto_selected_skill_ids" not in run.snapshot_json
        assert run.snapshot_json["attachments"] == [ids["attachment_id"]]
        assert references["file"]["version_or_digest"] == "file-sha256-v1"
        assert references["file"]["display_snapshot"]["name"] == "점검표.xlsx"
        assert references["artifact"]["version_or_digest"] == ids["artifact_digest"]
        assert references["artifact"]["display_snapshot"]["name"] == "설비 점검 보고서"
        assert references["skill"]["version_or_digest"] == ids["draft_digest"]
        assert references["skill"]["display_snapshot"]["name"] == "점검 보고서 작성"
        extension_snapshot = run.snapshot_json["extensions"][0]
        assert extension_snapshot["draft_revision"] == 1
        assert extension_snapshot["digest"] == ids["draft_digest"]
        assert (
            extension_snapshot["instructions"]
            == "# 점검 보고서\n\n초기 절차를 따릅니다."
        )
        assert len(run.snapshot_json["prompt_prefix_hash"]) == 64
        assert run.snapshot_json["prompt_cache_key"].startswith("lumina:user:v1:")
        assert len(run.snapshot_json["prompt_cache_key"]) == 63
        assert "@" not in run.snapshot_json["prompt_cache_key"]
        assert (
            db.scalar(
                select(func.count(MessageReference.id)).where(
                    MessageReference.message_id == message.id
                )
            )
            == 3
        )

        draft_snapshot = resolve_skill_snapshot(
            db, user=admin, project_id=ids["project_id"]
        )[0]
        draft, changed = update_draft(
            db,
            user=admin,
            draft_id=ids["draft_id"],
            expected_revision=1,
            expected_digest=str(draft_snapshot["digest"]),
            package_files={"SKILL.md": "# 점검 보고서\n\n변경된 절차를 따릅니다."},
            change_summary="절차 변경",
        )
        assert changed is True and draft.current_revision == 2
        db.commit()
        db.refresh(run)
        assert run.snapshot_json["extensions"][0]["draft_revision"] == 1
        assert (
            run.snapshot_json["extensions"][0]["instructions"]
            == "# 점검 보고서\n\n초기 절차를 따릅니다."
        )
        current_snapshot = resolve_skill_snapshot(
            db, user=admin, project_id=ids["project_id"]
        )[0]
        assert current_snapshot["draft_revision"] == 2
        assert current_snapshot["instructions"].endswith("변경된 절차를 따릅니다.")


def test_cross_project_references_are_rejected_but_project_member_can_use_file(
    tmp_path: Path,
) -> None:
    _app, ids = _setup(tmp_path)
    with SessionLocal() as db:
        admin = db.get(User, ids["admin_id"])
        member = db.get(User, ids["member_id"])
        assert admin is not None and member is not None

        member_run, _message, created = create_run(
            db,
            user=member,
            conversation_id=ids["conversation_id"],
            payload=RunCreate(
                message=RunMessageInput(
                    text="공유 프로젝트 파일을 사용합니다.",
                    attachment_ids=[ids["attachment_id"]],
                    prompt_references=[
                        MessageReferenceInput(
                            kind="file", reference_id=ids["attachment_id"]
                        )
                    ],
                )
            ),
            idempotency_key="member-file-run",
        )
        assert created is True
        assert member_run.snapshot_json["attachments"] == [ids["attachment_id"]]

        with pytest.raises(ApiProblem) as file_error:
            create_run(
                db,
                user=admin,
                conversation_id=ids["other_conversation_id"],
                payload=RunCreate(
                    message=RunMessageInput(
                        text="다른 프로젝트 파일 참조",
                        prompt_references=[
                            MessageReferenceInput(
                                kind="file", reference_id=ids["attachment_id"]
                            )
                        ],
                    )
                ),
                idempotency_key="cross-file-run",
            )
        assert file_error.value.status_code == 404

        with pytest.raises(ApiProblem) as skill_error:
            create_run(
                db,
                user=admin,
                conversation_id=ids["other_conversation_id"],
                payload=RunCreate(
                    message=RunMessageInput(
                        text="다른 프로젝트 Skill 참조",
                        prompt_references=[
                            MessageReferenceInput(
                                kind="skill", reference_id=ids["skill_id"]
                            )
                        ],
                    )
                ),
                idempotency_key="cross-skill-run",
            )
        assert skill_error.value.code == "extension_not_installed"

        with pytest.raises(ApiProblem) as range_error:
            create_run(
                db,
                user=admin,
                conversation_id=ids["conversation_id"],
                payload=RunCreate(
                    message=RunMessageInput(
                        text="짧은 본문",
                        prompt_references=[
                            MessageReferenceInput(
                                kind="file",
                                reference_id=ids["attachment_id"],
                                token_start=0,
                                token_end=100,
                            )
                        ],
                    )
                ),
                idempotency_key="invalid-range-run",
            )
        assert range_error.value.code == "invalid_reference_range"


def test_steer_and_queue_next_validate_and_persist_stable_references(
    tmp_path: Path,
) -> None:
    _app, ids = _setup(tmp_path)
    with SessionLocal() as db:
        admin = db.get(User, ids["admin_id"])
        assert admin is not None
        run, _message, _created = create_run(
            db,
            user=admin,
            conversation_id=ids["conversation_id"],
            payload=RunCreate(message=RunMessageInput(text="기본 작업")),
            idempotency_key="action-base-run",
        )

        run, steer_command, steer_message, changed = apply_run_action(
            db,
            user=admin,
            run_id=run.id,
            payload=RunActionRequest(
                type="steer",
                message=RunMessageInput(
                    text="현재 보고서에 Artifact와 Skill을 반영해 주세요.",
                    attachment_ids=[ids["attachment_id"]],
                    prompt_references=_references(ids)[1:],
                ),
            ),
            idempotency_key="steer-1",
        )
        assert changed is True and steer_message is not None
        assert steer_command.status == "waiting_safe_boundary"
        steer_references = _reference_map(
            steer_message.metadata_json["prompt_references"]
        )
        assert steer_message.metadata_json["attachment_ids"] == [ids["attachment_id"]]
        assert (
            steer_references["artifact"]["version_or_digest"] == ids["artifact_digest"]
        )
        assert steer_references["skill"]["version_or_digest"] == ids["draft_digest"]
        assert run.snapshot_json["pending_steers"][0]["message_id"] == steer_message.id
        assert (
            run.snapshot_json["pending_steers"][0]["prompt_references"]
            == steer_message.metadata_json["prompt_references"]
        )

        _run, queue_command, queue_message, queued_changed = apply_run_action(
            db,
            user=admin,
            run_id=run.id,
            payload=RunActionRequest(
                type="queue_next",
                message=RunMessageInput(
                    text="다음 보고서에서는 파일을 다시 사용해 주세요.",
                    attachment_ids=[ids["attachment_id"], ids["attachment_id"]],
                    prompt_references=_references(ids)[:1],
                ),
            ),
            idempotency_key="queue-1",
        )
        assert queued_changed is True and queue_message is not None
        assert queue_command.status == "queued"
        queued = db.scalar(
            select(QueuedMessage).where(QueuedMessage.idempotency_key == "queue-1")
        )
        assert queued is not None
        assert queued.attachment_ids_json == [ids["attachment_id"]]
        assert queued.prompt_references_json[0]["version_or_digest"] == "file-sha256-v1"
        assert (
            db.scalar(
                select(func.count(MessageReference.id)).where(
                    MessageReference.message_id.in_(
                        [steer_message.id, queue_message.id]
                    )
                )
            )
            == 3
        )
        command_count = db.scalar(select(func.count(RunCommand.id)))

        with pytest.raises(ApiProblem) as attachment_error:
            apply_run_action(
                db,
                user=admin,
                run_id=run.id,
                payload=RunActionRequest(
                    type="steer",
                    message=RunMessageInput(
                        text="격리된 파일",
                        attachment_ids=[ids["other_attachment_id"]],
                    ),
                ),
                idempotency_key="invalid-steer-attachment",
            )
        assert attachment_error.value.code == "attachment_not_found"

        with pytest.raises(ApiProblem) as reference_error:
            apply_run_action(
                db,
                user=admin,
                run_id=run.id,
                payload=RunActionRequest(
                    type="queue_next",
                    message=RunMessageInput(
                        text="격리된 Artifact",
                        prompt_references=[
                            MessageReferenceInput(
                                kind="artifact",
                                reference_id=ids["other_artifact_id"],
                            )
                        ],
                    ),
                ),
                idempotency_key="invalid-queue-reference",
            )
        assert reference_error.value.code == "reference_not_found"
        assert db.scalar(select(func.count(RunCommand.id))) == command_count


def test_first_run_assigns_message_title_only_to_untitled_conversation(
    tmp_path: Path,
) -> None:
    _app, ids = _setup(tmp_path)
    with SessionLocal() as db:
        admin = db.get(User, ids["admin_id"])
        assert admin is not None
        untitled = Conversation(
            organization_id=admin.organization_id,
            project_id=ids["project_id"],
            owner_user_id=admin.id,
            title="제목 없음",
        )
        named = Conversation(
            organization_id=admin.organization_id,
            project_id=ids["project_id"],
            owner_user_id=admin.id,
            title="사용자가 정한 제목",
        )
        db.add_all([untitled, named])
        db.flush()

        long_prompt = (
            "  분기별   매출 보고서를 분석하고 " + "핵심 지표를 정리해 주세요 " * 5
        )
        untitled_run, _message, created = create_run(
            db,
            user=admin,
            conversation_id=untitled.id,
            payload=RunCreate(message=RunMessageInput(text=long_prompt)),
            idempotency_key="automatic-title-1",
        )
        assert created is True
        assert len(untitled.title) == 60
        assert untitled.title.startswith(
            "분기별 매출 보고서를 분석하고 핵심 지표를 정리해 주세요"
        )
        assert untitled.title.endswith("…")
        assert "  " not in untitled.title
        snapshot = run_snapshot(db, untitled_run)
        assert snapshot["conversationTitle"] == untitled.title
        assert snapshot["conversationRevision"] == untitled.revision
        assert untitled_run.snapshot_json["conversation_title"] == {
            "status": "generated",
            "value": untitled.title,
            "revision": untitled.revision,
        }

        create_run(
            db,
            user=admin,
            conversation_id=named.id,
            payload=RunCreate(
                message=RunMessageInput(text="이 문장으로 바꾸지 마세요")
            ),
            idempotency_key="automatic-title-2",
        )
        assert named.title == "사용자가 정한 제목"
