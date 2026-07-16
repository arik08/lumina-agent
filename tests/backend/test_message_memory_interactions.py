from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lumina.api.errors import install_error_handlers
from lumina.api.routes import auth, memories, messages
from lumina.auth import bootstrap_database, create_user
from lumina.config import Settings, get_settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.models import (
    AuditEvent,
    Conversation,
    Message,
    MessageFeedback,
    MessageReference,
    MessageSelectionComment,
    Organization,
    Project,
    ProjectMembership,
    Run,
    RunEvent,
    User,
    UserMemory,
    utc_now,
)


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
        worker = create_user(
            db,
            login_name="worker",
            password="pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        db.add(
            ProjectMembership(
                project_id=project.id,
                user_id=worker.id,
                role="member",
                status="active",
                created_by_user_id=admin.id,
            )
        )
        conversation = Conversation(
            organization_id=organization.id,
            project_id=project.id,
            owner_user_id=admin.id,
            title="상호작용 테스트",
        )
        db.add(conversation)
        db.flush()
        now = utc_now()
        run = Run(
            organization_id=organization.id,
            project_id=project.id,
            conversation_id=conversation.id,
            user_id=admin.id,
            status="completed",
            provider_id="mock",
            model_key="mock-agent",
            runtime_model_id="mock-agent",
            model_display_name="Mock",
            effort="medium",
            approval_mode="yolo",
            environment_type="local_worker",
            snapshot_json={},
            usage_json={},
            assistant_draft="",
            current_turn=1,
            last_sequence=0,
            max_turns=20,
            started_at=now,
            finished_at=now,
        )
        db.add(run)
        db.flush()
        user_message = Message(
            conversation_id=conversation.id,
            run_id=run.id,
            author_user_id=admin.id,
            role="user",
            status="completed",
            canonical_text="보고서는 표 중심으로 작성해 주세요.",
            turn_index=1,
            metadata_json={
                "prompt_references": [
                    {
                        "kind": "file",
                        "reference_id": "11111111-1111-1111-1111-111111111111",
                        "version_or_digest": "sha256:abc",
                        "token_start": 0,
                        "token_end": 5,
                        "display_snapshot": {"name": "점검표.xlsx"},
                    }
                ]
            },
        )
        assistant_message = Message(
            conversation_id=conversation.id,
            run_id=run.id,
            role="assistant",
            status="completed",
            canonical_text="첫째 문장입니다. 둘째 문장은 수정 대상입니다. 마지막입니다.",
            turn_index=1,
            metadata_json={},
        )
        db.add_all([user_message, assistant_message])
        db.commit()
        ids = {
            "admin_id": admin.id,
            "worker_id": worker.id,
            "run_id": run.id,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
        }

    application = FastAPI()
    application.state.settings = settings
    application.dependency_overrides[get_settings] = lambda: settings
    install_error_handlers(application)
    for module in (auth, messages, memories):
        application.include_router(module.router, prefix="/api")
    return application, ids


def _login(client: TestClient, name: str = "admin", password: str = "1") -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": name,
            "loginDomain": "posco.com",
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrfToken"])


