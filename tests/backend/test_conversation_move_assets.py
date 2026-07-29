from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Artifact, Attachment, Run


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1111",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def _wait_for_completed(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200, response.text
        snapshot = response.json()
        if snapshot["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            assert snapshot["status"] == "completed", snapshot
            return snapshot
        time.sleep(0.02)
    raise AssertionError("Run did not complete")


def test_move_keeps_run_snapshot_and_moves_session_owned_assets(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'move.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        source_project_id = client.get("/api/projects").json()[0]["id"]
        destination = client.post(
            "/api/projects",
            headers={"X-CSRF-Token": csrf},
            json={"name": "이동 대상", "description": ""},
        )
        assert destination.status_code == 201, destination.text
        destination_project_id = destination.json()["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": source_project_id, "title": "자산 이동"},
        ).json()

        uploaded = client.post(
            f"/api/conversations/{conversation['id']}/attachments",
            headers={"X-CSRF-Token": csrf},
            files={
                "file": ("점검.md", "# 점검\n\n이상 없음".encode(), "text/markdown")
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        attachment_id = uploaded.json()["id"]

        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "move-assets-run-0001",
            },
            json={
                "message": {
                    "text": "첨부를 바탕으로 HTML 보고서 Artifact를 만들어 주세요.",
                    "attachmentIds": [attachment_id],
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
        snapshot = _wait_for_completed(client, run_id)
        assert len(snapshot["artifacts"]) == 1
        artifact_id = snapshot["artifacts"][0]["id"]

        moved = client.post(
            f"/api/conversations/{conversation['id']}/move",
            headers={"X-CSRF-Token": csrf},
            json={
                "projectId": destination_project_id,
                "idempotencyKey": "move-assets-0001",
            },
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["projectId"] == destination_project_id

        # Retrying an already-applied move is a no-op instead of changing revision again.
        repeated = client.post(
            f"/api/conversations/{conversation['id']}/move",
            headers={"X-CSRF-Token": csrf},
            json={
                "projectId": destination_project_id,
                "idempotencyKey": "move-assets-0001",
            },
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["revision"] == moved.json()["revision"]

        with SessionLocal() as db:
            stored_run = db.get(Run, run_id)
            stored_attachment = db.get(Attachment, attachment_id)
            stored_artifact = db.get(Artifact, artifact_id)
            assert stored_run is not None and stored_run.project_id == source_project_id
            assert (
                stored_attachment is not None
                and stored_attachment.project_id == destination_project_id
            )
            assert (
                stored_artifact is not None
                and stored_artifact.project_id == destination_project_id
            )

        destination_suggestions = client.get(
            "/api/composer/suggestions",
            params={"project_id": destination_project_id, "trigger": "@"},
        )
        assert destination_suggestions.status_code == 200
        destination_ids = {
            item["referenceId"] for item in destination_suggestions.json()["items"]
        }
        assert {attachment_id, artifact_id}.issubset(destination_ids)

        source_suggestions = client.get(
            "/api/composer/suggestions",
            params={"project_id": source_project_id, "trigger": "@"},
        )
        assert source_suggestions.status_code == 200
        source_ids = {
            item["referenceId"] for item in source_suggestions.json()["items"]
        }
        assert attachment_id not in source_ids
        assert artifact_id not in source_ids

        follow_up = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "move-assets-run-0002",
            },
            json={
                "message": {
                    "text": "옮겨진 첨부 내용을 다시 요약해 주세요.",
                    "attachmentIds": [attachment_id],
                    "promptReferences": [],
                },
                "execution": {
                    "providerId": "mock",
                    "modelKey": "mock-agent",
                    "effortId": "medium",
                },
            },
        )
        assert follow_up.status_code == 202, follow_up.text
        _wait_for_completed(client, follow_up.json()["run"]["runId"])
