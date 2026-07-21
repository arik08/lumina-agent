from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import (
    Conversation,
    KnowledgeDocument,
    KnowledgeDocumentTag,
    KnowledgeSpace,
    KnowledgeTag,
    KnowledgeTagAlias,
    Project,
    Run,
    ToolExecution,
    User,
)
from lumina.tools.knowledge import (
    MIN_KNOWLEDGE_RELEVANCE_SCORE,
    build_project_knowledge_retrieval_snapshot,
    execute_knowledge_tool,
    knowledge_retrieval_contract,
    knowledge_source_metadata,
    knowledge_tool_schemas,
)


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"loginName": "admin", "loginDomain": "posco.com", "password": "1"},
    )
    assert response.status_code == 200, response.text


def _snapshot(mode: str) -> dict[str, object]:
    return {
        "contractVersion": "knowledge-tool-retrieval-v1",
        "spaces": [{"id": "space-1", "useMode": mode, "settingsRevision": 1}],
    }


def test_knowledge_use_modes_control_the_tool_surface() -> None:
    assert knowledge_tool_schemas(_snapshot("off"), "지식 그래프에서 찾아줘") == ()
    assert knowledge_tool_schemas(_snapshot("explicit"), "일반적인 질문") == ()
    assert len(knowledge_tool_schemas(_snapshot("explicit"), "위키에서 찾아줘")) == 2
    assert len(knowledge_tool_schemas(_snapshot("auto"), "일반적인 질문")) == 2
    assert len(knowledge_tool_schemas(_snapshot("deep"), "문서를 비교해줘")) == 3
    assert knowledge_retrieval_contract(_snapshot("explicit"), "일반적인 질문") is None


def test_knowledge_tools_search_read_follow_and_preserve_evidence(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'knowledge-tools.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        _login(client)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_name == "admin"))
            project = db.scalar(select(Project).where(Project.is_default.is_(True)))
            assert user is not None
            assert project is not None
            space = KnowledgeSpace(
                organization_id=user.organization_id,
                owner_user_id=user.id,
                name="선택 검색 지식",
                use_mode="deep",
            )
            conversation = Conversation(
                organization_id=user.organization_id,
                project_id=project.id,
                owner_user_id=user.id,
                title="지식 검색",
            )
            db.add_all((space, conversation))
            db.flush()

            tag = KnowledgeTag(
                space_id=space.id,
                canonical_name="페라이트",
                normalized_name="페라이트",
                definition="철강 소재 조직",
            )
            db.add(tag)
            db.flush()
            db.add(
                KnowledgeTagAlias(
                    tag_id=tag.id,
                    normalized_alias="ferrite",
                    alias="ferrite",
                )
            )
            citations = [
                {
                    "sourceId": "source:paper-1",
                    "title": "원본 연구",
                    "url": "https://example.com/paper",
                }
            ]
            bodies = (
                "열연강 페라이트 조직은 냉각 조건에 따라 강도가 달라집니다.",
                "페라이트 결정립 크기와 인성의 관계를 비교한 후속 분석입니다.",
                "고객 지원 운영 절차와 담당자 연락 체계입니다.",
            )
            documents = [
                KnowledgeDocument(
                    space_id=space.id,
                    project_id=project.id,
                    owner_user_id=user.id,
                    title=title,
                    body=body,
                    researched_at=datetime(2026, 7, 21, tzinfo=UTC),
                    citations_json=citations if index == 0 else [],
                    content_digest=sha256(body.encode("utf-8")).hexdigest(),
                    status="active",
                )
                for index, (title, body) in enumerate(
                    zip(("소재 분석", "후속 분석", "운영 안내"), bodies, strict=True)
                )
            ]
            db.add_all(documents)
            db.flush()
            db.add_all(
                KnowledgeDocumentTag(document_id=document.id, tag_id=tag.id)
                for document in documents[:2]
            )
            db.flush()

            retrieval_snapshot = build_project_knowledge_retrieval_snapshot(
                db,
                project_id=project.id,
                owner_user_id=user.id,
            )
            assert retrieval_snapshot is not None
            assert all(body not in str(retrieval_snapshot) for body in bodies)
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
                    "knowledge_retrieval": retrieval_snapshot,
                    "user_message_text": "프로젝트 지식에서 ferrite를 비교해줘",
                },
            )
            db.add(run)
            db.flush()

            search_result = execute_knowledge_tool(
                db,
                run=run,
                user=user,
                name="search_knowledge",
                arguments={"query": "ferrite", "result_limit": 5},
            )
            assert search_result["returned"] == 2
            assert search_result["vectorAvailable"] is False
            assert search_result["retrievalMethods"] == ["bm25", "canonical_tags"]
            assert all(
                item["selectionScore"] >= MIN_KNOWLEDGE_RELEVANCE_SCORE
                for item in search_result["results"]
            )
            assert all(item["matchedTags"] == ["페라이트"] for item in search_result["results"])

            miss = execute_knowledge_tool(
                db,
                run=run,
                user=user,
                name="search_knowledge",
                arguments={"query": "천문 관측 위성"},
            )
            assert miss["results"] == []
            assert miss["reason"] == "no_lexical_or_tag_match"

            selected = search_result["results"][0]
            db.add(
                ToolExecution(
                    run_id=run.id,
                    tool_call_id="search-1",
                    tool_name="search_knowledge",
                    status="completed",
                    result_json=search_result,
                )
            )
            db.flush()
            read_result = execute_knowledge_tool(
                db,
                run=run,
                user=user,
                name="read_knowledge_document",
                arguments={
                    "document_id": selected["documentId"],
                    "passage": selected["passage"],
                },
            )
            assert read_result["selectionScore"] == selected["selectionScore"]
            assert read_result["passage"]["text"]
            assert read_result["source"]["evidenceKind"] == "knowledge_document"
            assert f"[source:{read_result['sourceId']}]" in read_result["instruction"]

            followed = execute_knowledge_tool(
                db,
                run=run,
                user=user,
                name="follow_knowledge_links",
                arguments={"document_id": selected["documentId"]},
            )
            assert followed["returned"] == 1
            assert followed["links"][0]["sharedTags"] == ["페라이트"]

            db.add(
                ToolExecution(
                    run_id=run.id,
                    tool_call_id="read-1",
                    tool_name="read_knowledge_document",
                    status="completed",
                    result_json=read_result,
                )
            )
            db.flush()
            metadata = knowledge_source_metadata(db, run.id)
            assert metadata["sources"][0]["selectionScore"] == selected["selectionScore"]
            assert metadata["knowledgeSelections"][0]["passages"] == [
                read_result["passage"]
            ]
            assert metadata["knowledgeSelections"][0]["originalCitations"] == read_result[
                "originalCitations"
            ]
