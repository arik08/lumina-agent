from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.artifacts.service import create_artifact
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import KnowledgeDocument, Project, User
from lumina.storage import ManagedLocalStorage


def test_html_artifact_is_saved_as_readable_knowledge_document_once(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-artifact.db').as_posix()}",
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

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            project = (
                db.scalar(select(Project).where(Project.owner_user_id == user.id))
                if user
                else None
            )
            assert user is not None and project is not None
            artifact, version = create_artifact(
                db,
                ManagedLocalStorage(settings.artifacts_dir),
                user=user,
                project_id=project.id,
                conversation_id=None,
                source_run_id=None,
                display_name="시장 분석.html",
                kind="html",
                mime_type="text/html",
                content=(
                    b"<!doctype html><html><head><title>Market Brief</title>"
                    b"<style>.hidden{display:none}</style></head><body>"
                    b"<main><h1>Quarterly outlook</h1><p>Demand remains stable.</p></main>"
                    b"<script>window.secret = 'not knowledge';</script></body></html>"
                ),
            )
            artifact_id = artifact.id
            version_number = version.version_number
            db.commit()

        created = client.post(
            f"/api/knowledge/documents/from-artifact/{artifact_id}",
            params={"version": version_number},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        assert created.json()["title"] == "Market Brief"
        assert "Quarterly outlook" in created.json()["body"]
        assert "Demand remains stable." in created.json()["body"]
        assert "window.secret" not in created.json()["body"]

        reused = client.post(
            f"/api/knowledge/documents/from-artifact/{artifact_id}",
            params={"version": version_number},
            headers=headers,
        )
        assert reused.status_code == 200, reused.text
        assert reused.json()["id"] == created.json()["id"]
        assert reused.json()["created"] is False

        with SessionLocal() as db:
            documents = list(
                db.scalars(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.source_artifact_id == artifact_id
                    )
                )
            )
            assert len(documents) == 1
