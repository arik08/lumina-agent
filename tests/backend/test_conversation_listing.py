from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, select

from lumina.api.errors import ApiProblem
from lumina.config import Settings
from lumina.conversations.service import (
    conversation_summaries,
    list_auto_delete_candidates,
    list_conversations,
    update_conversation,
)
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Conversation, Message, ToolExecution, User, utc_now


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
        assert (
            next(
                item
                for item in persisted.json()["items"]
                if item["id"] == created[1]["id"]
            )["isLiked"]
            is True
        )

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

        invalid_header = client.patch(
            f"/api/conversations/{conversation['id']}",
            headers={**headers, "If-Match": '"0"'},
            json={
                "isFavorite": True,
                "expectedRevision": conversation["revision"],
            },
        )
        assert invalid_header.status_code == 400
        assert invalid_header.json()["code"] == "invalid_revision"

        conversations = client.get(
            "/api/conversations",
            params={"project_id": project["id"]},
        ).json()["items"]
        unchanged_conversation = next(
            item for item in conversations if item["id"] == conversation["id"]
        )
        assert unchanged_conversation["revision"] == conversation["revision"]


def test_content_search_keeps_substring_and_short_token_semantics_with_fts(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'content-search.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation_id = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "unrelated title"},
        ).json()["id"]
        with SessionLocal() as db:
            conversation = db.get(Conversation, conversation_id)
            assert conversation is not None
            db.add(
                Message(
                    conversation_id=conversation.id,
                    author_user_id=conversation.owner_user_id,
                    role="user",
                    status="completed",
                    canonical_text="prefixNeedleSuffix 가나다검색마침",
                    turn_index=1,
                    metadata_json={},
                )
            )
            db.commit()

        substring = client.get(
            "/api/conversations/content-search",
            params={"q": "needles", "project_id": project_id},
        )
        assert substring.status_code == 200, substring.text
        assert [item["id"] for item in substring.json()["items"]] == [conversation_id]
        assert substring.json()["items"][0]["matches"]

        korean = client.get(
            "/api/conversations/content-search",
            params={"q": "나다검", "project_id": project_id},
        )
        assert [item["id"] for item in korean.json()["items"]] == [conversation_id]

        short_token = client.get(
            "/api/conversations/content-search",
            params={"q": "ee", "project_id": project_id},
        )
        assert [item["id"] for item in short_token.json()["items"]] == [conversation_id]


