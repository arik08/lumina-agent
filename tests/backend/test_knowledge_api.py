from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.knowledge.tagger import DocumentTagSuggestion, NewTagSuggestion
from lumina.main import create_app
from lumina.models import (
    Conversation,
    KnowledgeDocument,
    KnowledgeDocumentTag,
    KnowledgeTag,
    Message,
    Project,
    Run,
    User,
)
from lumina.tools.knowledge import (
    build_project_knowledge_retrieval_snapshot,
    execute_knowledge_tool,
)


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={"loginName": "admin", "loginDomain": "posco.com", "password": "1111"},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def test_knowledge_documents_remain_available_beyond_the_latest_200(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-recall.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        space = client.post(
            "/api/knowledge/spaces",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Recall"},
        )
        assert space.status_code == 201, space.text
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_name == "admin"))
            project = db.get(Project, project_id)
            assert user is not None
            assert project is not None
            now = datetime(2026, 7, 20, tzinfo=UTC)
            documents = []
            for index in range(205):
                body = (
                    "legacyneedle appears only in the oldest document"
                    if index == 204
                    else f"ordinary knowledge document {index}"
                )
                documents.append(
                    KnowledgeDocument(
                        space_id=space.json()["id"],
                        project_id=project_id,
                        owner_user_id=user.id,
                        title=f"Document {index}",
                        body=body,
                        researched_at=now - timedelta(days=index),
                        citations_json=[],
                        content_digest=sha256(body.encode("utf-8")).hexdigest(),
                        status="active",
                    )
                )
            db.add_all(documents)
            db.commit()

            conversation = Conversation(
                organization_id=user.organization_id,
                project_id=project.id,
                owner_user_id=user.id,
                title="Knowledge recall",
            )
            db.add(conversation)
            db.flush()
            snapshot = build_project_knowledge_retrieval_snapshot(
                db,
                project_id=project.id,
                owner_user_id=user.id,
            )
            assert snapshot is not None
            assert "legacyneedle" not in str(snapshot)
            run = Run(
                organization_id=user.organization_id,
                project_id=project.id,
                conversation_id=conversation.id,
                user_id=user.id,
                status="completed",
                provider_id="mock",
                model_key="mock-agent",
                runtime_model_id="mock-agent",
                model_display_name="Mock Agent",
                snapshot_json={
                    "knowledge_retrieval": snapshot,
                    "user_message_text": "legacyneedle",
                },
            )
            db.add(run)
            db.flush()
            result = execute_knowledge_tool(
                db,
                run=run,
                user=user,
                name="search_knowledge",
                arguments={"query": "legacyneedle"},
            )
            assert [item["title"] for item in result["results"]] == [
                "Document 204"
            ]

        listing = client.get(
            "/api/knowledge/documents", params={"spaceId": space.json()["id"]}
        )
        assert listing.status_code == 200, listing.text
        assert len(listing.json()) == 205
        assert listing.json()[-1]["title"] == "Document 204"

        graph = client.get(
            "/api/knowledge/graph", params={"spaceId": space.json()["id"]}
        )
        assert graph.status_code == 200, graph.text
        assert len(graph.json()["nodes"]) == 205
        assert graph.json()["truncated"] is False


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

    tag_batches: list[tuple[str, int]] = []

    async def fake_tag_batch(**kwargs) -> tuple[DocumentTagSuggestion, ...]:
        tag_batches.append((kwargs["model"], len(kwargs["documents"])))
        suggestions = []
        for document in kwargs["documents"]:
            canonical_name = {
                "병합 후보 문서": "AI 기술",
                "일괄 승인 문서": "자동화 승인",
                "일괄 거절 문서": "자동화 거절",
            }.get(document.title, "인공지능")
            suggestions.append(
                DocumentTagSuggestion(
                    tag_ids=(),
                    new_tags=(
                        NewTagSuggestion.model_validate(
                            {
                                "canonicalName": canonical_name,
                                "scopeNote": f"{canonical_name} 범위",
                                "aliases": [],
                            }
                        ),
                    ),
                )
            )
        return tuple(suggestions)

    monkeypatch.setattr(
        "lumina.knowledge.service.suggest_document_tag_batch", fake_tag_batch
    )

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
        assert tag_batches == []
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

        second_body = "두 번째 미태깅 문서도 같은 요청에서 처리합니다."
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_name == "admin"))
            assert user is not None
            second_document = KnowledgeDocument(
                space_id=saved["spaceId"],
                project_id=project_id,
                owner_user_id=user.id,
                source_message_id=None,
                source_run_id=None,
                source_conversation_id=conversation_id,
                title="두 번째 문서",
                body=second_body,
                researched_at=researched_at + timedelta(seconds=1),
                citations_json=[],
                content_digest=sha256(second_body.encode("utf-8")).hexdigest(),
                status="active",
            )
            db.add(second_document)
            db.commit()
            second_document_id = second_document.id

        tagged = client.post(
            "/api/knowledge/documents/tag-batch",
            headers=headers,
            json={
                "spaceId": saved["spaceId"],
                "providerId": "mock",
                "modelKey": "mock-agent",
                "newTagPolicy": "auto_approve",
            },
        )
        assert tagged.status_code == 200, tagged.text
        assert tagged.json() == {
            "requestedCount": 2,
            "taggedCount": 2,
            "proposedCount": 0,
            "proposalDocumentCount": 0,
            "failedCount": 0,
            "remainingCount": 0,
            "target": "untagged",
            "newTagPolicy": "auto_approve",
        }
        assert tag_batches == [("mock-agent", 2)]
        assert (
            client.get(f"/api/knowledge/documents/{saved['id']}").json()["tags"][0][
                "name"
            ]
            == "인공지능"
        )

        proposal_body = "승인 전에는 그래프에 연결하지 않는 새 태그 제안 문서"
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_name == "admin"))
            assert user is not None
            proposal_document = KnowledgeDocument(
                space_id=saved["spaceId"],
                project_id=project_id,
                owner_user_id=user.id,
                source_message_id=None,
                source_run_id=None,
                source_conversation_id=conversation_id,
                title="태그 제안 문서",
                body=proposal_body,
                researched_at=researched_at + timedelta(seconds=2),
                citations_json=[],
                content_digest=sha256(proposal_body.encode("utf-8")).hexdigest(),
                status="active",
            )
            db.add(proposal_document)
            db.commit()
            proposal_document_id = proposal_document.id

        proposed = client.post(
            "/api/knowledge/documents/tag-batch",
            headers=headers,
            json={
                "spaceId": saved["spaceId"],
                "providerId": "mock",
                "modelKey": "mock-agent",
                "newTagPolicy": "propose",
            },
        )
        assert proposed.status_code == 200, proposed.text
        assert proposed.json()["proposedCount"] == 1
        assert proposed.json()["taggedCount"] == 0
        assert client.get(f"/api/knowledge/documents/{proposal_document_id}").json()["tags"] == []

        proposal_items = client.get(
            "/api/knowledge/tag-proposals",
            params={"spaceId": saved["spaceId"]},
        )
        assert proposal_items.status_code == 200, proposal_items.text
        proposal = proposal_items.json()[0]
        assert proposal["canonicalName"] == "인공지능"
        assert proposal["documentCount"] == 1
        approved = client.post(
            f"/api/knowledge/tag-proposals/{proposal['id']}/resolve",
            headers=headers,
            json={"action": "approve", "expectedRevision": proposal["revision"]},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert client.get(f"/api/knowledge/documents/{proposal_document_id}").json()["tags"][0]["name"] == "인공지능"
        assert client.get(
            "/api/knowledge/tag-proposals", params={"spaceId": saved["spaceId"]}
        ).json() == []
        assert client.delete(
            f"/api/knowledge/documents/{proposal_document_id}", headers=headers
        ).status_code == 204

        workflow_document_ids: dict[str, str] = {}
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_name == "admin"))
            assert user is not None
            for offset, title in enumerate(
                ("병합 후보 문서", "일괄 승인 문서", "일괄 거절 문서"), start=3
            ):
                body_value = f"{title} 본문"
                document = KnowledgeDocument(
                    space_id=saved["spaceId"],
                    project_id=project_id,
                    owner_user_id=user.id,
                    source_message_id=None,
                    source_run_id=None,
                    source_conversation_id=conversation_id,
                    title=title,
                    body=body_value,
                    researched_at=researched_at + timedelta(seconds=offset),
                    citations_json=[],
                    content_digest=sha256(body_value.encode("utf-8")).hexdigest(),
                    status="active",
                )
                db.add(document)
                db.flush()
                workflow_document_ids[title] = document.id
            db.commit()

        workflow_tagging = client.post(
            "/api/knowledge/documents/tag-batch",
            headers=headers,
            json={
                "spaceId": saved["spaceId"],
                "providerId": "mock",
                "modelKey": "mock-agent",
                "newTagPolicy": "propose",
            },
        )
        assert workflow_tagging.status_code == 200, workflow_tagging.text
        assert workflow_tagging.json()["proposedCount"] == 3
        workflow_proposals = client.get(
            "/api/knowledge/tag-proposals", params={"spaceId": saved["spaceId"]}
        ).json()
        proposals_by_name = {item["canonicalName"]: item for item in workflow_proposals}
        existing_tag_id = client.get(
            f"/api/knowledge/documents/{saved['id']}"
        ).json()["tags"][0]["id"]
        merged = client.post(
            f"/api/knowledge/tag-proposals/{proposals_by_name['AI 기술']['id']}/resolve",
            headers=headers,
            json={
                "action": "merge",
                "expectedRevision": proposals_by_name["AI 기술"]["revision"],
                "targetTagId": existing_tag_id,
            },
        )
        assert merged.status_code == 200, merged.text
        assert merged.json()["status"] == "merged"
        bulk_approved = client.post(
            "/api/knowledge/tag-proposals/resolve-batch",
            headers=headers,
            json={
                "action": "approve",
                "proposalIds": [proposals_by_name["자동화 승인"]["id"]],
            },
        )
        assert bulk_approved.json() == {"resolvedCount": 1}
        bulk_rejected = client.post(
            "/api/knowledge/tag-proposals/resolve-batch",
            headers=headers,
            json={
                "action": "reject",
                "proposalIds": [proposals_by_name["자동화 거절"]["id"]],
            },
        )
        assert bulk_rejected.json() == {"resolvedCount": 1}
        assert client.get(
            f"/api/knowledge/documents/{workflow_document_ids['병합 후보 문서']}"
        ).json()["tags"][0]["id"] == existing_tag_id
        assert client.get(
            f"/api/knowledge/documents/{workflow_document_ids['일괄 승인 문서']}"
        ).json()["tags"][0]["name"] == "자동화 승인"
        assert client.get(
            f"/api/knowledge/documents/{workflow_document_ids['일괄 거절 문서']}"
        ).json()["tags"] == []
        for document_id in workflow_document_ids.values():
            assert client.delete(
                f"/api/knowledge/documents/{document_id}", headers=headers
            ).status_code == 204

        failed_retag = client.post(
            "/api/knowledge/documents/tag-batch",
            headers=headers,
            json={
                "spaceId": saved["spaceId"],
                "providerId": "mock",
                "modelKey": "mock-agent",
                "target": "all",
                "newTagPolicy": "pool_only",
            },
        )
        assert failed_retag.status_code == 200, failed_retag.text
        assert failed_retag.json()["failedCount"] == 2
        assert client.get(f"/api/knowledge/documents/{saved['id']}").json()["tags"][0]["name"] == "인공지능"
        second_deleted = client.delete(
            f"/api/knowledge/documents/{second_document_id}", headers=headers
        )
        assert second_deleted.status_code == 204, second_deleted.text

        linked_body = "같은 태그를 공유하는 두 번째 지식 문서"
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_name == "admin"))
            tag = db.scalar(select(KnowledgeTag).where(KnowledgeTag.space_id == saved["spaceId"]))
            assert user is not None
            assert tag is not None
            linked_document = KnowledgeDocument(
                space_id=saved["spaceId"],
                project_id=project_id,
                owner_user_id=user.id,
                source_message_id=None,
                source_run_id=None,
                source_conversation_id=conversation_id,
                title="연결된 두 번째 문서",
                body=linked_body,
                researched_at=researched_at,
                citations_json=[],
                content_digest=sha256(linked_body.encode("utf-8")).hexdigest(),
                status="active",
            )
            db.add(linked_document)
            db.flush()
            db.add(KnowledgeDocumentTag(document_id=linked_document.id, tag_id=tag.id))
            db.commit()
            linked_document_id = linked_document.id

        listing = client.get("/api/knowledge/documents")
        assert listing.status_code == 200
        assert {item["id"] for item in listing.json()} == {saved["id"], linked_document_id}
        assert {item["linkedDocumentCount"] for item in listing.json()} == {1}

        deleted = client.delete(
            f"/api/knowledge/documents/{linked_document_id}", headers=headers
        )
        assert deleted.status_code == 204, deleted.text
        assert client.get(f"/api/knowledge/documents/{linked_document_id}").status_code == 404
        listing_after_delete = client.get("/api/knowledge/documents").json()
        assert [item["id"] for item in listing_after_delete] == [saved["id"]]
        assert listing_after_delete[0]["linkedDocumentCount"] == 0

        graph = client.get("/api/knowledge/graph")
        assert graph.status_code == 200
        assert graph.json()["nodes"][0]["id"] == saved["id"]
        assert graph.json()["edges"] == []

        with SessionLocal() as db:
            assert db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == saved["id"])) is not None
            deleted_document = db.get(KnowledgeDocument, linked_document_id)
            assert deleted_document is not None
            assert deleted_document.status == "deleted"