def test_references_rating_report_and_comment_contracts(tmp_path: Path) -> None:
    app, ids = _setup(tmp_path)
    assistant_id = ids["assistant_message_id"]
    user_message_id = ids["user_message_id"]
    with TestClient(app) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}

        references = client.get(f"/api/messages/{user_message_id}/references")
        assert references.status_code == 200
        assert references.json()[0]["displaySnapshot"]["name"] == "점검표.xlsx"

        liked = client.put(
            f"/api/messages/{assistant_id}/rating",
            headers=headers,
            json={"value": "like"},
        )
        assert liked.status_code == 200, liked.text
        disliked = client.put(
            f"/api/messages/{assistant_id}/rating",
            headers=headers,
            json={"value": "dislike"},
        )
        assert disliked.status_code == 200
        assert disliked.json()["id"] == liked.json()["id"]
        assert disliked.json()["value"] == "dislike"

        report = client.post(
            f"/api/messages/{assistant_id}/reports",
            headers=headers,
            json={
                "category": "source_issue",
                "description": "원문과 수치가 다릅니다.",
                "diagnosticScope": {
                    "includeRunState": True,
                    "includeToolSummaries": False,
                    "includeConversation": True,
                    "includeAttachments": False,
                },
            },
        )
        assert report.status_code == 201, report.text
        assert report.json()["status"] == "submitted"
        assert report.json()["diagnosticScope"]["includeConversation"] is True

        assistant_text = "첫째 문장입니다. 둘째 문장은 수정 대상입니다. 마지막입니다."
        selected = "둘째 문장은 수정 대상입니다."
        start = assistant_text.index(selected)
        exact = client.post(
            f"/api/messages/{assistant_id}/comments",
            headers=headers,
            json={
                "blockId": "paragraph-1",
                "startOffset": start,
                "endOffset": start + len(selected),
                "selectedText": selected,
                "prefixContext": "첫째 문장입니다. ",
                "suffixContext": " 마지막입니다.",
                "instruction": "이 문장을 더 구체화해 주세요.",
            },
        )
        assert exact.status_code == 201, exact.text
        assert exact.json()["anchorStatus"] == "exact"
        comment_id = exact.json()["id"]

        reanchored = client.post(
            f"/api/messages/{assistant_id}/comments",
            headers=headers,
            json={
                "blockId": "paragraph-1",
                "startOffset": 0,
                "endOffset": len(selected),
                "selectedText": selected,
                "prefixContext": "첫째 문장입니다. ",
                "suffixContext": " 마지막입니다.",
                "instruction": "다시 확인해 주세요.",
            },
        )
        assert reanchored.status_code == 201
        assert reanchored.json()["anchorStatus"] == "reanchored"
        assert reanchored.json()["startOffset"] == start

        stale = client.post(
            f"/api/messages/{assistant_id}/comments",
            headers=headers,
            json={
                "blockId": "paragraph-1",
                "startOffset": 0,
                "endOffset": 4,
                "selectedText": "없는 문장",
                "instruction": "확인해 주세요.",
            },
        )
        assert stale.status_code == 201
        assert stale.json()["anchorStatus"] == "stale"

        resolved = client.patch(
            f"/api/message-comments/{comment_id}",
            headers=headers,
            json={"status": "resolved"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "resolved"

        assistant_only = client.put(
            f"/api/messages/{user_message_id}/rating",
            headers=headers,
            json={"value": "like"},
        )
        assert assistant_only.status_code == 409

        deleted = client.delete(f"/api/messages/{assistant_id}/rating", headers=headers)
        assert deleted.status_code == 204
        feedback = client.get(f"/api/messages/{assistant_id}/feedback")
        assert [item["kind"] for item in feedback.json()] == ["report"]

        client.cookies.clear()
        worker_csrf = _login(client, "worker", "pw")
        forbidden_edit = client.patch(
            f"/api/message-comments/{comment_id}",
            headers={"X-CSRF-Token": worker_csrf},
            json={"status": "resolved"},
        )
        assert forbidden_edit.status_code == 404

    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count(MessageReference.id)).where(
                    MessageReference.message_id == user_message_id
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(MessageFeedback.id)).where(
                    MessageFeedback.message_id == assistant_id,
                    MessageFeedback.kind == "rating",
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(MessageSelectionComment.id)).where(
                    MessageSelectionComment.message_id == assistant_id
                )
            )
            == 3
        )
        event_types = list(
            db.scalars(
                select(RunEvent.event_type)
                .where(RunEvent.run_id == ids["run_id"])
                .order_by(RunEvent.sequence)
            )
        )
        assert "message_feedback_changed" in event_types
        assert "message_comment_changed" in event_types


