from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.knowledge.tagger import DocumentTagSuggestion, NewTagSuggestion
from lumina.main import create_app
from lumina.models import KnowledgeDocument, Message, Run, User


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={"loginName": "admin", "loginDomain": "posco.com", "password": "1"},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def test_answer_is_saved_without_tags_then_batch_tagged_with_selected_model(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-documents.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )

    tag_models: list[str] = []

    async def fake_tags(**kwargs) -> DocumentTagSuggestion:
        tag_models.append(kwargs["model"])
        return DocumentTagSuggestion(
            tag_ids=(),
            new_tags=(
                NewTagSuggestion.model_validate(
                    {
                        "canonicalName": "인공지능",
                        "scopeNote": "컴퓨터 과학의 AI 기술",
                        "aliases": ["AI", "Artificial Intelligence"],
                    }
                ),
            ),
        )

    monkeypatch.setattr("lumina.knowledge.service.suggest_document_tags", fake_tags)

    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        project_response = client.post(
            "/api/projects", headers=headers, json={"name": "문서 그래프 프로젝트"}
        )
        assert project_response.status_code == 201, project_response.text
        project_id = project_response.json()["id"]
        conversation_response = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "LLM Wiki 설계"},
        )
        assert conversation_response.status_code == 201, conversation_response.text
        conversation_id = conversation_response.json()["id"]

        researched_at = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
        body = "# 문서 단위 지식\n\nLLM의 최종 답변을 **그대로** 저장합니다. [1]"
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_name == "admin"))
            assert user is not None
            run = Run(
                organization_id=user.organization_id,
                project_id=project_id,
                conversation_id=conversation_id,
                user_id=user.id,
                status="completed",
                provider_id="mock",
                model_key="mock-agent",
                runtime_model_id="mock-agent",
                model_display_name="Mock Agent",
                started_at=researched_at,
                finished_at=researched_at,
            )
            db.add(run)
            db.flush()
            message = Message(
                conversation_id=conversation_id,
                run_id=run.id,
                role="assistant",
                status="completed",
                canonical_text=body,
                turn_index=1,
                metadata_json={
                    "sources": [
                        {
                            "sourceId": "source-1",
                            "title": "Obsidian Help",
                            "normalizedUrl": "https://help.obsidian.md/links",
                            "domain": "help.obsidian.md",
                            "verbatimExcerpt": "Links connect notes.",
                            "evidenceKind": "fetched_content",
                        }
                    ],
                    "citations": [
                        {"sourceId": "source-1", "markerNumber": 1, "status": "cited"}
                    ],
                },
            )
            db.add(message)
            db.commit()
            message_id = message.id

        first = client.post(
            f"/api/knowledge/documents/from-message/{message_id}", headers=headers
        )
        assert first.status_code == 201, first.text
        saved = first.json()
        assert saved["created"] is True
        assert saved["title"] == "LLM Wiki 설계"
        assert saved["body"] == body
        assert saved["researchedAt"] == researched_at.isoformat().replace("+00:00", "Z")
        assert saved["tags"] == []
        assert tag_models == []
        assert saved["citations"][0]["title"] == "Obsidian Help"
        assert "description" not in saved
        assert "author" not in saved
        assert "created" in saved

        duplicate = client.post(
            f"/api/knowledge/documents/from-message/{message_id}", headers=headers
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["id"] == saved["id"]
        assert duplicate.json()["created"] is False

        tagged = client.post(
            "/api/knowledge/documents/tag-batch",
            headers=headers,
            json={
                "spaceId": saved["spaceId"],
                "providerId": "mock",
                "modelKey": "mock-agent",
            },
        )
        assert tagged.status_code == 200, tagged.text
        assert tagged.json() == {
            "requestedCount": 1,
            "taggedCount": 1,
            "failedCount": 0,
            "remainingCount": 0,
        }
        assert tag_models == ["mock-agent"]
        assert (
            client.get(f"/api/knowledge/documents/{saved['id']}").json()["tags"][0][
                "name"
            ]
            == "인공지능"
        )

        listing = client.get("/api/knowledge/documents")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [saved["id"]]

        graph = client.get("/api/knowledge/graph")
        assert graph.status_code == 200
        assert graph.json()["nodes"][0]["id"] == saved["id"]
        assert graph.json()["edges"] == []

        with SessionLocal() as db:
            assert db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == saved["id"])) is not None


def test_legacy_entity_and_statement_routes_are_gone(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-legacy-routes.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        _login(client)
        paths = client.get("/api/openapi.json").json()["paths"]
        assert not any("entities" in path for path in paths)
        assert not any("statements" in path for path in paths)
        assert not any("reviews" in path for path in paths)


def test_knowledge_space_project_links_are_revision_checked_and_persisted(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-project-links.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        project = client.post(
            "/api/projects", headers=headers, json={"name": "연결 프로젝트"}
        )
        assert project.status_code == 201, project.text
        space = client.post(
            "/api/knowledge/spaces",
            headers=headers,
            json={"name": "연결 지식 그래프"},
        )
        assert space.status_code == 201, space.text
        assert space.json()["projectIds"] == []

        updated = client.patch(
            f"/api/knowledge/spaces/{space.json()['id']}",
            headers=headers,
            json={
                "expectedRevision": space.json()["settingsRevision"],
                "projectIds": [project.json()["id"]],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["projectIds"] == [project.json()["id"]]
        assert updated.json()["settingsRevision"] == 2

        stale = client.patch(
            f"/api/knowledge/spaces/{space.json()['id']}",
            headers=headers,
            json={"expectedRevision": 1, "projectIds": []},
        )
        assert stale.status_code == 409, stale.text
        assert client.get("/api/knowledge/spaces").json()[0]["projectIds"] == [
            project.json()["id"]
        ]