def test_document_tags_can_be_replaced_with_existing_and_new_names(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-tag-edit.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        project_id = client.get("/api/projects").json()[0]["id"]
        space_response = client.post(
            "/api/knowledge/spaces",
            headers=headers,
            json={"name": "Tag editing"},
        )
        assert space_response.status_code == 201, space_response.text
        space_id = space_response.json()["id"]
        existing_tag = client.post(
            "/api/knowledge/tags",
            headers=headers,
            json={
                "spaceId": space_id,
                "namespace": "topic",
                "canonicalName": "AI 자동화",
            },
        )
        assert existing_tag.status_code == 201, existing_tag.text

        body = "문서 태그를 한 입력란에서 수정합니다."
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_name == "admin"))
            assert user is not None
            document = KnowledgeDocument(
                space_id=space_id,
                project_id=project_id,
                owner_user_id=user.id,
                title="태그 편집 문서",
                body=body,
                researched_at=datetime(2026, 7, 25, tzinfo=UTC),
                citations_json=[],
                content_digest=sha256(body.encode("utf-8")).hexdigest(),
                status="active",
            )
            db.add(document)
            db.commit()
            document_id = document.id

        updated = client.patch(
            f"/api/knowledge/documents/{document_id}",
            headers=headers,
            json={"tags": ["AI 자동화", "두 울", "AI 자동화"]},
        )
        assert updated.status_code == 200, updated.text
        assert [tag["name"] for tag in updated.json()["tags"]] == [
            "AI 자동화",
            "두 울",
        ]
        assert updated.json()["tags"][0]["id"] == existing_tag.json()["id"]

        ten_tags = client.patch(
            f"/api/knowledge/documents/{document_id}",
            headers=headers,
            json={
                "tags": [
                    "하나", "둘", "셋", "넷", "다섯",
                    "여섯", "일곱", "여덟", "아홉", "열",
                ]
            },
        )
        assert ten_tags.status_code == 200, ten_tags.text
        assert len(ten_tags.json()["tags"]) == 10

        cleared = client.patch(
            f"/api/knowledge/documents/{document_id}",
            headers=headers,
            json={"tags": []},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["tags"] == []

        too_many = client.patch(
            f"/api/knowledge/documents/{document_id}",
            headers=headers,
            json={
                "tags": [
                    "하나", "둘", "셋", "넷", "다섯", "여섯",
                    "일곱", "여덟", "아홉", "열", "열하나",
                ]
            },
        )
        assert too_many.status_code == 422, too_many.text


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
        assert space.json()["useMode"] == "auto"

        updated = client.patch(
            f"/api/knowledge/spaces/{space.json()['id']}",
            headers=headers,
            json={
                "expectedRevision": space.json()["settingsRevision"],
                "projectIds": [project.json()["id"]],
                "useMode": "deep",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["projectIds"] == [project.json()["id"]]
        assert updated.json()["useMode"] == "deep"
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
        assert client.get("/api/knowledge/spaces").json()[0]["useMode"] == "deep"


def test_manual_tag_dictionary_supports_definitions_aliases_and_hierarchy(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-tags.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        space = client.post(
            "/api/knowledge/spaces",
            headers=headers,
            json={"name": "경쟁사 분석 지식"},
        )
        assert space.status_code == 201, space.text
        space_id = space.json()["id"]

        parent = client.post(
            "/api/knowledge/tags",
            headers=headers,
            json={
                "spaceId": space_id,
                "namespace": "company",
                "canonicalName": "철강사",
                "definition": "철강 제품을 생산하는 기업",
            },
        )
        assert parent.status_code == 201, parent.text
        assert parent.json()["usageCount"] == 0

        child = client.post(
            "/api/knowledge/tags",
            headers=headers,
            json={
                "spaceId": space_id,
                "namespace": "company",
                "canonicalName": "포스코",
                "definition": "포스코홀딩스의 철강 사업회사",
                "aliases": ["POSCO"],
                "parentTagId": parent.json()["id"],
            },
        )
        assert child.status_code == 201, child.text
        assert child.json()["parentTagId"] == parent.json()["id"]
        assert child.json()["aliases"] == ["POSCO"]
        assert child.json()["revision"] == 1

        updated = client.patch(
            f"/api/knowledge/tags/{child.json()['id']}",
            headers=headers,
            json={
                "expectedRevision": child.json()["revision"],
                "canonicalName": "포스코홀딩스",
                "definition": "포스코그룹의 지주회사",
                "aliases": ["POSCO Holdings", "포스코홀딩스"],
                "parentTagId": parent.json()["id"],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "포스코홀딩스"
        assert updated.json()["definition"] == "포스코그룹의 지주회사"
        assert updated.json()["aliases"] == ["POSCO Holdings"]
        assert updated.json()["revision"] == 2

        listing = client.get("/api/knowledge/tags", params={"spaceId": space_id})
        assert listing.status_code == 200, listing.text
        assert {item["name"] for item in listing.json()} == {"철강사", "포스코홀딩스"}

        stale = client.patch(
            f"/api/knowledge/tags/{child.json()['id']}",
            headers=headers,
            json={"expectedRevision": 1, "definition": "오래된 변경"},
        )
        assert stale.status_code == 409, stale.text

        wrong_parent = client.post(
            "/api/knowledge/tags",
            headers=headers,
            json={
                "spaceId": space_id,
                "namespace": "purpose",
                "canonicalName": "경쟁사 분석",
                "parentTagId": parent.json()["id"],
            },
        )
        assert wrong_parent.status_code == 409, wrong_parent.text
