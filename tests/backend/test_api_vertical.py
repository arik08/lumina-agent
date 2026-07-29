from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.main import create_app


def test_login_run_replay_and_artifact_version(tmp_path: Path, capsys) -> None:
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
                "password": "1111",
            },
        )
        assert login.status_code == 200
        csrf = login.json()["csrfToken"]
        headers = {"X-CSRF-Token": csrf}

        projects = client.get("/api/projects")
        assert projects.status_code == 200
        project_id = projects.json()[0]["id"]

        provider_catalog = client.get(
            "/api/provider-catalog", params={"project_id": project_id}
        )
        assert provider_catalog.status_code == 200, provider_catalog.text
        assert (
            provider_catalog.json()["modelsByProvider"]["mock"][0]["modelKey"]
            == "mock-agent"
        )
        assert provider_catalog.json()["providers"][0]["id"] == "mock"

        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "통합 실행 테스트"},
        )
        assert conversation.status_code == 201
        conversation_id = conversation.json()["id"]

        started = client.post(
            f"/api/conversations/{conversation_id}/runs",
            headers={**headers, "Idempotency-Key": "vertical-run-0001"},
            json={
                "message": {
                    "text": "점검 결과를 HTML 보고서 Artifact로 만들어 줘",
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
        run_id = started.json()["run"]["runId"]

        snapshot = _wait_for_terminal(client, run_id)
        assert snapshot["status"] == "completed"
        snapshots = client.post(
            "/api/runs/snapshots",
            headers={**headers, "Accept-Encoding": "gzip"},
            json={"runIds": [run_id]},
        )
        assert snapshots.status_code == 200, snapshots.text
        assert snapshots.headers["content-encoding"] == "gzip"
        assert [item["runId"] for item in snapshots.json()] == [run_id]
        activity_lines = [
            line
            for line in capsys.readouterr().out.splitlines()
            if "[Lumina] LLM response" in line
        ]
        assert len(activity_lines) == 2
        assert "LLM response started user=admin@posco.com" in activity_lines[0]
        assert "LLM response completed user=admin@posco.com" in activity_lines[1]
        assert "점검 결과" not in "\n".join(activity_lines)
        assert "Artifact" in snapshot["assistantDraft"]["text"]
        assert len(snapshot["toolExecutions"]) == 1
        assert snapshot["toolExecutions"][0]["status"] == "completed"
        tools_step = next(
            step for step in snapshot["plan"]["steps"] if step["key"] == "tools"
        )
        assert [subtask["status"] for subtask in tools_step["subtasks"]] == [
            "completed"
        ]
        assert len(snapshot["artifacts"]) == 1

        replay = client.get(
            f"/stream/runs/{run_id}?after_sequence=0",
            headers={"Accept-Encoding": "gzip"},
        )
        assert replay.status_code == 200
        assert "content-encoding" not in replay.headers
        events = [
            json.loads(line.removeprefix("data: "))
            for line in replay.text.splitlines()
            if line.startswith("data: ")
        ]
        sequences = [event["sequence"] for event in events]
        assert sequences == sorted(set(sequences))
        assert {event["type"] for event in events} >= {
            "run_started",
            "tool_started",
            "tool_completed",
            "artifact_created",
            "run_completed",
        }

        artifact = snapshot["artifacts"][0]
        artifact_id = artifact["id"]
        version = client.get(f"/api/artifacts/{artifact_id}/versions/1")
        assert version.status_code == 200
        version_payload = version.json()
        assert "<!doctype html>" in version_payload["sourceText"]

        saved = client.post(
            f"/api/artifacts/{artifact_id}/versions",
            headers={
                **headers,
                "If-Match": version_payload["etag"],
                "Idempotency-Key": "artifact-save-0001",
            },
            json={
                "baseVersion": 1,
                "sourceText": version_payload["sourceText"]
                .replace("작업 결과 보고서", "수정된 작업 결과 보고서")
                .replace(
                    "</body>",
                    '<div class="mermaid">flowchart TD\nA-->B</div></body>',
                ),
                "changeSummary": "제목 수정",
            },
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["version"] == 2
        downloaded = client.get(f"/api/artifacts/{artifact_id}/download?version=2")
        assert downloaded.status_code == 200
        assert "수정된 작업 결과 보고서" in downloaded.text
        assert "cdn.jsdelivr.net/npm/mermaid@11.16.0" in downloaded.text
        assert 'data-lumina-standalone-mermaid="11.16.0"' in downloaded.text
        assert downloaded.headers["etag"] != f'"{saved.json()["etag"]}"'
        stored_version_two = next(
            path
            for path in (tmp_path / "artifacts").rglob("*")
            if path.is_file() and "수정된 작업 결과 보고서" in path.read_text("utf-8")
        )
        assert "cdn.jsdelivr.net/npm/mermaid" not in stored_version_two.read_text("utf-8")
        stored_version_two.write_bytes(b"tampered artifact")
        unavailable = client.get(f"/api/artifacts/{artifact_id}/download?version=2")
        assert unavailable.status_code == 503
        assert unavailable.json()["code"] == "artifact_content_missing"

        markdown_saved = client.post(
            f"/api/artifacts/from-message/{snapshot['assistantDraft']['messageId']}",
            headers=headers,
        )
        assert markdown_saved.status_code == 201, markdown_saved.text
        markdown_artifact = markdown_saved.json()
        assert markdown_artifact["kind"] == "markdown"
        assert markdown_artifact["mimeType"] == "text/markdown"
        assert markdown_artifact["displayName"].endswith(".md")
        markdown_version = client.get(
            f"/api/artifacts/{markdown_artifact['id']}/versions/1"
        )
        assert markdown_version.status_code == 200
        assert markdown_version.json()["sourceText"].strip()
        assert "Artifact ID" not in markdown_version.json()["sourceText"]
        assert list((tmp_path / "artifacts").rglob("*.md"))


def _wait_for_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {
            "completed",
            "failed",
            "cancelled",
            "limit_reached",
            "interrupted",
        }:
            return payload
        time.sleep(0.03)
    raise AssertionError("Run did not reach a terminal state")
