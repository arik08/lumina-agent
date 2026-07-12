from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.main import create_app


def _login(client: TestClient, login_name: str = "admin", password: str = "1") -> str:
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


def _wait_for_terminal(client: TestClient, run_id: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/runs/{run_id}/snapshot")
        assert snapshot.status_code == 200, snapshot.text
        status = snapshot.json()["status"]
        if status in {"completed", "failed", "cancelled", "interrupted"}:
            assert status == "completed"
            return
        time.sleep(0.02)
    raise AssertionError("Run did not finish")


def test_branch_preserves_completed_transcript_and_exports_json_markdown(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'branch.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "원본 대화"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "branch-export-run-0001",
            },
            json={
                "message": {
                    "text": "분기 테스트 답변을 작성해 주세요.",
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
        _wait_for_terminal(client, started.json()["run"]["runId"])

        source_turns = client.get(
            f"/api/conversations/{conversation['id']}/turn-sets",
            params={"limit_turn_sets": 3},
        ).json()["turnSets"]
        source_messages = [
            message for turn in source_turns for message in turn["messages"]
        ]
        anchor = next(
            message for message in source_messages if message["role"] == "assistant"
        )

        content_search = client.get(
            "/api/conversations/content-search",
            params={"q": "분기   테스트", "project_id": project_id},
        )
        assert content_search.status_code == 200, content_search.text
        assert content_search.json()["queryTokens"] == ["분기", "테스트"]
        assert content_search.json()["items"][0]["id"] == conversation["id"]
        assert (
            "분기 테스트" in content_search.json()["items"][0]["matches"][0]["snippet"]
        )

        branched = client.post(
            f"/api/conversations/{conversation['id']}/branch",
            headers={"X-CSRF-Token": csrf},
            json={"anchorMessageId": anchor["id"], "title": "검토용 분기"},
        )
        assert branched.status_code == 201, branched.text
        branch = branched.json()
        assert branch["title"] == "검토용 분기"
        assert branch["parentConversationId"] == conversation["id"]
        assert branch["branchMessageId"] == anchor["id"]

        branch_turns = client.get(
            f"/api/conversations/{branch['id']}/turn-sets",
            params={"limit_turn_sets": 3},
        )
        assert branch_turns.status_code == 200, branch_turns.text
        cloned_messages = [
            message
            for turn in branch_turns.json()["turnSets"]
            for message in turn["messages"]
        ]
        assert [message["text"] for message in cloned_messages] == [
            message["text"] for message in source_messages
        ]
        assert all(message["runId"] is None for message in cloned_messages)

        json_export = client.get(
            f"/api/conversations/{branch['id']}/export",
            params={"format": "json", "include_artifacts": True},
        )
        assert json_export.status_code == 200, json_export.text
        assert json_export.json()["schemaVersion"] == "lumina.conversation-export.v1"
        assert (
            json_export.json()["conversation"]["parentConversationId"]
            == conversation["id"]
        )
        assert [item["text"] for item in json_export.json()["messages"]] == [
            message["text"] for message in source_messages
        ]
        assert (
            "attachment; filename*=UTF-8''"
            in json_export.headers["content-disposition"]
        )

        markdown = client.get(
            f"/api/conversations/{branch['id']}/export",
            params={"format": "markdown"},
        )
        assert markdown.status_code == 200, markdown.text
        assert markdown.text.startswith("# 검토용 분기")
        assert "## 사용자" in markdown.text
        assert "## Lumina" in markdown.text

        created_user = client.post(
            "/api/admin/users",
            headers={"X-CSRF-Token": csrf},
            json={
                "loginName": "branch-reader",
                "loginDomain": "posco.com",
                "password": "branch-password",
                "role": "user",
                "status": "active",
                "mustChangePassword": False,
            },
        )
        assert created_user.status_code == 201, created_user.text
        other_client = TestClient(app)
        try:
            other_csrf = _login(
                other_client, login_name="branch-reader", password="branch-password"
            )
            denied_export = other_client.get(
                f"/api/conversations/{branch['id']}/export"
            )
            assert denied_export.status_code == 404
            isolated_search = other_client.get(
                "/api/conversations/content-search", params={"q": "분기 테스트"}
            )
            assert isolated_search.status_code == 200
            assert isolated_search.json()["items"] == []
            denied_branch = other_client.post(
                f"/api/conversations/{conversation['id']}/branch",
                headers={"X-CSRF-Token": other_csrf},
                json={"anchorMessageId": anchor["id"]},
            )
            assert denied_branch.status_code == 404
        finally:
            other_client.close()
