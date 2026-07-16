from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import time

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.conversations.service import list_auto_delete_candidates
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import utc_now


def test_cursor_preserves_favorite_order_and_search_is_whitespace_tolerant(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created: list[dict[str, object]] = []
        for index, title in enumerate(
            [
                "Energy    Cost  Review",
                "Line bottleneck",
                "Safety checklist",
                "Maintenance report",
                "Inventory review",
            ]
        ):
            response = client.post(
                "/api/conversations",
                headers={"X-CSRF-Token": csrf},
                json={"projectId": project_id, "title": title},
            )
            assert response.status_code == 201
            item = response.json()
            created.append(item)
            if index in {0, 3}:
                favorite = client.patch(
                    f"/api/conversations/{item['id']}",
                    headers={
                        "X-CSRF-Token": csrf,
                        "If-Match": f'"{item["revision"]}"',
                    },
                    json={"isFavorite": True},
                )
                assert favorite.status_code == 200

        collected: list[dict[str, object]] = []
        cursor: str | None = None
        while True:
            response = client.get(
                "/api/conversations",
                params={
                    "project_id": project_id,
                    "limit": 2,
                    **({"cursor": cursor} if cursor else {}),
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            collected.extend(payload["items"])
            cursor = payload["nextCursor"]
            if cursor is None:
                break

        assert len(collected) == len(created)
        assert len({item["id"] for item in collected}) == len(created)
        assert [item["isFavorite"] for item in collected] == sorted(
            (item["isFavorite"] for item in collected), reverse=True
        )

        liked = client.patch(
            f"/api/conversations/{created[1]['id']}",
            headers={
                "X-CSRF-Token": csrf,
                "If-Match": f'"{created[1]["revision"]}"',
            },
            json={"isLiked": True},
        )
        assert liked.status_code == 200
        assert liked.json()["isLiked"] is True

        persisted = client.get(
            "/api/conversations",
            params={"project_id": project_id, "limit": 10},
        )
        assert next(
            item for item in persisted.json()["items"] if item["id"] == created[1]["id"]
        )["isLiked"] is True

        with SessionLocal() as db:
            candidate_ids = {
                item.id
                for item in list_auto_delete_candidates(
                    db, older_than=utc_now() + timedelta(days=1)
                )
            }
        assert created[1]["id"] not in candidate_ids
        assert created[2]["id"] in candidate_ids

        search = client.get(
            "/api/conversations/search",
            params={"project_id": project_id, "title_query": " energy   review "},
        )
        assert search.status_code == 200
        assert [item["title"] for item in search.json()["items"]] == [
            "Energy    Cost  Review"
        ]


def test_project_and_conversation_patch_reject_noop_payloads(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'noop-patch.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        project = client.get("/api/projects").json()[0]

        for invalid_payload in ({}, {"name": None, "archived": None}):
            rejected_project = client.patch(
                f"/api/projects/{project['id']}",
                headers=headers,
                json=invalid_payload,
            )
            assert rejected_project.status_code == 422, rejected_project.text

        unchanged_project = next(
            item
            for item in client.get("/api/projects").json()
            if item["id"] == project["id"]
        )
        assert unchanged_project["updatedAt"] == project["updatedAt"]

        conversation_response = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project["id"], "title": "No-op patch guard"},
        )
        assert conversation_response.status_code == 201, conversation_response.text
        conversation = conversation_response.json()

        for invalid_payload in (
            {},
            {"expectedRevision": conversation["revision"]},
            {"title": None, "isFavorite": None},
        ):
            rejected_conversation = client.patch(
                f"/api/conversations/{conversation['id']}",
                headers=headers,
                json=invalid_payload,
            )
            assert rejected_conversation.status_code == 422, rejected_conversation.text

        conversations = client.get(
            "/api/conversations",
            params={"project_id": project["id"]},
        ).json()["items"]
        unchanged_conversation = next(
            item for item in conversations if item["id"] == conversation["id"]
        )
        assert unchanged_conversation["revision"] == conversation["revision"]


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1",
        },
    )
    assert response.status_code == 200
    return response.json()["csrfToken"]


def test_turn_set_cursor_pages_backwards_without_overlap(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'turns.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "cursor test"},
        ).json()
        conversation_id = conversation["id"]

        for index in range(5):
            started = client.post(
                f"/api/conversations/{conversation_id}/runs",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": f"turn-page-{index:04d}",
                },
                json={
                    "message": {
                        "text": f"질문 {index}",
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
            assert started.status_code == 202
            _wait_for_terminal(client, started.json()["run"]["runId"])

        latest = client.get(
            f"/api/conversations/{conversation_id}/turn-sets",
            params={"limit_turn_sets": 2},
        ).json()
        assert len(latest["turnSets"]) == 2
        assert latest["hasMoreBefore"] is True

        older = client.get(
            f"/api/conversations/{conversation_id}/turn-sets",
            params={
                "limit_turn_sets": 2,
                "before_cursor": latest["previousCursor"],
            },
        ).json()
        assert len(older["turnSets"]) == 2
        assert {item["id"] for item in latest["turnSets"]}.isdisjoint(
            {item["id"] for item in older["turnSets"]}
        )


def _wait_for_terminal(client: TestClient, run_id: str) -> None:
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        status = client.get(f"/api/runs/{run_id}/snapshot").json()["status"]
        if status in {"completed", "failed", "cancelled", "interrupted"}:
            assert status == "completed"
            return
        time.sleep(0.02)
    raise AssertionError("Run did not finish")
