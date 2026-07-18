from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient

from lumina.agent.executor import LocalRunExecutor, local_run_executor
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Run
from lumina.providers.mock import MockProvider


def _login(client: TestClient, login_name: str, password: str) -> str:
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


def _create_user(
    client: TestClient, csrf: str, *, login_name: str, display_name: str
) -> dict[str, object]:
    response = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": csrf},
        json={
            "loginName": login_name,
            "loginDomain": "posco.com",
            "password": f"{login_name}-password",
            "displayName": display_name,
            "affiliation": "Knowledge 팀",
            "role": "user",
            "status": "active",
            "mustChangePassword": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_entity(
    client: TestClient,
    headers: dict[str, str],
    space_id: str,
    name: str,
) -> str:
    response = client.post(
        f"/api/knowledge/spaces/{space_id}/entities",
        headers=headers,
        json={"entityType": "concept", "canonicalName": name},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _start_knowledge_run(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    *,
    text: str,
    suffix: str,
) -> str:
    conversation = client.post(
        "/api/conversations",
        headers=headers,
        json={"projectId": project_id, "title": f"Knowledge context {suffix}"},
    )
    assert conversation.status_code == 201, conversation.text
    started = client.post(
        f"/api/conversations/{conversation.json()['id']}/runs",
        headers={**headers, "Idempotency-Key": f"knowledge-context-{suffix}"},
        json={
            "message": {"text": text, "attachmentIds": [], "promptReferences": []},
            "execution": {
                "providerId": "mock",
                "modelKey": "mock-agent",
                "effortId": "medium",
            },
        },
    )
    assert started.status_code == 202, started.text
    return started.json()["run"]["runId"]


def test_knowledge_auto_capture_defaults_to_first_space_and_can_move(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-auto-capture.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client, "admin", "1")
        headers = {"X-CSRF-Token": csrf}
        first = client.post(
            "/api/knowledge/spaces", headers=headers, json={"name": "철강 기술 동향"}
        )
        assert first.status_code == 201, first.text
        setting = client.get("/api/knowledge/auto-capture")
        assert setting.status_code == 200, setting.text
        assert setting.json() == {
            "enabled": True,
            "spaceId": first.json()["id"],
            "mode": "research",
        }

        second = client.post(
            "/api/knowledge/spaces", headers=headers, json={"name": "신소재 연구"}
        )
        moved = client.patch(
            "/api/knowledge/auto-capture",
            headers=headers,
            json={"enabled": True, "spaceId": second.json()["id"]},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["spaceId"] == second.json()["id"]

        disabled = client.patch(
            "/api/knowledge/auto-capture",
            headers=headers,
            json={"enabled": False},
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json() == {
            "enabled": False,
            "spaceId": None,
            "mode": "research",
        }


def test_wiki_pages_preserve_manual_markdown_across_generated_revisions(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-wiki.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client, "admin", "1")
        headers = {"X-CSRF-Token": csrf}
        space = client.post(
            "/api/knowledge/spaces", headers=headers, json={"name": "철강 Wiki"}
        ).json()
        evidence_text = "수소환원제철은 철광석 환원 과정의 탄소 배출을 줄입니다."
        source = client.post(
            f"/api/knowledge/spaces/{space['id']}/sources",
            headers=headers,
            json={
                "sourceType": "text",
                "title": "수소환원제철 검증 자료",
                "contentDigest": sha256(evidence_text.encode()).hexdigest(),
                "mediaType": "text/plain",
                "byteSize": len(evidence_text.encode()),
                "capturedText": evidence_text,
                "evidenceSegments": [{"text": evidence_text}],
            },
        ).json()
        process_id = _create_entity(client, headers, space["id"], "수소환원제철")
        impact_id = _create_entity(client, headers, space["id"], "탄소배출감축")

        initial_pages = client.get(
            f"/api/knowledge/spaces/{space['id']}/pages"
        ).json()
        process_page = next(
            page for page in initial_pages if page["entityId"] == process_id
        )
        assert process_page["currentRevision"]["revisionNumber"] == 1

        approved = client.post(
            f"/api/knowledge/spaces/{space['id']}/statements",
            headers=headers,
            json={
                "subjectEntityId": process_id,
                "predicateKey": "REDUCES",
                "objectKind": "entity",
                "objectEntityId": impact_id,
                "evidenceSegmentIds": [source["evidenceSegments"][0]["id"]],
                "status": "approved",
            },
        )
        assert approved.status_code == 201, approved.text
        generated_page = next(
            page
            for page in client.get(
                f"/api/knowledge/spaces/{space['id']}/pages"
            ).json()
            if page["entityId"] == process_id
        )
        assert generated_page["currentRevision"]["revisionNumber"] == 2
        assert "`REDUCES`" in generated_page["currentRevision"]["generatedMarkdown"]

        edited = client.patch(
            f"/api/knowledge/pages/{process_page['id']}",
            headers=headers,
            json={
                "expectedRevision": 2,
                "manualMarkdown": "상용화 일정과 실증 규모를 매 분기 확인합니다.",
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["currentRevision"]["revisionNumber"] == 3
        assert "매 분기 확인" in edited.json()["currentRevision"]["markdownBody"]

        refreshed = client.post(
            f"/api/knowledge/spaces/{space['id']}/statements",
            headers=headers,
            json={
                "subjectEntityId": process_id,
                "predicateKey": "SUPPORTS",
                "objectKind": "entity",
                "objectEntityId": impact_id,
                "evidenceSegmentIds": [source["evidenceSegments"][0]["id"]],
                "status": "approved",
            },
        )
        assert refreshed.status_code == 201, refreshed.text
        current = next(
            page
            for page in client.get(
                f"/api/knowledge/spaces/{space['id']}/pages"
            ).json()
            if page["entityId"] == process_id
        )
        assert current["currentRevision"]["revisionNumber"] == 4
        assert current["currentRevision"]["manualMarkdown"] == (
            "상용화 일정과 실증 규모를 매 분기 확인합니다."
        )
        assert "`SUPPORTS`" in current["currentRevision"]["generatedMarkdown"]

        revisions = client.get(
            f"/api/knowledge/pages/{process_page['id']}/revisions"
        )
        assert revisions.status_code == 200, revisions.text
        assert [item["revisionNumber"] for item in revisions.json()] == [4, 3, 2, 1]
        stale = client.patch(
            f"/api/knowledge/pages/{process_page['id']}",
            headers=headers,
            json={"expectedRevision": 3, "manualMarkdown": "stale"},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "knowledge_page_revision_conflict"


def test_personal_knowledge_source_statement_and_bounded_graph(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        admin_csrf = _login(client, "admin", "1")
        _create_user(client, admin_csrf, login_name="alice", display_name="Alice")
        _create_user(client, admin_csrf, login_name="bob", display_name="Bob")

        client.cookies.clear()
        alice_csrf = _login(client, "alice", "alice-password")
        headers = {"X-CSRF-Token": alice_csrf}
        space = client.post(
            "/api/knowledge/spaces",
            headers=headers,
            json={
                "name": "개인 연구 지식",
                "description": "계정 단위 테스트",
                "purpose": "근거가 있는 Statement 관리",
            },
        )
        assert space.status_code == 201, space.text
        space_id = space.json()["id"]
        assert space.json()["spaceType"] == "personal"
        assert space.json()["visibility"] == "private"

        source_text = "Lumina Knowledge는 Source와 Statement를 분리한다."
        digest = sha256(source_text.encode("utf-8")).hexdigest()
        source_request = {
            "sourceType": "text",
            "title": "Knowledge 설계 메모",
            "contentDigest": digest,
            "mediaType": "text/plain",
            "byteSize": len(source_text.encode("utf-8")),
            "capturedText": source_text,
            "evidenceSegments": [
                {
                    "text": source_text,
                    "locator": {"paragraph": 1},
                    "language": "ko",
                    "tokenCount": 12,
                }
            ],
        }
        source = client.post(
            f"/api/knowledge/spaces/{space_id}/sources",
            headers=headers,
            json=source_request,
        )
        assert source.status_code == 201, source.text
        evidence_id = source.json()["evidenceSegments"][0]["id"]
        duplicate = client.post(
            f"/api/knowledge/spaces/{space_id}/sources",
            headers=headers,
            json=source_request,
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["id"] == source.json()["id"]
        assert duplicate.json()["revision"]["id"] == source.json()["revision"]["id"]
        sources = client.get(f"/api/knowledge/spaces/{space_id}/sources")
        assert sources.status_code == 200
        assert [item["title"] for item in sources.json()] == ["Knowledge 설계 메모"]
        assert sources.json()[0]["evidenceSegments"][0]["id"] == evidence_id

        lumina_id = _create_entity(client, headers, space_id, "Lumina")
        knowledge_id = _create_entity(client, headers, space_id, "Knowledge")
        source_entity_id = _create_entity(client, headers, space_id, "Source")
        entities = client.get(f"/api/knowledge/spaces/{space_id}/entities")
        assert entities.status_code == 200
        assert [item["canonicalName"] for item in entities.json()] == [
            "Knowledge",
            "Lumina",
            "Source",
        ]

        first_statement = client.post(
            f"/api/knowledge/spaces/{space_id}/statements",
            headers=headers,
            json={
                "subjectEntityId": lumina_id,
                "predicateKey": "USES",
                "objectKind": "entity",
                "objectEntityId": knowledge_id,
                "evidenceSegmentIds": [evidence_id],
                "status": "approved",
                "confidence": 0.9,
                "changeSummary": "수동 근거 등록",
            },
        )
        assert first_statement.status_code == 201, first_statement.text
        assert first_statement.json()["revisionNumber"] == 1
        assert first_statement.json()["evidenceSegmentIds"] == [evidence_id]

        second_statement = client.post(
            f"/api/knowledge/spaces/{space_id}/statements",
            headers=headers,
            json={
                "subjectEntityId": knowledge_id,
                "predicateKey": "DERIVED_FROM",
                "objectKind": "entity",
                "objectEntityId": source_entity_id,
                "evidenceSegmentIds": [evidence_id],
                "status": "approved",
            },
        )
        assert second_statement.status_code == 201, second_statement.text
        assert second_statement.json()["revisionNumber"] == 2

        missing_evidence = client.post(
            f"/api/knowledge/spaces/{space_id}/statements",
            headers=headers,
            json={
                "subjectEntityId": lumina_id,
                "predicateKey": "CLAIMS",
                "objectKind": "text",
                "objectValue": "근거 없는 승인",
                "status": "approved",
            },
        )
        assert missing_evidence.status_code == 422
        assert missing_evidence.json()["code"] == "validation_failed"

        depth_one = client.get(
            f"/api/knowledge/entities/{lumina_id}/neighborhood?maxDepth=1"
        )
        assert depth_one.status_code == 200, depth_one.text
        assert {node["canonicalName"] for node in depth_one.json()["nodes"]} == {
            "Lumina",
            "Knowledge",
        }
        depth_two = client.get(
            f"/api/knowledge/entities/{lumina_id}/neighborhood?maxDepth=2"
        )
        assert depth_two.status_code == 200, depth_two.text
        assert {node["canonicalName"] for node in depth_two.json()["nodes"]} == {
            "Lumina",
            "Knowledge",
            "Source",
        }
        assert len(depth_two.json()["edges"]) == 2

        statements = client.get(f"/api/knowledge/spaces/{space_id}/statements")
        assert statements.status_code == 200
        assert len(statements.json()) == 2

        client.cookies.clear()
        _login(client, "bob", "bob-password")
        assert client.get("/api/knowledge/spaces").json() == []
        forbidden_space = client.get(f"/api/knowledge/spaces/{space_id}")
        assert forbidden_space.status_code == 404
        assert forbidden_space.json()["code"] == "knowledge_space_not_found"
        assert (
            client.get(f"/api/knowledge/spaces/{space_id}/sources").status_code == 404
        )
        assert (
            client.get(f"/api/knowledge/spaces/{space_id}/entities").status_code == 404
        )
        forbidden_graph = client.get(
            f"/api/knowledge/entities/{lumina_id}/neighborhood"
        )
        assert forbidden_graph.status_code == 404
        assert forbidden_graph.json()["code"] == "knowledge_space_not_found"

        client.cookies.clear()
        _login(client, "admin", "1")
        assert client.get("/api/knowledge/spaces").json() == []
        assert client.get(f"/api/knowledge/spaces/{space_id}").status_code == 404


def test_project_binding_pins_an_approved_revision_until_explicit_update(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-binding.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client, "admin", "1")
        headers = {"X-CSRF-Token": csrf}
        project = client.get("/api/projects").json()[0]
        space = client.post(
            "/api/knowledge/spaces",
            headers=headers,
            json={"name": "Project 고정 지식"},
        ).json()
        source_text = "수소환원제철은 탄소 배출 저감 기술과 연결됩니다."
        source = client.post(
            f"/api/knowledge/spaces/{space['id']}/sources",
            headers=headers,
            json={
                "sourceType": "text",
                "title": "고정 revision 근거",
                "contentDigest": sha256(source_text.encode()).hexdigest(),
                "mediaType": "text/plain",
                "byteSize": len(source_text.encode()),
                "capturedText": source_text,
                "evidenceSegments": [{"text": source_text}],
            },
        ).json()
        subject_id = _create_entity(client, headers, space["id"], "수소환원제철")
        object_id = _create_entity(client, headers, space["id"], "탄소배출저감")
        first = client.post(
            f"/api/knowledge/spaces/{space['id']}/statements",
            headers=headers,
            json={
                "subjectEntityId": subject_id,
                "predicateKey": "REDUCES",
                "objectKind": "entity",
                "objectEntityId": object_id,
                "evidenceSegmentIds": [source["evidenceSegments"][0]["id"]],
                "status": "approved",
                "changeSummary": "첫 승인",
            },
        )
        assert first.status_code == 201, first.text

        revisions = client.get(
            f"/api/knowledge/spaces/{space['id']}/revisions"
        )
        assert revisions.status_code == 200, revisions.text
        assert [item["revisionNumber"] for item in revisions.json()] == [1]
        binding = client.post(
            f"/api/knowledge/spaces/{space['id']}/project-bindings",
            headers=headers,
            json={
                "projectId": project["id"],
                "knowledgeRevisionId": first.json()["revisionId"],
            },
        )
        assert binding.status_code == 201, binding.text
        assert binding.json()["projectName"] == project["name"]
        assert binding.json()["knowledgeRevision"]["revisionNumber"] == 1
        assert binding.json()["bindingRevision"] == 1
        assert binding.json()["followLatestApproved"] is False

        duplicate = client.post(
            f"/api/knowledge/spaces/{space['id']}/project-bindings",
            headers=headers,
            json={
                "projectId": project["id"],
                "knowledgeRevisionId": first.json()["revisionId"],
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "knowledge_project_binding_exists"

        second = client.post(
            f"/api/knowledge/spaces/{space['id']}/statements",
            headers=headers,
            json={
                "subjectEntityId": subject_id,
                "predicateKey": "SUPPORTS",
                "objectKind": "entity",
                "objectEntityId": object_id,
                "evidenceSegmentIds": [source["evidenceSegments"][0]["id"]],
                "status": "approved",
                "changeSummary": "두 번째 승인",
            },
        )
        assert second.status_code == 201, second.text
        pinned = client.get(
            f"/api/knowledge/spaces/{space['id']}/project-bindings"
        ).json()[0]
        assert pinned["knowledgeRevision"]["revisionNumber"] == 1
        context_pack_response = client.post(
            "/api/knowledge/context-packs",
            headers=headers,
            json={
                "projectId": project["id"],
                "query": "수소환원제철 탄소배출저감",
                "maxStatements": 8,
                "characterBudget": 8000,
            },
        )
        assert context_pack_response.status_code == 200, context_pack_response.text
        assert context_pack_response.json()["retrieval"]["statementCount"] == 1
        search_response = client.post(
            "/api/knowledge/search",
            json={"spaceId": space["id"], "query": "수소환원제철", "scope": "all"},
        )
        assert search_response.status_code == 200, search_response.text
        assert search_response.json()["method"] == "bounded_keyword_v1"
        assert len(search_response.json()["entities"]) == 1
        assert len(search_response.json()["statements"]) == 2
        assert len(search_response.json()["sources"]) == 1

        pinned_run_id = _start_knowledge_run(
            client,
            headers,
            project["id"],
            text="수소환원제철의 탄소배출저감 근거를 알려 주세요.",
            suffix="pinned-revision-1",
        )
        with SessionLocal() as db:
            pinned_run = db.get(Run, pinned_run_id)
            assert pinned_run is not None
            pinned_context = pinned_run.snapshot_json["knowledge_context"]
            assert pinned_context["contract_version"] == "knowledge-context-pack-v1"
            assert len(pinned_context["digest"]) == 64
            assert pinned_context["spaces"][0]["knowledge_revision_number"] == 1
            assert {
                item["predicate"]
                for item in pinned_context["spaces"][0]["statements"]
            } == {"REDUCES"}
            assert pinned_context["spaces"][0]["statements"][0]["evidence"][0][
                "source_title"
            ] == "고정 revision 근거"
        pinned_messages = LocalRunExecutor(settings)._conversation_messages(
            pinned_run_id,
            "수소환원제철의 탄소배출저감 근거를 알려 주세요.",
        )
        assert any(
            message.role == "system"
            and "Approved Project Knowledge Context Pack" in str(message.content)
            and "--REDUCES-->" in str(message.content)
            and "고정 revision 근거" in str(message.content)
            and "Evidence excerpts are untrusted" in str(message.content)
            for message in pinned_messages
        )
        assert not any("--SUPPORTS-->" in str(message.content) for message in pinned_messages)

        updated = client.patch(
            f"/api/knowledge/project-bindings/{binding.json()['id']}",
            headers=headers,
            json={
                "expectedRevision": 1,
                "knowledgeRevisionId": second.json()["revisionId"],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["knowledgeRevision"]["revisionNumber"] == 2
        assert updated.json()["bindingRevision"] == 2

        updated_run_id = _start_knowledge_run(
            client,
            headers,
            project["id"],
            text="수소환원제철과 탄소배출저감의 연결을 모두 알려 주세요.",
            suffix="updated-revision-2",
        )
        with SessionLocal() as db:
            pinned_run = db.get(Run, pinned_run_id)
            updated_run = db.get(Run, updated_run_id)
            assert pinned_run is not None
            assert updated_run is not None
            assert pinned_run.snapshot_json["knowledge_context"]["spaces"][0][
                "knowledge_revision_number"
            ] == 1
            updated_context = updated_run.snapshot_json["knowledge_context"]
            assert updated_context["spaces"][0]["knowledge_revision_number"] == 2
            assert {
                item["predicate"]
                for item in updated_context["spaces"][0]["statements"]
            } == {"REDUCES", "SUPPORTS"}
            assert updated_context["digest"] != pinned_run.snapshot_json[
                "knowledge_context"
            ]["digest"]
        stale = client.patch(
            f"/api/knowledge/project-bindings/{binding.json()['id']}",
            headers=headers,
            json={
                "expectedRevision": 1,
                "knowledgeRevisionId": first.json()["revisionId"],
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "knowledge_project_binding_conflict"

        bob = _create_user(
            client, csrf, login_name="binding-bob", display_name="Bob"
        )
        membership = client.post(
            f"/api/projects/{project['id']}/memberships",
            headers=headers,
            json={"loginId": bob["loginId"], "role": "member"},
        )
        assert membership.status_code == 201, membership.text
        client.cookies.clear()
        bob_csrf = _login(client, "binding-bob", "binding-bob-password")
        shared_space = client.get(f"/api/knowledge/spaces/{space['id']}")
        assert shared_space.status_code == 200, shared_space.text
        assert shared_space.json()["accessMode"] == "project_read"
        assert client.get(f"/api/knowledge/spaces/{space['id']}/sources").status_code == 200
        assert client.get(f"/api/knowledge/spaces/{space['id']}/statements").status_code == 200
        member_search = client.post(
            "/api/knowledge/search",
            json={"spaceId": space["id"], "query": "수소환원제철"},
        )
        assert member_search.status_code == 200, member_search.text
        assert len(member_search.json()["statements"]) == 2
        assert client.patch(
            f"/api/knowledge/spaces/{space['id']}",
            headers={"X-CSRF-Token": bob_csrf},
            json={"expectedRevision": 1, "name": "권한 없음"},
        ).status_code == 404
        assert (
            client.post(
                "/api/knowledge/context-packs",
                headers={"X-CSRF-Token": bob_csrf},
                json={"projectId": project["id"], "query": "수소환원제철"},
            ).status_code
            == 200
        )

        client.cookies.clear()
        csrf = _login(client, "admin", "1")
        deleted = client.delete(
            f"/api/knowledge/project-bindings/{binding.json()['id']}"
            "?expectedRevision=2",
            headers={"X-CSRF-Token": csrf},
        )
        assert deleted.status_code == 204, deleted.text
        assert (
            client.get(
                f"/api/knowledge/spaces/{space['id']}/project-bindings"
            ).json()
            == []
        )
        client.cookies.clear()
        _login(client, "binding-bob", "binding-bob-password")
        assert client.get(f"/api/knowledge/spaces/{space['id']}").status_code == 404
        assert client.post(
            "/api/knowledge/search",
            json={"spaceId": space["id"], "query": "수소환원제철"},
        ).status_code == 404


def test_knowledge_ingestion_runs_structured_extraction_and_reuses_result(
    tmp_path: Path, monkeypatch
) -> None:
    extraction_json = json.dumps(
        {
            "entities": [
                {
                    "key": "lumina",
                    "entityType": "product",
                    "canonicalName": "Lumina",
                    "description": "지식 기능을 제공하는 제품",
                },
                {
                    "key": "knowledge",
                    "entityType": "feature",
                    "canonicalName": "Knowledge",
                    "description": "근거 기반 지식 기능",
                },
            ],
            "statements": [
                {
                    "subjectKey": "lumina",
                    "predicateKey": "HAS_FEATURE",
                    "objectKey": "knowledge",
                    "confidence": 0.94,
                    "evidenceSegmentIds": ["placeholder"],
                }
            ],
        },
        ensure_ascii=False,
    )

    def provider_for_test(_provider_id: str) -> MockProvider:
        return MockProvider(text_chunks=(extraction_json,))

    monkeypatch.setattr(local_run_executor, "provider_for_probe", provider_for_test)
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-ingestion.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client, "admin", "1")
        headers = {"X-CSRF-Token": csrf}
        space_response = client.post(
            "/api/knowledge/spaces",
            headers=headers,
            json={"name": "AI 추출 검증", "purpose": "구조화 추출 실행 검증"},
        )
        assert space_response.status_code == 201, space_response.text
        space_id = space_response.json()["id"]
        source_text = "Lumina는 근거 기반 Knowledge 기능을 제공한다."
        source_response = client.post(
            f"/api/knowledge/spaces/{space_id}/sources",
            headers=headers,
            json={
                "sourceType": "text",
                "title": "제품 설명",
                "contentDigest": sha256(source_text.encode()).hexdigest(),
                "mediaType": "text/plain",
                "byteSize": len(source_text.encode()),
                "capturedText": source_text,
                "evidenceSegments": [{"text": source_text}],
            },
        )
        assert source_response.status_code == 201, source_response.text
        source = source_response.json()
        evidence_id = source["evidenceSegments"][0]["id"]
        extraction_json = json.dumps(
            {
                **json.loads(extraction_json),
                "statements": [
                    {
                        "subjectKey": "lumina",
                        "predicateKey": "HAS_FEATURE",
                        "objectKey": "knowledge",
                        "confidence": 0.94,
                        "evidenceSegmentIds": [evidence_id],
                    },
                    {
                        "subjectKey": "lumina",
                        "predicateKey": "UNSUPPORTED",
                        "objectKey": "knowledge",
                        "confidence": 0.2,
                        "evidenceSegmentIds": ["unknown-evidence"],
                    },
                ],
            },
            ensure_ascii=False,
        )

        started = client.post(
            f"/api/knowledge/spaces/{space_id}/sources/{source['id']}/ingestions",
            headers=headers,
        )
        assert started.status_code == 202, started.text
        job = started.json()
        for _ in range(100):
            jobs = client.get(f"/api/knowledge/spaces/{space_id}/ingestions").json()
            job = jobs[0]
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed", job
        assert job["entityCount"] == 2
        assert job["statementCount"] == 1
        assert job["inputSegmentCount"] == 1
        assert job["inputTokens"] == 8

        entities = client.get(f"/api/knowledge/spaces/{space_id}/entities").json()
        assert {entity["canonicalName"] for entity in entities} == {
            "Lumina",
            "Knowledge",
        }
        statements = client.get(f"/api/knowledge/spaces/{space_id}/statements").json()
        assert len(statements) == 1
        assert statements[0]["status"] == "proposed"
        assert statements[0]["evidenceSegmentIds"] == [evidence_id]

        reused = client.post(
            f"/api/knowledge/spaces/{space_id}/sources/{source['id']}/ingestions",
            headers=headers,
        )
        assert reused.status_code == 200, reused.text
        assert reused.json()["id"] == job["id"]


def test_knowledge_review_settings_and_archive_preserve_revision_history(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-review.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client, "admin", "1")
        headers = {"X-CSRF-Token": csrf}
        space = client.post(
            "/api/knowledge/spaces",
            headers=headers,
            json={"name": "검토 공간", "purpose": "승인 흐름 검증"},
        ).json()
        space_id = space["id"]
        source_text = "Lumina Knowledge는 근거를 보존한다."
        source = client.post(
            f"/api/knowledge/spaces/{space_id}/sources",
            headers=headers,
            json={
                "sourceType": "text",
                "title": "검토 근거",
                "contentDigest": sha256(source_text.encode()).hexdigest(),
                "mediaType": "text/plain",
                "byteSize": len(source_text.encode()),
                "capturedText": source_text,
                "evidenceSegments": [{"text": source_text}],
            },
        ).json()
        subject_id = _create_entity(client, headers, space_id, "Lumina Knowledge")
        object_id = _create_entity(client, headers, space_id, "Evidence")
        proposed = client.post(
            f"/api/knowledge/spaces/{space_id}/statements",
            headers=headers,
            json={
                "subjectEntityId": subject_id,
                "predicateKey": "PRESERVES",
                "objectKind": "entity",
                "objectEntityId": object_id,
                "evidenceSegmentIds": [source["evidenceSegments"][0]["id"]],
                "status": "proposed",
            },
        )
        assert proposed.status_code == 201, proposed.text

        reviewed = client.post(
            f"/api/knowledge/reviews/{proposed.json()['id']}/decision",
            headers=headers,
            json={"decision": "approved", "reason": "원문 근거 확인"},
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["id"] != proposed.json()["id"]
        assert reviewed.json()["status"] == "approved"
        assert reviewed.json()["revisionNumber"] == 2
        current = client.get(f"/api/knowledge/spaces/{space_id}/statements").json()
        assert [item["id"] for item in current] == [reviewed.json()["id"]]
        duplicate = client.post(
            f"/api/knowledge/reviews/{proposed.json()['id']}/decision",
            headers=headers,
            json={"decision": "rejected"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "knowledge_statement_already_reviewed"

        updated = client.patch(
            f"/api/knowledge/spaces/{space_id}",
            headers=headers,
            json={
                "expectedRevision": 1,
                "name": "검토 완료 공간",
                "description": "설정 revision 검증",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["settingsRevision"] == 2
        stale = client.patch(
            f"/api/knowledge/spaces/{space_id}",
            headers=headers,
            json={"expectedRevision": 1, "name": "충돌"},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "knowledge_space_revision_conflict"

        archived = client.delete(
            f"/api/knowledge/spaces/{space_id}?expectedRevision=2",
            headers=headers,
        )
        assert archived.status_code == 204, archived.text
        assert client.get("/api/knowledge/spaces").json() == []
        assert client.get(f"/api/knowledge/spaces/{space_id}").status_code == 404