def test_conversation_list_summaries_use_constant_query_count(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'bulk-summary.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        for index in range(30):
            created = client.post(
                "/api/conversations",
                headers={"X-CSRF-Token": csrf},
                json={"projectId": project_id, "title": f"bulk {index:02d}"},
            )
            assert created.status_code == 201

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert user is not None
            bind = db.get_bind()
            statement_count = 0

            def count_statement(*_args: object) -> None:
                nonlocal statement_count
                statement_count += 1

            event.listen(bind, "before_cursor_execute", count_statement)
            try:
                conversations, cursor = list_conversations(db, user, limit=30)
                summaries = conversation_summaries(db, conversations)
            finally:
                event.remove(bind, "before_cursor_execute", count_statement)

        assert cursor is None
        assert len(conversations) == 30
        assert len(summaries) == 30
        assert statement_count == 2


def test_conversation_revision_compare_and_swap_rejects_stale_session(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'conversation-cas.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation_response = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "CAS base"},
        )
        assert conversation_response.status_code == 201, conversation_response.text
        conversation_id = conversation_response.json()["id"]

        with SessionLocal() as first_db, SessionLocal() as stale_db:
            first_user = first_db.scalar(
                select(User).where(User.login_id == "admin@posco.com")
            )
            stale_user = stale_db.scalar(
                select(User).where(User.login_id == "admin@posco.com")
            )
            stale_conversation = stale_db.get(Conversation, conversation_id)
            assert first_user is not None and stale_user is not None
            assert stale_conversation is not None
            assert stale_conversation.revision == 1

            updated = update_conversation(
                first_db,
                first_user,
                conversation_id,
                expected_revision=1,
                title="CAS winner",
            )
            first_db.commit()
            assert updated.revision == 2

            with pytest.raises(ApiProblem) as conflict:
                update_conversation(
                    stale_db,
                    stale_user,
                    conversation_id,
                    expected_revision=1,
                    is_favorite=True,
                )
            assert conflict.value.code == "revision_conflict"
            assert conflict.value.details == {"currentRevision": 2}

        persisted = client.get(
            "/api/conversations",
            params={"project_id": project_id},
        ).json()["items"][0]
        assert persisted["title"] == "CAS winner"
        assert persisted["isFavorite"] is False
        assert persisted["revision"] == "2"


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
        assert latest["totalQuestionCount"] == 5

        older = client.get(
            f"/api/conversations/{conversation_id}/turn-sets",
            params={
                "limit_turn_sets": 2,
                "before_cursor": latest["previousCursor"],
            },
        ).json()
        assert len(older["turnSets"]) == 2
        assert older["totalQuestionCount"] == 5
        assert {item["id"] for item in latest["turnSets"]}.isdisjoint(
            {item["id"] for item in older["turnSets"]}
        )


def test_turn_set_cursor_reaches_messages_older_than_legacy_limit(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'long-turns.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation_id = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "long cursor test"},
        ).json()["id"]

        with SessionLocal() as db:
            conversation = db.get(Conversation, conversation_id)
            assert conversation is not None
            created_at = utc_now()
            for index in range(205):
                branch_source_run_id = f"seed-run-{index:04d}"
                for role_index, role in enumerate(("user", "assistant")):
                    db.add(
                        Message(
                            conversation_id=conversation_id,
                            author_user_id=conversation.owner_user_id
                            if role == "user"
                            else None,
                            role=role,
                            canonical_text=f"turn {index} {role}",
                            turn_index=role_index,
                            metadata_json={"branchSourceRunId": branch_source_run_id},
                            created_at=created_at
                            + timedelta(microseconds=index * 2 + role_index),
                        )
                    )
            db.commit()

        collected_ids: list[str] = []
        cursor: str | None = None
        while True:
            params: dict[str, str | int] = {"limit_turn_sets": 20}
            if cursor is not None:
                params["before_cursor"] = cursor
            page = client.get(
                f"/api/conversations/{conversation_id}/turn-sets",
                params=params,
            )
            assert page.status_code == 200, page.text
            payload = page.json()
            collected_ids.extend(item["id"] for item in payload["turnSets"])
            if not payload["hasMoreBefore"]:
                break
            cursor = payload["previousCursor"]
            assert cursor is not None

        assert len(collected_ids) == 205
        assert len(set(collected_ids)) == 205


def test_web_source_content_pages_stored_text_with_delivery_counts(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'source-content.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation_id = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "source body"},
        ).json()["id"]
        started = client.post(
            f"/api/conversations/{conversation_id}/runs",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "source-body-run"},
            json={
                "message": {
                    "text": "source",
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
        run_id = started.json()["run"]["runId"]
        _wait_for_terminal(client, run_id)
        body = "0123456789" * 1_200
        with SessionLocal() as db:
            db.add(
                ToolExecution(
                    run_id=run_id,
                    tool_call_id="fetch-source-body",
                    tool_name="web_fetch",
                    validated_input_json={"url": "https://example.com/source"},
                    status="completed",
                    result_json={
                        "source": {"sourceId": "src-body"},
                        "text": body,
                        "providerContextIncludedChars": 8_000,
                    },
                )
            )
            db.commit()

        first = client.get(
            f"/api/conversations/{conversation_id}/runs/{run_id}/sources/src-body/content",
            params={"offset": 0, "limit": 4_000},
        )
        assert first.status_code == 200, first.text
        assert first.json() == {
            "sourceId": "src-body",
            "content": body[:4_000],
            "offset": 0,
            "nextOffset": 4_000,
            "hasMore": True,
            "totalChars": len(body),
            "llmTextChars": 8_000,
            "llmTextCharsEstimated": False,
        }
        last = client.get(
            f"/api/conversations/{conversation_id}/runs/{run_id}/sources/src-body/content",
            params={"offset": 8_000, "limit": 4_000},
        ).json()
        assert last["content"] == body[8_000:]
        assert last["hasMore"] is False


def _wait_for_terminal(client: TestClient, run_id: str) -> None:
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        status = client.get(f"/api/runs/{run_id}/snapshot").json()["status"]
        if status in {"completed", "failed", "cancelled", "interrupted"}:
            assert status == "completed"
            return
        time.sleep(0.02)
    raise AssertionError("Run did not finish")
