from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.main import create_app


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

        lumina_id = _create_entity(client, headers, space_id, "Lumina")
        knowledge_id = _create_entity(client, headers, space_id, "Knowledge")
        source_entity_id = _create_entity(client, headers, space_id, "Source")

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
        forbidden_graph = client.get(
            f"/api/knowledge/entities/{lumina_id}/neighborhood"
        )
        assert forbidden_graph.status_code == 404
        assert forbidden_graph.json()["code"] == "knowledge_space_not_found"
