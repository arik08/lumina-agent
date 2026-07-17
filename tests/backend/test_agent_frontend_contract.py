from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.agent_frontends import (
    agent_frontend_payload,
    normalize_agent_frontend_payload,
)
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Conversation, Run


def test_removed_builtin_frontend_falls_back_to_general_chat() -> None:
    assert agent_frontend_payload("removed-agent", "7") == {
        "id": "removed-agent",
        "version": "7",
        "frontendModule": "general-chat",
        "frontendContract": "lumina-frontend-v1",
        "fallback": True,
    }

    assert normalize_agent_frontend_payload(
        {"id": "general", "version": "1"},
        agent_id="general",
        agent_version="1",
    ) == {
        "id": "general",
        "version": "1",
        "frontendModule": "general-chat",
        "frontendContract": "lumina-frontend-v1",
        "fallback": False,
    }


def test_conversation_and_run_freeze_builtin_frontend_contract(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "loginName": "admin",
                "loginDomain": "posco.com",
                "password": "1",
            },
        )
        assert login.status_code == 200, login.text
        headers = {"X-CSRF-Token": login.json()["csrfToken"]}
        project_id = client.get("/api/projects").json()[0]["id"]

        created = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "Frontend contract"},
        )
        assert created.status_code == 201, created.text
        conversation = created.json()
        assert conversation["agent"] == {
            "id": "general",
            "version": "1",
            "frontendModule": "general-chat",
            "frontendContract": "lumina-frontend-v1",
            "fallback": False,
        }

        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={**headers, "Idempotency-Key": "frontend-contract-run"},
            json={
                "message": {
                    "text": "Frontend contract snapshot",
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
        assert started.status_code == 202, started.text
        assert started.json()["run"]["agent"] == conversation["agent"]

        with SessionLocal() as db:
            persisted_conversation = db.scalar(
                select(Conversation).where(Conversation.id == conversation["id"])
            )
            run = db.scalar(
                select(Run).where(Run.id == started.json()["run"]["runId"])
            )
            assert persisted_conversation is not None
            assert persisted_conversation.agent_id == "general"
            assert persisted_conversation.agent_version == "1"
            assert run is not None
            assert run.snapshot_json["agent"] == conversation["agent"]