def test_user_memory_ownership_events_and_settings(tmp_path: Path) -> None:
    app, ids = _setup(tmp_path)
    source_message_id = ids["user_message_id"]
    with TestClient(app) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        default_setting = client.get("/api/memory-settings")
        assert default_setting.json() == {"mode": "auto", "enabled": True}

        created = client.post(
            "/api/memories",
            headers=headers,
            json={
                "category": "output_preference",
                "fact": " 보고서는   표 중심으로 작성 ",
                "displayText": "보고서는 표 중심으로 작성합니다.",
                "sourceMessageIds": [source_message_id],
                "confidence": 0.8,
            },
        )
        assert created.status_code == 201, created.text
        memory = created.json()
        memory_id = memory["id"]
        assert memory["normalizedFact"] == "보고서는 표 중심으로 작성"
        assert memory["sourceRunIds"] == [ids["run_id"]]

        confirmed = client.post(
            "/api/memories",
            headers=headers,
            json={
                "category": "output_preference",
                "fact": "보고서는 표 중심으로 작성",
                "displayText": "보고서는 표 중심으로 작성합니다.",
                "sourceMessageIds": [source_message_id],
                "confidence": 0.9,
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["id"] == memory_id
        assert confirmed.json()["evidenceCount"] == 2
        assert confirmed.json()["confidence"] == 0.9

        searched = client.get("/api/memories?query=표 중심")
        assert [item["id"] for item in searched.json()] == [memory_id]
        edited = client.patch(
            f"/api/memories/{memory_id}",
            headers=headers,
            json={"displayText": "표를 먼저 배치한 보고서를 선호합니다."},
        )
        assert edited.status_code == 200
        assert "표를 먼저" in edited.json()["displayText"]

        for invalid_patch in (
            {"category": None},
            {"fact": None},
            {"displayText": None},
            {"confidence": None},
            {"status": None},
        ):
            rejected_null = client.patch(
                f"/api/memories/{memory_id}",
                headers=headers,
                json=invalid_patch,
            )
            assert rejected_null.status_code == 422, (
                invalid_patch,
                rejected_null.text,
            )
        unchanged = client.get("/api/memories?query=표를 먼저").json()[0]
        assert unchanged["id"] == memory_id
        assert unchanged["category"] == "output_preference"
        assert unchanged["confidence"] == 0.9

        sensitive = client.post(
            "/api/memories",
            headers=headers,
            json={
                "category": "secret",
                "fact": "api_key=abcdef123456",
                "displayText": "api_key=abcdef123456",
                "sourceMessageIds": [source_message_id],
            },
        )
        assert sensitive.status_code == 422
        assert sensitive.json()["code"] == "sensitive_memory_forbidden"

        setting = client.patch(
            "/api/memory-settings", headers=headers, json={"enabled": False}
        )
        assert setting.status_code == 200
        assert setting.json() == {"mode": "off", "enabled": False}

        client.cookies.clear()
        worker_csrf = _login(client, "worker", "pw")
        assert client.get("/api/memories").json() == []
        hidden = client.patch(
            f"/api/memories/{memory_id}",
            headers={"X-CSRF-Token": worker_csrf},
            json={"status": "dismissed"},
        )
        assert hidden.status_code == 404

        client.cookies.clear()
        admin_csrf = _login(client)
        deleted = client.delete(
            f"/api/memories/{memory_id}",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert deleted.status_code == 204
        assert client.get("/api/memories").json() == []

    with SessionLocal() as db:
        memory_row = db.get(UserMemory, memory_id)
        assert memory_row is not None
        assert memory_row.status == "deleted"
        assert memory_row.deleted_at is not None
        memory_events = list(
            db.scalars(
                select(RunEvent).where(
                    RunEvent.run_id == ids["run_id"],
                    RunEvent.event_type == "memory_changed",
                )
            )
        )
        assert len(memory_events) == 4
        audit_actions = set(db.scalars(select(AuditEvent.action)))
        assert {
            "memory_created",
            "memory_confirmed",
            "memory_edited",
            "memory_deleted",
            "memory_settings_changed",
        } <= audit_actions


def test_pending_memory_candidates_can_be_listed_accepted_and_dismissed(
    tmp_path: Path,
) -> None:
    app, ids = _setup(tmp_path)
    with SessionLocal() as db:
        user = db.get(User, ids["admin_id"])
        assert user is not None
        active = UserMemory(
            user_id=user.id,
            category="communication_preference",
            normalized_fact="response language: korean",
            display_text="답변은 한국어로 제공합니다.",
            conflict_key="response_language",
            source_message_ids_json=[ids["user_message_id"]],
            source_run_ids_json=[ids["run_id"]],
            confidence=0.95,
            evidence_count=1,
            status="active",
            extractor_version="offline-conservative-v1",
        )
        db.add(active)
        db.flush()
        accepted_candidate = UserMemory(
            user_id=user.id,
            category="communication_preference",
            normalized_fact="response language: english",
            display_text="답변은 영어로 제공합니다.",
            conflict_key="response_language",
            source_message_ids_json=[ids["user_message_id"]],
            source_run_ids_json=[ids["run_id"]],
            confidence=0.9,
            evidence_count=1,
            status="pending",
            supersedes_memory_id=active.id,
            extractor_version="offline-conservative-v1",
        )
        dismissed_candidate = UserMemory(
            user_id=user.id,
            category="output_preference",
            normalized_fact="report format: html",
            display_text="보고서는 HTML 형식을 선호합니다.",
            conflict_key="report_output",
            source_message_ids_json=[ids["user_message_id"]],
            source_run_ids_json=[ids["run_id"]],
            confidence=0.85,
            evidence_count=1,
            status="pending",
            extractor_version="offline-conservative-v1",
        )
        db.add_all((accepted_candidate, dismissed_candidate))
        db.commit()
        accepted_id = accepted_candidate.id
        dismissed_id = dismissed_candidate.id
        active_id = active.id

    with TestClient(app) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        pending = client.get("/api/memories?status=pending")
        assert pending.status_code == 200
        payloads = {item["id"]: item for item in pending.json()}
        assert set(payloads) == {accepted_id, dismissed_id}
        assert payloads[accepted_id]["conflictKey"] == "response_language"
        assert payloads[accepted_id]["supersedesMemoryId"] == active_id
        assert payloads[accepted_id]["extractorVersion"] == ("offline-conservative-v1")

        accepted = client.patch(
            f"/api/memories/{accepted_id}",
            headers=headers,
            json={"status": "active"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "active"
        dismissed = client.patch(
            f"/api/memories/{dismissed_id}",
            headers=headers,
            json={"status": "dismissed"},
        )
        assert dismissed.status_code == 200
        assert dismissed.json()["status"] == "dismissed"
        assert client.get("/api/memories?status=pending").json() == []

    with SessionLocal() as db:
        active_row = db.get(UserMemory, active_id)
        accepted_row = db.get(UserMemory, accepted_id)
        dismissed_row = db.get(UserMemory, dismissed_id)
        assert active_row is not None and active_row.status == "superseded"
        assert accepted_row is not None and accepted_row.status == "active"
        assert dismissed_row is not None and dismissed_row.status == "dismissed"
