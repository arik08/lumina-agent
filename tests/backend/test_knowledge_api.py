from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.agent.executor import local_run_executor
from lumina.main import create_app
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
) -> None:
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
