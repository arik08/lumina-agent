from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.agent.executor import LocalRunExecutor
from lumina.api.schemas import RunCreate, RunMessageInput
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Attachment, Run, User
from lumina.runs.approvals import classify_tool_risk
from lumina.runs.service import create_run
from lumina.tools.source_documents import (
    SOURCE_DOCUMENT_TOOL_SCHEMAS,
    attachment_source_document_id,
    execute_source_document_tool,
    message_source_document_id,
    source_document_threshold_tokens,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'source-documents.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"loginName": "admin", "loginDomain": "posco.com", "password": "1"},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def _large_document() -> str:
    return "\n".join(
        (
            f"{index:05d}. 조직업무분장 원문입니다. 부서별 임무와 정원, 현안, 개편 영향을 검토합니다."
            + (" TARGET-4321 핵심 근거" if index == 4_321 else "")
        )
        for index in range(1, 12_001)
    )


def test_source_document_tool_schema_and_dynamic_threshold() -> None:
    assert [item["function"]["name"] for item in SOURCE_DOCUMENT_TOOL_SCHEMAS] == [
        "search_source_document",
        "read_source_document",
    ]
    assert source_document_threshold_tokens(None) == 20_000
    assert source_document_threshold_tokens(16_000) == 4_000
    assert source_document_threshold_tokens(128_000) == 25_600
    assert source_document_threshold_tokens(1_050_000) == 80_000
    for name in ("search_source_document", "read_source_document"):
        assert classify_tool_risk(name, approval_mode="on_risk").effect == "read_only"


def test_large_attachment_uses_recoverable_manifest_and_line_tools(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    executor = LocalRunExecutor(settings)
    long_text = _large_document()
    assert len(long_text) > 500_000

    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "large source"},
        ).json()
        upload = client.post(
            f"/api/conversations/{conversation['id']}/attachments",
            headers=headers,
            files={
                "file": (
                    "organization.txt",
                    long_text.encode("utf-8"),
                    "text/plain",
                )
            },
        )
        assert upload.status_code == 201, upload.text
        attachment_id = upload.json()["id"]

        other_conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "other source"},
        ).json()
        other_upload = client.post(
            f"/api/conversations/{other_conversation['id']}/attachments",
            headers=headers,
            files={"file": ("private.txt", b"private", "text/plain")},
        )
        assert other_upload.status_code == 201

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            attachment = db.get(Attachment, attachment_id)
            assert user is not None and attachment is not None
            run, _message, created = create_run(
                db,
                user=user,
                conversation_id=conversation["id"],
                payload=RunCreate(
                    message=RunMessageInput(
                        text="조직 개편안을 검토해 주세요.",
                        attachment_ids=[attachment_id],
                    )
                ),
                idempotency_key="large-source-document-run",
            )
            db.commit()
            assert created is True
            run_id = run.id
            document_id = attachment_source_document_id(attachment)
            assert attachment.metadata_json.get("truncated") is False

        prepared = executor._message_with_context(
            "조직 개편안을 검토해 주세요.",
            attachment_ids=[attachment_id],
            prompt_references=[],
            extensions=[],
            context_window=128_000,
        )
        assert "<source-document-manifest>" in prepared
        assert document_id in prepared
        assert "TARGET-4321" not in prepared
        assert len(prepared) < 5_000

        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            searched = execute_source_document_tool(
                db,
                executor.file_storage,
                executor.storage,
                run=run,
                name="search_source_document",
                arguments={
                    "document_id": document_id,
                    "query": "TARGET-4321",
                    "limit": 8,
                },
            )
            assert searched["matches"]
            assert searched["untrustedExternalContent"] is True
            match = searched["matches"][0]
            assert match["startLine"] <= 4_321 <= match["endLine"]

            read = execute_source_document_tool(
                db,
                executor.file_storage,
                executor.storage,
                run=run,
                name="read_source_document",
                arguments={
                    "document_id": document_id,
                    "start_line": 4_320,
                    "limit": 3,
                },
            )
            assert "4321|04321." in read["content"]
            assert "TARGET-4321" in read["content"]
            assert read["nextStartLine"] == 4_323
            assert read["untrustedExternalContent"] is True

            dispatched = asyncio.run(
                executor._execute_tool(
                    run_id,
                    {
                        "id": "source-document-read-dispatch",
                        "name": "read_source_document",
                        "arguments": json.dumps(
                            {
                                "document_id": document_id,
                                "start_line": 4_321,
                                "limit": 1,
                            }
                        ),
                    },
                    "원문 근거를 확인해 주세요.",
                )
            )
            assert "TARGET-4321" in dispatched["content"]

            other_attachment = db.get(Attachment, other_upload.json()["id"])
            assert other_attachment is not None
            with pytest.raises(ValueError, match="unavailable"):
                execute_source_document_tool(
                    db,
                    executor.file_storage,
                    executor.storage,
                    run=run,
                    name="read_source_document",
                    arguments={
                        "document_id": attachment_source_document_id(other_attachment),
                        "start_line": 1,
                        "limit": 10,
                    },
                )


def test_small_attachment_remains_inline(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    executor = LocalRunExecutor(settings)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "small source"},
        ).json()
        upload = client.post(
            f"/api/conversations/{conversation['id']}/attachments",
            headers=headers,
            files={"file": ("small.txt", "작은 문서 원문".encode(), "text/plain")},
        )
        assert upload.status_code == 201

        prepared = executor._message_with_context(
            "확인해 주세요.",
            attachment_ids=[upload.json()["id"]],
            prompt_references=[],
            extensions=[],
            context_window=128_000,
        )
        assert "작은 문서 원문" in prepared
        assert "<source-document-manifest>" not in prepared


def test_oversized_pasted_user_document_is_recoverable_from_message(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    executor = LocalRunExecutor(settings)
    source = _large_document()
    user_text = f"{source}\n\n이 원문에서 TARGET-4321의 의미를 검토해 주세요."

    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "pasted source"},
        ).json()
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert user is not None
            run, message, created = create_run(
                db,
                user=user,
                conversation_id=conversation["id"],
                payload=RunCreate(message=RunMessageInput(text=user_text)),
                idempotency_key="pasted-source-document-run",
            )
            db.commit()
            assert created is True
            run_id = run.id
            message_id = message.id
            assert run.snapshot_json["user_message_id"] == message_id

        document_id = message_source_document_id(message_id, user_text)
        prepared = executor._message_with_context(
            user_text,
            attachment_ids=[],
            prompt_references=[],
            extensions=[],
            context_window=128_000,
            user_message_id=message_id,
        )
        assert document_id in prepared
        assert "User request retained outside the stored source" in prepared
        assert "이 원문에서 TARGET-4321의 의미를 검토해 주세요." in prepared
        assert "04321. 조직업무분장 원문" not in prepared
        assert len(prepared) < 5_000
        provider_messages = executor._conversation_messages(
            run_id,
            prepared,
            tool_schemas=SOURCE_DOCUMENT_TOOL_SCHEMAS,
        )
        provider_text = "\n".join(item.content or "" for item in provider_messages)
        assert document_id in provider_text
        assert "04321. 조직업무분장 원문" not in provider_text

        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            read = execute_source_document_tool(
                db,
                executor.file_storage,
                executor.storage,
                run=run,
                name="read_source_document",
                arguments={
                    "document_id": document_id,
                    "start_line": 4_321,
                    "limit": 1,
                },
            )
            assert "TARGET-4321" in read["content"]
