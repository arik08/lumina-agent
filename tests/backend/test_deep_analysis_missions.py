from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.auth.service import create_user
from lumina.agent.executor import (
    _filter_web_sources_for_policy,
    _source_domain_allowed,
    local_run_executor,
)
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.deep_analysis.calculations import execute_python_calculation
from lumina.deep_analysis.ai_planner import design_initial_workflow
from lumina.deep_analysis.events import emit_event
from lumina.deep_analysis.execution import (
    _output_path,
    _run_profile,
    _run_prompt,
    create_runnable_node_runs,
)
from lumina.deep_analysis.planning import runnable_nodes
from lumina.deep_analysis.models import (
    DeepAnalysisCommand,
    DeepAnalysisEvent,
    DeepAnalysisDecision,
    DeepAnalysisDecisionResponse,
    DeepAnalysisMission,
    DeepAnalysisMissionExport,
    DeepAnalysisWorkflowEdge,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowPattern,
    DeepAnalysisWorkflowRevision,
)
from lumina.deep_analysis.ledger import (
    extract_analysis_ledger,
    persist_analysis_ledger,
)
from lumina.deep_analysis.planning import (
    apply_workflow_decision,
    extract_workflow_decision,
    initial_workflow_plan,
    next_runnable_node,
    plan_edges,
)
from lumina.deep_analysis.quality import evaluate_quality_gate
from lumina.main import create_app
from lumina.models import (
    Message,
    Organization,
    ProjectFile,
    ProjectFileVersion,
    ProjectFolder,
    Run,
    User,
)
from lumina.providers.mock import MockProvider
from lumina.storage import ManagedLocalStorage


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1",
        },
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def test_runnable_nodes_returns_all_dependency_ready_branches_in_sequence_order() -> None:
    nodes = [
        DeepAnalysisWorkflowNode(
            workflow_revision_id="workflow",
            node_key="root",
            node_type="scope",
            title="Root",
            sequence=1,
            position_x=0,
            position_y=0,
            status="completed",
        ),
        DeepAnalysisWorkflowNode(
            workflow_revision_id="workflow",
            node_key="branch-b",
            node_type="research",
            title="Branch B",
            sequence=3,
            position_x=0,
            position_y=0,
            status="planned",
        ),
        DeepAnalysisWorkflowNode(
            workflow_revision_id="workflow",
            node_key="branch-a",
            node_type="research",
            title="Branch A",
            sequence=2,
            position_x=0,
            position_y=0,
            status="ready",
        ),
        DeepAnalysisWorkflowNode(
            workflow_revision_id="workflow",
            node_key="join",
            node_type="synthesis",
            title="Join",
            sequence=4,
            position_x=0,
            position_y=0,
            status="planned",
        ),
    ]
    edges = [
        DeepAnalysisWorkflowEdge(
            workflow_revision_id="workflow",
            source_node_key="root",
            target_node_key="branch-a",
        ),
        DeepAnalysisWorkflowEdge(
            workflow_revision_id="workflow",
            source_node_key="root",
            target_node_key="branch-b",
        ),
        DeepAnalysisWorkflowEdge(
            workflow_revision_id="workflow",
            source_node_key="branch-a",
            target_node_key="join",
        ),
        DeepAnalysisWorkflowEdge(
            workflow_revision_id="workflow",
            source_node_key="branch-b",
            target_node_key="join",
        ),
    ]

    assert [node.node_key for node in runnable_nodes(nodes, edges)] == [
        "branch-a",
        "branch-b",
    ]


def test_parallel_nodes_reserve_disjoint_shares_of_the_remaining_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mission = DeepAnalysisMission(
        title="예산 예약 검증",
        budget_microusd=1_000_000,
        spent_microusd=100_000,
    )
    nodes = [
        DeepAnalysisWorkflowNode(
            workflow_revision_id="workflow",
            node_key="branch-a",
            node_type="research",
            title="Branch A",
            sequence=1,
            position_x=0,
            position_y=0,
            status="ready",
        ),
        DeepAnalysisWorkflowNode(
            workflow_revision_id="workflow",
            node_key="branch-b",
            node_type="research",
            title="Branch B",
            sequence=2,
            position_x=0,
            position_y=0,
            status="ready",
        ),
    ]
    reservations: list[int | None] = []

    def fake_create_node_run(
        _db: object,
        *,
        node: DeepAnalysisWorkflowNode,
        budget_limit_microusd: int | None,
        **_kwargs: object,
    ) -> tuple[SimpleNamespace, bool]:
        reservations.append(budget_limit_microusd)
        return SimpleNamespace(id=node.node_key), True

    monkeypatch.setattr(
        "lumina.deep_analysis.execution.create_node_run",
        fake_create_node_run,
    )

    runs = create_runnable_node_runs(
        object(),  # type: ignore[arg-type]
        user=User(id="budget-user"),
        mission=mission,
        nodes=nodes,
        edges=[],
        settings=_settings(tmp_path),
    )

    assert [run.id for run in runs] == ["branch-a", "branch-b"]
    assert reservations == [450_000, 450_000]
    assert sum(item or 0 for item in reservations) == (
        mission.budget_microusd - mission.spent_microusd
    )


def test_node_output_contracts_keep_handoffs_compact_and_reports_detailed() -> None:
    mission = DeepAnalysisMission(
        title="출력 계약 검증",
        objective="여러 근거를 분석해 최종 보고서를 작성합니다.",
        created_at=datetime(2026, 7, 20, tzinfo=ZoneInfo("Asia/Seoul")),
        execution_settings_json={
            "analysisDepth": "deep",
            "answerLength": "detailed",
            "outputMode": "file",
            "outputFormat": "html",
            "targetOutputTokens": 10_000,
        },
    )
    scope = DeepAnalysisWorkflowNode(
        node_key="N001",
        node_type="scope",
        title="범위 설계",
        purpose="검증 범위를 정의합니다.",
    )
    analysis = DeepAnalysisWorkflowNode(
        node_key="N020",
        node_type="analysis",
        title="원인 분석",
        purpose="핵심 원인을 분석합니다.",
    )
    report = DeepAnalysisWorkflowNode(
        node_key="N040",
        node_type="report",
        title="최종 보고서",
        purpose="최종 결론을 작성합니다.",
    )

    assert _run_profile(mission, scope) == ("deep", "brief", 1_200)
    assert _run_profile(mission, analysis) == ("deep", "standard", 3_500)
    assert _run_profile(mission, report) == ("deep", "detailed", 10_000)

    scope_prompt = _run_prompt(mission, scope, [])
    assert "분석 질문을 검증 가능한 형태로 구체화" in scope_prompt
    assert "최종 보고서가 아니라 다음 Node를 위한 압축 인계물" in scope_prompt
    assert "선행 산출물의 내용을 반복 요약하지" in scope_prompt

    report_prompt = _run_prompt(mission, report, [])
    assert "의사결정자가 바로 사용할 수 있는 최종 보고서" in report_prompt
    assert "하나의 일관된 최종 보고서" in report_prompt
    assert "독립 실행 가능한 HTML 문서" in report_prompt
    assert "Markdown code fence로 감싸지 마십시오" in report_prompt
    assert _output_path(mission, scope).endswith("/N001_범위 설계.md")
    assert _output_path(mission, report).endswith("/N040_최종 보고서.html")

    mission.execution_settings_json["outputFormat"] = "임원용 1페이지 의사결정 메모"
    custom_prompt = _run_prompt(mission, report, [])
    assert "사용자가 지정한 최종 산출물 형태는 '임원용 1페이지 의사결정 메모'" in custom_prompt
    assert "직접 입력한 형태의 원문은 Markdown 파일로 저장" in custom_prompt
    assert _output_path(mission, report).endswith("/N040_최종 보고서.md")


def test_node_output_contract_respects_smaller_target_and_chat_mode() -> None:
    analysis = DeepAnalysisWorkflowNode(
        node_key="N020",
        node_type="analysis",
        title="원인 분석",
        purpose="핵심 원인을 분석합니다.",
    )
    file_mission = DeepAnalysisMission(
        title="작은 출력 목표",
        objective="간결하게 분석합니다.",
        execution_settings_json={
            "outputMode": "file",
            "targetOutputTokens": 1_000,
        },
    )
    chat_mission = DeepAnalysisMission(
        title="채팅 출력",
        objective="간결하게 분석합니다.",
        execution_settings_json={
            "outputMode": "chat",
            "targetOutputTokens": None,
        },
    )

    assert _run_profile(file_mission, analysis) == ("auto", "standard", 1_000)
    assert _run_profile(chat_mission, analysis) == ("auto", "standard", None)


def _create_viewer() -> dict[str, str]:
    with SessionLocal() as db:
        organization_id = db.scalar(
            select(Organization.id).where(Organization.slug == "posco")
        )
        assert organization_id is not None
        user = create_user(
            db,
            login_name="deep-analysis-viewer",
            password="password",
            organization_id=organization_id,
            display_name="Deep Analysis Viewer",
            role="user",
            status="active",
        )
        db.commit()
        return {"id": user.id, "loginId": user.login_id}


def _login_viewer(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "deep-analysis-viewer",
            "loginDomain": "posco.com",
            "password": "password",
        },
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def test_mission_workflow_persists_and_uses_revision_cas(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]

        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "전사 영업원가 변동 원인 분석",
                "objective": "전년 대비 영업원가 변동의 핵심 원인을 정량적으로 설명한다.",
                "autonomyMode": "balanced",
            },
        )
        assert created.status_code == 201, created.text
        mission = created.json()
        assert mission["revision"] == 1
        assert mission["executionAvailable"] is True
        assert mission["spentMicrousd"] == 0
        assert mission["workflow"]["revisionNumber"] == 1
        assert len(mission["workflow"]["nodes"]) == 7
        assert mission["workflow"]["nodes"][0]["nodeType"] == "scope"
        assert len(mission["workflow"]["edges"]) == 7
        assert mission["startMode"] == "ai_fallback"
        assert mission["workflow"]["changeLog"][0]["action"] == "initial"
        assert "정량" in mission["workflow"]["reason"]

        listing = client.get(f"/api/projects/{project_id}/deep-analysis/missions")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [mission["id"]]

        restored = client.get(f"/api/deep-analysis/missions/{mission['id']}")
        assert restored.status_code == 200
        assert (
            restored.json()["workflow"]["graphDigest"]
            == mission["workflow"]["graphDigest"]
        )
        projection = client.get(
            f"/api/deep-analysis/missions/{mission['id']}/projection"
        )
        assert projection.status_code == 200
        projected = projection.json()
        assert projected["missionId"] == mission["id"]
        assert projected["eventCursor"] == mission["eventCursor"]
        assert len(projected["nodes"]) == len(mission["workflow"]["nodes"])
        assert "workflow" not in projected
        assert "sourceManifest" not in projected

        updated = client.patch(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            json={"expectedRevision": 1, "autonomyMode": "guided"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 2
        assert updated.json()["autonomyMode"] == "guided"

        stale = client.patch(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            json={"expectedRevision": 1, "title": "충돌하는 변경"},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "revision_conflict"
        assert stale.json()["details"] == {"currentRevision": 2}


def test_mission_creation_freezes_sources_and_applies_run_output_settings(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": "자료.csv", "changeReason": "심층분석 입력"},
            files={"file": ("자료.csv", "항목,값\nA,1\n".encode(), "text/csv")},
        )
        assert uploaded.status_code == 201, uploaded.text
        source = uploaded.json()
        token = "@자료.csv"
        objective = f"{token}의 값을 근거로 상세 분석한다."
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "설정 반영 분석",
                "objective": objective,
                "analysisDepth": "deep",
                "answerLength": "detailed",
                "outputMode": "file",
                "outputFormat": "html",
                "targetOutputTokens": 20_000,
                "execution": {
                    "providerId": "mock",
                    "modelKey": "mock-agent",
                    "effortId": "low",
                },
                "promptReferences": [{
                    "kind": "file",
                    "referenceId": source["id"],
                    "versionOrDigest": source["contentHash"],
                    "tokenStart": 0,
                    "tokenEnd": len(token),
                }],
            },
        )
        assert created.status_code == 201, created.text
        mission = created.json()
        assert mission["analysisDepth"] == "deep"
        assert mission["answerLength"] == "detailed"
        assert mission["outputMode"] == "file"
        assert mission["outputFormat"] == "html"
        assert mission["targetOutputTokens"] == 20_000
        assert mission["execution"] == {
            "providerId": "mock",
            "modelKey": "mock-agent",
            "effortId": "low",
        }
        assert mission["promptReferences"][0]["versionOrDigest"] == source["contentHash"]
        assert mission["sourceManifest"][0]["projectFileId"] == source["id"]

        updated = client.patch(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            json={
                "expectedRevision": mission["revision"],
                "analysisDepth": "standard",
                "answerLength": "brief",
                "outputMode": "chat",
                "outputFormat": "임원용 1페이지 의사결정 메모",
                "targetOutputTokens": None,
                "execution": {
                    "providerId": "mock",
                    "modelKey": "mock-agent",
                    "effortId": "low",
                },
                "promptReferences": mission["promptReferences"],
            },
        )
        assert updated.status_code == 200, updated.text
        mission = updated.json()
        assert mission["analysisDepth"] == "standard"
        assert mission["answerLength"] == "brief"
        assert mission["outputMode"] == "chat"
        assert mission["outputFormat"] == "임원용 1페이지 의사결정 메모"
        assert mission["targetOutputTokens"] is None
        assert mission["promptReferences"][0]["versionOrDigest"] == source["contentHash"]
        assert mission["sourceManifest"][0]["projectFileId"] == source["id"]

        started = client.post(
            f"/api/deep-analysis/missions/{mission['id']}/start",
            headers=headers,
            json={"expectedRevision": mission["revision"]},
        )
        assert started.status_code == 200, started.text
        run_id = started.json()["workflow"]["nodes"][0]["runId"]
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            assert run.snapshot_json["analysis_depth"] == "standard"
            assert run.snapshot_json["answer_length"] == "brief"
            assert run.snapshot_json["output_mode"] == "chat"
            assert run.snapshot_json["target_output_tokens"] is None
            assert run.provider_id == "mock"
            assert run.model_key == "mock-agent"
            assert run.effort == "low"
            assert run.snapshot_json["prompt_references"][0]["reference_id"] == source["id"]


def test_mission_research_controls_are_frozen_and_future_nodes_receive_guidance(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "연구 제어 검증",
                "objective": "지정 기간의 공식 자료를 분석한다.",
                "researchPeriod": {
                    "startDate": "2024-01-01",
                    "endDate": "2025-12-31",
                },
                "webSourcePolicy": {
                    "mode": "restrict",
                    "domains": ["Example.COM"],
                    "excludedDomains": ["ads.example.net"],
                },
            },
        )
        assert created.status_code == 201, created.text
        mission = created.json()
        assert mission["researchPeriod"] == {
            "startDate": "2024-01-01",
            "endDate": "2025-12-31",
        }
        assert mission["webSourcePolicy"] == {
            "mode": "restrict",
            "domains": ["example.com"],
            "excludedDomains": ["ads.example.net"],
        }

        started = client.post(
            f"/api/deep-analysis/missions/{mission['id']}/start",
            headers=headers,
            json={"expectedRevision": mission["revision"]},
        )
        assert started.status_code == 200, started.text
        running = started.json()
        first_node = next(
            item for item in running["workflow"]["nodes"] if item["status"] == "running"
        )
        assert "2024-01-01 ~ 2025-12-31" in first_node["executionPrompt"]
        assert "웹 출처 모드: restrict" in first_node["executionPrompt"]

        steered = client.post(
            f"/api/deep-analysis/missions/{mission['id']}/steer",
            headers=headers,
            json={
                "expectedRevision": running["revision"],
                "instruction": "향후 Node에서는 공급망 위험을 별도 절로 다뤄 주세요.",
                "promptReferences": [],
            },
        )
        assert steered.status_code == 200, steered.text
        steered_payload = steered.json()
        assert steered_payload["guidanceCount"] == 1
        unchanged_first = next(
            item
            for item in steered_payload["workflow"]["nodes"]
            if item["id"] == first_node["id"]
        )
        assert "공급망 위험" not in unchanged_first["executionPrompt"]

        with SessionLocal() as db:
            stored_mission = db.get(DeepAnalysisMission, mission["id"])
            future_node = db.scalar(
                select(DeepAnalysisWorkflowNode)
                .where(
                    DeepAnalysisWorkflowNode.workflow_revision_id
                    == steered_payload["workflow"]["id"],
                    DeepAnalysisWorkflowNode.status == "planned",
                )
                .order_by(DeepAnalysisWorkflowNode.sequence)
            )
            run = db.get(Run, first_node["runId"])
            assert stored_mission is not None and future_node is not None and run is not None
            assert "공급망 위험" in _run_prompt(stored_mission, future_node, [])
            assert run.snapshot_json["deep_analysis"]["web_source_policy"]["mode"] == "restrict"
            assert run.snapshot_json["deep_analysis"]["guidance_history"] == []


def test_deep_analysis_web_source_policy_filters_search_and_blocks_fetch() -> None:
    policy = {
        "mode": "restrict",
        "domains": ["example.com"],
        "excludedDomains": ["blocked.example.com"],
    }
    assert _source_domain_allowed("docs.example.com", policy) is True
    assert _source_domain_allowed("blocked.example.com", policy) is False
    assert _source_domain_allowed("outside.test", policy) is False
    assert _filter_web_sources_for_policy(
        [
            {"sourceId": "allowed", "normalizedUrl": "https://docs.example.com/a"},
            {"sourceId": "blocked", "normalizedUrl": "https://blocked.example.com/b"},
            {"sourceId": "outside", "normalizedUrl": "https://outside.test/c"},
        ],
        policy,
    ) == [
        {"sourceId": "allowed", "normalizedUrl": "https://docs.example.com/a"}
    ]


def test_mission_research_inspector_and_changed_source_refresh(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": "inputs/base.csv", "changeReason": "초기 자료"},
            files={"file": ("base.csv", b"value\n10\n", "text/csv")},
        )
        assert uploaded.status_code == 201, uploaded.text
        source = uploaded.json()
        token = "@base.csv"
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "자료 갱신 검증",
                "objective": f"{token}의 수치를 분석한다.",
                "promptReferences": [
                    {
                        "kind": "file",
                        "referenceId": source["id"],
                        "versionOrDigest": source["contentHash"],
                        "tokenStart": 0,
                        "tokenEnd": len(token),
                    }
                ],
            },
        ).json()
        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": created["revision"]},
        ).json()
        running_node = next(
            item for item in started["workflow"]["nodes"] if item["status"] == "running"
        )

        with SessionLocal() as db:
            assistant = db.scalar(
                select(Message).where(
                    Message.run_id == running_node["runId"], Message.role == "assistant"
                )
            )
            run = db.get(Run, running_node["runId"])
            if assistant is None and run is not None:
                assistant = Message(
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                    role="assistant",
                    status="completed",
                    canonical_text="",
                    turn_index=1,
                )
                db.add(assistant)
            report = db.scalar(
                select(DeepAnalysisWorkflowNode).where(
                    DeepAnalysisWorkflowNode.workflow_revision_id
                    == started["workflow"]["id"],
                    DeepAnalysisWorkflowNode.node_type == "report",
                )
            )
            project_file = db.get(ProjectFile, source["id"])
            assert assistant is not None and report is not None and project_file is not None
            assistant.status = "completed"
            assistant.canonical_text = "공식 통계는 10%입니다.[1]"
            assistant.metadata_json = {
                "sources": [
                    {
                        "sourceId": "official-1",
                        "title": "Official",
                        "normalizedUrl": "https://official.example/report",
                        "citationStatus": "cited",
                    }
                ],
                "citations": [{"sourceId": "official-1", "marker": "[1]"}],
                "researchVerification": "verified",
            }
            report.output_markdown = (
                "# 결과\ninputs/base.csv 기준 값은 10%입니다.[1]\n"
                "추정 성장률은 25%입니다.\n"
            )
            assert run is not None
            current_report_run = Run(
                organization_id=run.organization_id,
                project_id=run.project_id,
                conversation_id=run.conversation_id,
                user_id=run.user_id,
                status="completed",
                provider_id=run.provider_id,
                model_key=run.model_key,
                runtime_model_id=run.runtime_model_id,
                model_display_name=run.model_display_name,
                effort=run.effort,
                snapshot_json={},
                usage_json={},
                idempotency_key="report-diff-current",
            )
            db.add(current_report_run)
            db.flush()
            db.add(
                Message(
                    conversation_id=run.conversation_id,
                    run_id=current_report_run.id,
                    role="assistant",
                    status="completed",
                    canonical_text="# 결과\n기준 값은 12%입니다.[1]\n새 결론입니다.\n",
                    turn_index=2,
                )
            )
            report.run_history_json = [
                {"attempt": 1, "runId": run.id, "status": "completed"}
            ]
            report.run_id = current_report_run.id
            current_version = db.scalar(
                select(ProjectFileVersion).where(
                    ProjectFileVersion.project_file_id == project_file.id,
                    ProjectFileVersion.version_number == 1,
                )
            )
            assert current_version is not None
            next_version = ProjectFileVersion(
                project_file_id=project_file.id,
                version_number=2,
                storage_backend=current_version.storage_backend,
                storage_key=f"{current_version.storage_key}.v2",
                content_hash="b" * 64,
                size_bytes=12,
                mime_type="text/csv",
                original_filename="base.csv",
                parent_version_id=current_version.id,
                extraction_status="ready",
                metadata_json={},
                created_by_user_id=current_version.created_by_user_id,
            )
            db.add(next_version)
            project_file.current_version_number = 2
            mission = db.get(DeepAnalysisMission, created["id"])
            assert mission is not None
            mission.status = "completed"
            for node in db.scalars(
                select(DeepAnalysisWorkflowNode).where(
                    DeepAnalysisWorkflowNode.workflow_revision_id
                    == started["workflow"]["id"]
                )
            ):
                node.status = "completed"
            db.commit()

        inspector = client.get(
            f"/api/deep-analysis/missions/{created['id']}/research-inspector"
        )
        assert inspector.status_code == 200, inspector.text
        inspected = inspector.json()
        assert inspected["summary"]["sourceCount"] == 2
        assert inspected["summary"]["citedSourceCount"] == 2
        assert inspected["summary"]["citationReviewNeededCount"] == 1
        assert inspected["citationReviewCandidates"][0]["text"] == "추정 성장률은 25%입니다."

        preview = client.get(
            f"/api/deep-analysis/missions/{created['id']}/refresh-preview"
        )
        assert preview.status_code == 200, preview.text
        preview_payload = preview.json()
        assert preview_payload["hasChanges"] is True
        assert preview_payload["canRefresh"] is True
        assert preview_payload["changedSources"][0]["fromVersion"] == 1
        assert preview_payload["changedSources"][0]["toVersion"] == 2
        assert len(preview_payload["affectedNodeKeys"]) == len(
            started["workflow"]["nodes"]
        )
        assert preview_payload["reportDiff"]["available"] is True
        assert preview_payload["reportDiff"]["addedLines"] == 3
        assert preview_payload["reportDiff"]["removedLines"] == 1

        refreshed = client.post(
            f"/api/deep-analysis/missions/{created['id']}/refresh",
            headers=headers,
            json={"expectedRevision": started["revision"]},
        )
        assert refreshed.status_code == 200, refreshed.text
        refreshed_payload = refreshed.json()
        assert refreshed_payload["status"] == "running"
        assert refreshed_payload["sourceManifest"][0]["version"] == 2
        assert refreshed_payload["promptReferences"][0]["versionOrDigest"] == "b" * 64
        assert sum(
            item["status"] == "running"
            for item in refreshed_payload["workflow"]["nodes"]
        ) == 1


def test_mission_without_references_does_not_include_project_files(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        unrelated = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": "포스코_간단_소개.md", "changeReason": "무관 자료"},
            files={
                "file": (
                    "포스코_간단_소개.md",
                    "# 포스코 간단 소개\n".encode(),
                    "text/markdown",
                )
            },
        )
        assert unrelated.status_code == 201, unrelated.text

        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "오라클 주가 장기하락 원인 분석",
                "objective": "오라클 주가 하락 원인을 검토합니다.",
            },
        )
        assert created.status_code == 201, created.text
        mission = created.json()
        assert mission["promptReferences"] == []
        assert mission["sourceManifest"] == []

        started = client.post(
            f"/api/deep-analysis/missions/{mission['id']}/start",
            headers=headers,
            json={"expectedRevision": mission["revision"]},
        )
        assert started.status_code == 200, started.text
        payload = started.json()
        assert payload["sourceManifest"] == []
        node = payload["workflow"]["nodes"][0]
        assert "포스코_간단_소개.md" not in node["executionPrompt"]
        assert unrelated.json()["id"] not in node["executionPrompt"]
        assert "다음 Node를 위한 압축 인계물" in node["executionPrompt"]
        with SessionLocal() as db:
            run = db.get(Run, node["runId"])
            assert run is not None
            assert run.snapshot_json["project_file_manifest"] == []
            assert run.snapshot_json["answer_length"] == "brief"
            assert run.snapshot_json["target_output_tokens"] == 1_200


def test_mission_sidebar_preferences_rename_and_project_move_persist(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        source_project_id = client.get("/api/projects").json()[0]["id"]
        destination = client.post(
            "/api/projects",
            headers=headers,
            json={"name": "분석 이동 대상", "description": ""},
        )
        assert destination.status_code == 201, destination.text
        destination_project_id = destination.json()["id"]
        created = client.post(
            f"/api/projects/{source_project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "이동 전 분석", "objective": "사이드바 동작을 검증한다."},
        ).json()

        updated = client.patch(
            f"/api/deep-analysis/missions/{created['id']}",
            headers=headers,
            json={
                "expectedRevision": created["revision"],
                "title": "이동 후 분석",
                "isFavorite": True,
                "isLiked": True,
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["title"] == "이동 후 분석"
        assert updated.json()["isFavorite"] is True
        assert updated.json()["isLiked"] is True

        moved = client.post(
            f"/api/deep-analysis/missions/{created['id']}/move",
            headers=headers,
            json={"projectId": destination_project_id},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["projectId"] == destination_project_id
        destination_items = client.get(
            f"/api/projects/{destination_project_id}/deep-analysis/missions"
        ).json()
        assert [(item["title"], item["isFavorite"], item["isLiked"]) for item in destination_items] == [
            ("이동 후 분석", True, True)
        ]


def test_draft_question_change_rebuilds_the_initial_workflow(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "열린 문제 진단", "objective": "현상을 분석해 설명한다."},
        ).json()
        assert len(created["workflow"]["nodes"]) == 6

        updated = client.patch(
            f"/api/deep-analysis/missions/{created['id']}",
            headers=headers,
            json={
                "expectedRevision": 1,
                "objective": "신규 시스템 도입 전략과 투자 리스크를 비교해 의사결정한다.",
            },
        )
        assert updated.status_code == 200, updated.text
        detail = updated.json()
        assert detail["workflow"]["revisionNumber"] == 2
        assert len(detail["workflow"]["nodes"]) == 7
        assert detail["workflow"]["nodes"][0]["title"] == "의사결정 문제 정의"
        assert detail["workflow"]["changeLog"][-1]["action"] == "question_updated"
        assert "의사결정형" in detail["workflow"]["reason"]


@pytest.mark.skip(reason="legacy missions are deleted by migration 0055")
def test_legacy_unstarted_workflow_is_upgraded_once_on_restore(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "기존 원가 분석",
                "objective": "원가 변동 기여도를 정량적으로 분석한다.",
            },
        ).json()
        with SessionLocal() as db:
            revision = db.get(
                DeepAnalysisWorkflowRevision, created["workflow"]["id"]
            )
            assert revision is not None
            revision.change_log_json = []
            db.commit()

        restored = client.get(f"/api/deep-analysis/missions/{created['id']}")
        assert restored.status_code == 200, restored.text
        detail = restored.json()
        assert detail["workflow"]["revisionNumber"] == 2
        assert detail["workflow"]["changeLog"][-1]["action"] == "legacy_upgraded"

        restored_again = client.get(f"/api/deep-analysis/missions/{created['id']}")
        assert restored_again.json()["workflow"]["revisionNumber"] == 2


def test_every_initial_workflow_contains_a_branch_and_merge() -> None:
    questions = (
        ("원가 변동", "원가 변동 기여도를 정량적으로 분석한다."),
        ("시장 비교", "경쟁사 사례와 시장 동향을 비교 조사한다."),
        ("도입 의사결정", "신규 시스템 투자 리스크와 대안을 평가한다."),
        ("공급망 이슈", "공급망 지연 원인을 분석한다."),
    )
    for title, objective in questions:
        plan = initial_workflow_plan(title, objective)
        edges = plan_edges(plan)
        assert len(plan.nodes) >= 6
        assert edges
        dependency_counts = [len(node.depends_on) for node in plan.nodes]
        outgoing_counts = {
            node.key: sum(source == node.key for source, _target in edges)
            for node in plan.nodes
        }
        assert max(dependency_counts) >= 2
        assert max(outgoing_counts.values()) >= 2


def test_explicit_workflow_presets_do_not_depend_on_question_keywords() -> None:
    assert initial_workflow_plan("1", "2", preset="quantitative").kind == "quantitative"
    assert initial_workflow_plan("1", "2", preset="comparative_research").kind == "comparative_research"
    assert initial_workflow_plan("1", "2", preset="decision").kind == "decision"
    assert initial_workflow_plan("1", "2", preset="open_analysis").kind == "open_analysis"


def test_ai_planner_builds_a_valid_branching_workflow() -> None:
    response = {
        "reason": "원인 가설을 독립 검증한 뒤 합성합니다.",
        "nodes": [
            {"ref": "scope", "nodeType": "scope", "title": "범위 설계", "purpose": "질문과 기준을 확정합니다.", "dependsOn": []},
            {"ref": "cause", "nodeType": "analysis", "title": "주요 원인 분석", "purpose": "주요 원인을 검증합니다.", "dependsOn": ["scope"]},
            {"ref": "counter", "nodeType": "analysis", "title": "대안 원인 분석", "purpose": "대안 설명을 검증합니다.", "dependsOn": ["scope"]},
            {"ref": "merge", "nodeType": "synthesis", "title": "원인 합성", "purpose": "두 분석을 합성합니다.", "dependsOn": ["cause", "counter"]},
            {"ref": "report", "nodeType": "report", "title": "최종 보고서", "purpose": "결론과 근거를 정리합니다.", "dependsOn": ["merge"]},
        ],
    }
    design = asyncio.run(
        design_initial_workflow(
            provider=MockProvider(text_chunks=(json.dumps(response, ensure_ascii=False),)),
            model="mock-agent",
            title="공급망 지연 원인",
            objective="주요 원인과 반대 가설을 검증한다.",
            effort="medium",
        )
    )

    assert design.plan.kind == "ai_designed"
    assert [node.key for node in design.plan.nodes] == ["N001", "N010", "N020", "N030", "N040"]
    assert design.plan.nodes[3].depends_on == ("N010", "N020")
    assert design.plan.nodes[-1].node_type == "report"


def test_mission_api_uses_ai_design(
    tmp_path: Path, monkeypatch,
) -> None:
    ai_response = {
        "reason": "질문별 근거 수집과 반대 관점을 합성합니다.",
        "nodes": [
            {"ref": "scope", "nodeType": "scope", "title": "AI 범위 설계", "purpose": "질문 범위를 정합니다.", "dependsOn": []},
            {"ref": "research", "nodeType": "research", "title": "AI 근거 조사", "purpose": "근거를 수집합니다.", "dependsOn": ["scope"]},
            {"ref": "report", "nodeType": "report", "title": "AI 최종 보고서", "purpose": "결론을 보고합니다.", "dependsOn": ["research"]},
        ],
    }
    monkeypatch.setattr(
        local_run_executor,
        "provider_for_probe",
        lambda _provider_id: MockProvider(
            text_chunks=(json.dumps(ai_response, ensure_ascii=False),)
        ),
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        ai_created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "맞춤 조사",
                "objective": "입력에 맞는 Workflow를 설계한다.",
            },
        )
        assert ai_created.status_code == 201, ai_created.text
        ai_payload = ai_created.json()
        assert ai_payload["startMode"] == "ai_designed"
        assert [node["title"] for node in ai_payload["workflow"]["nodes"]] == [
            "AI 범위 설계",
            "AI 근거 조사",
            "AI 최종 보고서",
        ]
        assert ai_payload["workflow"]["changeLog"][0]["planner"]["mode"] == "ai"


def test_workflow_regeneration_creates_a_new_active_revision(
    tmp_path: Path, monkeypatch,
) -> None:
    responses = (
        {
            "reason": "처음에는 순차 실행합니다.",
            "nodes": [
                {"ref": "scope", "nodeType": "scope", "title": "범위 설정", "purpose": "범위를 정합니다.", "dependsOn": []},
                {"ref": "research", "nodeType": "research", "title": "자료 조사", "purpose": "자료를 조사합니다.", "dependsOn": ["scope"]},
                {"ref": "report", "nodeType": "report", "title": "보고서", "purpose": "결과를 정리합니다.", "dependsOn": ["research"]},
            ],
        },
        {
            "reason": "두 분석을 병렬로 실행한 뒤 합칩니다.",
            "nodes": [
                {"ref": "scope", "nodeType": "scope", "title": "쟁점 정의", "purpose": "분석 범위를 정합니다.", "dependsOn": []},
                {"ref": "market", "nodeType": "research", "title": "시장 조사", "purpose": "시장 자료를 조사합니다.", "dependsOn": ["scope"]},
                {"ref": "finance", "nodeType": "analysis", "title": "재무 분석", "purpose": "재무 자료를 분석합니다.", "dependsOn": ["scope"]},
                {"ref": "report", "nodeType": "report", "title": "통합 보고서", "purpose": "두 결과를 합칩니다.", "dependsOn": ["market", "finance"]},
            ],
        },
    )
    provider_calls = 0

    def provider_for_probe(_provider_id: str) -> MockProvider:
        nonlocal provider_calls
        response = responses[min(provider_calls, len(responses) - 1)]
        provider_calls += 1
        return MockProvider(text_chunks=(json.dumps(response, ensure_ascii=False),))

    monkeypatch.setattr(local_run_executor, "provider_for_probe", provider_for_probe)
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "경쟁사 분석", "objective": "시장과 재무를 분석합니다."},
        ).json()
        previous_workflow_id = created["workflow"]["id"]

        regenerated = client.post(
            f"/api/deep-analysis/missions/{created['id']}/workflow/regenerate",
            headers=headers,
            json={
                "expectedRevision": created["revision"],
                "prompt": "시장 조사와 재무 분석을 병렬로 진행한 뒤 합쳐 주세요.",
            },
        )
        assert regenerated.status_code == 200, regenerated.text
        detail = regenerated.json()
        assert detail["revision"] == 2
        assert detail["status"] == "ready"
        assert detail["workflow"]["id"] != previous_workflow_id
        assert detail["workflow"]["revisionNumber"] == 2
        assert [node["title"] for node in detail["workflow"]["nodes"]] == [
            "쟁점 정의", "시장 조사", "재무 분석", "통합 보고서",
        ]
        assert detail["workflow"]["changeLog"][0]["action"] == "workflow_regenerated"
        assert detail["workflow"]["changeLog"][0]["regenerationPrompt"].startswith("시장 조사")

        with SessionLocal() as db:
            previous = db.get(DeepAnalysisWorkflowRevision, previous_workflow_id)
            assert previous is not None
            assert previous.state == "archived"

        stale = client.post(
            f"/api/deep-analysis/missions/{created['id']}/workflow/regenerate",
            headers=headers,
            json={"expectedRevision": 1, "prompt": "다시 그려 주세요."},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "revision_conflict"
        assert provider_calls == 2

@pytest.mark.skip(reason="runtime LLM replanning was removed")
def test_runtime_decision_branches_merges_and_then_shrinks_the_dag(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "공급망 이슈", "objective": "공급망 지연 원인을 분석한다."},
        ).json()

        markdown, decision = extract_workflow_decision(
            "# 중간 결과\n추가 검증이 필요합니다.\n"
            '<!-- LUMINA_WORKFLOW_DECISION\n'
            '{"action":"expand","reason":"지역과 공급자 가설을 분리 검증한 뒤 합쳐야 합니다.",'
            '"confidence":0.88,"add":[{"ref":"region","title":"지역별 지연 분석",'
            '"purpose":"지역별 리드타임과 병목 차이를 검증합니다.","nodeType":"analysis","dependsOn":["current"]},'
            '{"ref":"supplier","title":"공급자별 지연 분석",'
            '"purpose":"공급자별 납기 편차와 반복 병목을 검증합니다.","nodeType":"analysis","dependsOn":["current"]},'
            '{"ref":"merge","title":"지연 원인 교차검증",'
            '"purpose":"지역과 공급자 분석을 결합해 공통 원인과 예외를 검증합니다.","nodeType":"validation","dependsOn":["region","supplier"]}],'
            '"remove":[]}\n-->'
        )
        assert "LUMINA_WORKFLOW_DECISION" not in markdown
        assert decision["action"] == "expand"

        with SessionLocal() as db:
            mission = db.get(DeepAnalysisMission, created["id"])
            revision = db.get(
                DeepAnalysisWorkflowRevision, created["workflow"]["id"]
            )
            assert mission is not None and revision is not None
            current = db.scalar(
                select(DeepAnalysisWorkflowNode).where(
                    DeepAnalysisWorkflowNode.workflow_revision_id == revision.id,
                    DeepAnalysisWorkflowNode.node_key == "N001",
                )
            )
            assert current is not None
            current.status = "completed"
            assert apply_workflow_decision(
                db,
                mission=mission,
                revision=revision,
                current_node=current,
                decision=decision,
            )
            db.commit()

            nodes = list(
                db.scalars(
                    select(DeepAnalysisWorkflowNode)
                    .where(DeepAnalysisWorkflowNode.workflow_revision_id == revision.id)
                    .order_by(DeepAnalysisWorkflowNode.sequence)
                )
            )
            edges = list(
                db.scalars(
                    select(DeepAnalysisWorkflowEdge).where(
                        DeepAnalysisWorkflowEdge.workflow_revision_id == revision.id
                    )
                )
            )
            region = next(node for node in nodes if node.title == "지역별 지연 분석")
            supplier = next(node for node in nodes if node.title == "공급자별 지연 분석")
            merge = next(node for node in nodes if node.title == "지연 원인 교차검증")
            edge_pairs = {
                (edge.source_node_key, edge.target_node_key) for edge in edges
            }
            assert revision.revision_number == 2
            assert (current.node_key, region.node_key) in edge_pairs
            assert (current.node_key, supplier.node_key) in edge_pairs
            assert (region.node_key, merge.node_key) in edge_pairs
            assert (supplier.node_key, merge.node_key) in edge_pairs
            assert (merge.node_key, "N010") in edge_pairs
            assert next_runnable_node(nodes, edges).node_key == region.node_key
            assert revision.change_log_json[-1]["addedNodeKeys"] == [
                region.node_key,
                supplier.node_key,
                merge.node_key,
            ]

            shrink = {
                "action": "shrink",
                "reason": "기존 자료로 동일 내용을 이미 검증했습니다.",
                "confidence": 0.93,
                "add": [],
                "remove": [region.node_key, supplier.node_key, merge.node_key],
            }
            assert apply_workflow_decision(
                db,
                mission=mission,
                revision=revision,
                current_node=current,
                decision=shrink,
            )
            db.commit()
            remaining = list(
                db.scalars(
                    select(DeepAnalysisWorkflowNode)
                    .where(DeepAnalysisWorkflowNode.workflow_revision_id == revision.id)
                    .order_by(DeepAnalysisWorkflowNode.sequence)
                )
            )
            remaining_edges = list(
                db.scalars(
                    select(DeepAnalysisWorkflowEdge).where(
                        DeepAnalysisWorkflowEdge.workflow_revision_id == revision.id
                    )
                )
            )
            removed_ids = {region.id, supplier.id, merge.id}
            assert all(node.id not in removed_ids for node in remaining)
            assert next_runnable_node(remaining, remaining_edges).node_key == "N010"
            assert set(revision.change_log_json[-1]["removedNodeKeys"]) == {
                region.node_key,
                supplier.node_key,
                merge.node_key,
            }


@pytest.mark.skip(reason="runtime LLM decisions were removed")
def test_runtime_decision_waits_for_durable_user_answer_and_resumes(
    tmp_path: Path, monkeypatch
) -> None:
    enqueued: list[str] = []
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        enqueued.append,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "투자안 심층 분석",
                "objective": "사용자 기준에 따라 투자안의 우선순위를 평가한다.",
            },
        ).json()
        assert created["decisions"] == []

        markdown, decision = extract_workflow_decision(
            "# 중간 결과\n평가 기준을 확정해야 합니다.\n"
            "<!-- LUMINA_WORKFLOW_DECISION\n"
            '{"action":"ask","reason":"평가 기준에 따라 결론이 달라집니다.",'
            '"confidence":0.91,"add":[],"remove":[],'
            '"question":"어떤 기준을 최우선으로 평가할까요?",'
            '"options":[{"id":"profit","label":"수익성","description":"NPV와 회수기간을 우선합니다."},'
            '{"id":"risk","label":"위험 최소화","description":"변동성과 손실 가능성을 우선합니다."}],'
            '"recommendationOptionId":"risk",'
            '"recommendationRationale":"현재 자료의 불확실성이 높습니다.",'
            '"impact":{"summary":"후속 분석의 가중치가 달라집니다."},'
            '"affectedNodeKeys":["N010","N020"]}\n-->'
        )
        assert markdown.startswith("# 중간 결과")
        assert decision["action"] == "ask"
        assert [item["id"] for item in decision["options"]] == ["profit", "risk"]

        with SessionLocal() as db:
            mission = db.get(DeepAnalysisMission, created["id"])
            revision = db.get(
                DeepAnalysisWorkflowRevision, created["workflow"]["id"]
            )
            assert mission is not None and revision is not None
            current = db.scalar(
                select(DeepAnalysisWorkflowNode).where(
                    DeepAnalysisWorkflowNode.workflow_revision_id == revision.id,
                    DeepAnalysisWorkflowNode.node_key == "N001",
                )
            )
            assert current is not None
            mission.status = "running"
            current.status = "completed"
            assert not apply_workflow_decision(
                db,
                mission=mission,
                revision=revision,
                current_node=current,
                decision=decision,
            )
            mission.revision += 1
            db.commit()
            decision_id = db.scalar(
                select(DeepAnalysisDecision.id).where(
                    DeepAnalysisDecision.mission_id == mission.id
                )
            )
            assert decision_id is not None

        waiting = client.get(
            f"/api/deep-analysis/missions/{created['id']}"
        ).json()
        assert waiting["status"] == "awaiting_input"
        assert waiting["revision"] == 2
        assert waiting["decisions"][0]["status"] == "pending"
        assert waiting["decisions"][0]["recommendationOptionId"] == "risk"

        answered = client.post(
            f"/api/deep-analysis/missions/{created['id']}/decisions/{decision_id}/answer",
            headers=headers,
            json={
                "expectedRevision": 2,
                "selectedOptionId": "risk",
                "answerText": "하방 위험을 먼저 제한해 주세요.",
            },
        )
        assert answered.status_code == 200, answered.text
        resumed = answered.json()
        assert resumed["status"] == "running"
        assert resumed["revision"] == 3
        assert resumed["decisions"][0]["status"] == "resolved"
        assert resumed["decisions"][0]["selectedOptionId"] == "risk"
        next_node = next(
            node for node in resumed["workflow"]["nodes"] if node["status"] == "running"
        )
        assert next_node["runId"] in enqueued

        with SessionLocal() as db:
            stored_response = db.scalar(
                select(DeepAnalysisDecisionResponse).where(
                    DeepAnalysisDecisionResponse.decision_id == decision_id
                )
            )
            prompt = db.scalar(
                select(Message.canonical_text).where(
                    Message.run_id == next_node["runId"], Message.role == "user"
                )
            )
            assert stored_response is not None
            assert stored_response.answer_text == "하방 위험을 먼저 제한해 주세요."
            assert prompt is not None
            assert "사용자 확정 판단" in prompt
            assert "위험 최소화 — 하방 위험을 먼저 제한해 주세요." in prompt

        duplicate = client.post(
            f"/api/deep-analysis/missions/{created['id']}/decisions/{decision_id}/answer",
            headers=headers,
            json={
                "expectedRevision": 2,
                "selectedOptionId": "risk",
                "answerText": "하방 위험을 먼저 제한해 주세요.",
            },
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["revision"] == 3

        overwritten = client.post(
            f"/api/deep-analysis/missions/{created['id']}/decisions/{decision_id}/answer",
            headers=headers,
            json={
                "expectedRevision": 3,
                "selectedOptionId": "profit",
                "answerText": "수익성을 우선합니다.",
            },
        )
        assert overwritten.status_code == 409
        assert overwritten.json()["code"] == "decision_already_resolved"

        listed = client.get(
            f"/api/deep-analysis/missions/{created['id']}/decisions"
        )
        assert listed.status_code == 200
        assert listed.json()[0]["appliedWorkflowRevisionNumber"] == 1


@pytest.mark.skip(reason="charter and quality gate were removed")
def test_charter_contract_quality_gate_and_immutable_waiver(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "계약 검증 분석", "objective": "투자 타당성을 판단한다."},
        ).json()
        patched = client.patch(
            f"/api/deep-analysis/missions/{created['id']}",
            headers=headers,
            json={
                "expectedRevision": 1,
                "charter": {
                    "purpose": "투자 타당성을 판단한다.",
                    "keyQuestions": ["예상 수익이 위험을 보상하는가?"],
                    "deliverables": ["최종 Markdown 보고서"],
                    "audience": "투자심의위원회",
                    "inScope": ["향후 3년 현금흐름"],
                    "outOfScope": ["법률 실사"],
                    "comparisonBasis": "기준안 대비",
                    "qualityStandards": ["근거 없는 수치를 사용하지 않음"],
                },
                "completionContract": {
                    "requiredSections": ["결론", "근거", "한계"],
                    "requiredNodeTypes": ["report"],
                    "requireReport": True,
                    "requireNoFailedNodes": True,
                    "requireNoStaleNodes": True,
                    "minimumEvidenceCoverage": 0,
                    "maximumOpenIssues": 0,
                    "requiresFinalReview": True,
                    "allowWaiver": True,
                },
            },
        )
        assert patched.status_code == 200, patched.text
        contract = patched.json()
        assert contract["revision"] == 2
        assert contract["charter"]["audience"] == "투자심의위원회"
        assert contract["completionContract"]["requiresFinalReview"] is True

        output = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={
                "logicalPath": "심층분석/계약 검증 분석_test/N040_최종 보고서.md",
                "changeReason": "Quality Gate 테스트",
            },
            files={
                "file": (
                    "N040_최종 보고서.md",
                    "# 결론\n진행 가능\n# 근거\n검증됨\n# 한계\n법률 실사 제외\n".encode(),
                    "text/markdown",
                )
            },
        )
        assert output.status_code == 201, output.text

        with SessionLocal() as db:
            mission = db.get(DeepAnalysisMission, created["id"])
            revision = db.get(
                DeepAnalysisWorkflowRevision, created["workflow"]["id"]
            )
            assert mission is not None and revision is not None
            nodes = list(
                db.scalars(
                    select(DeepAnalysisWorkflowNode)
                    .where(DeepAnalysisWorkflowNode.workflow_revision_id == revision.id)
                    .order_by(DeepAnalysisWorkflowNode.sequence)
                )
            )
            report = next(node for node in nodes if node.node_type == "report")
            for node in nodes:
                node.status = "completed"
            mission.status = "running"
            mission.charter_json = {**mission.charter_json, "confirmed": True}
            report.output_project_file_id = output.json()["id"]
            report.output_logical_path = output.json()["logicalPath"]
            report.output_markdown = "# 결론\n진행 가능\n# 근거\n검증됨\n# 한계\n법률 실사 제외\n"
            gate = evaluate_quality_gate(
                db,
                mission=mission,
                revision=revision,
                report_node=report,
                nodes=nodes,
            )
            mission.revision += 1
            db.commit()
            assert gate.result == "failed"

        waiting = client.get(
            f"/api/deep-analysis/missions/{created['id']}"
        ).json()
        assert waiting["status"] == "awaiting_input"
        assert waiting["completionOutcome"] is None
        assert waiting["completionContract"]["qualityGate"] == "waiver_required"
        failed_gate = waiting["qualityGates"][-1]
        assert failed_gate["result"] == "failed"
        assert any(
            check["id"] == "final_review" and check["status"] == "failed"
            for check in failed_gate["checks"]
        )
        waiver_decision = waiting["decisions"][-1]

        waived = client.post(
            f"/api/deep-analysis/missions/{created['id']}/decisions/{waiver_decision['id']}/answer",
            headers=headers,
            json={
                "expectedRevision": waiting["revision"],
                "selectedOptionId": "accept_exceptions",
                "answerText": "위원회 검토를 완료했고 예외를 승인합니다.",
            },
        )
        assert waived.status_code == 200, waived.text
        resolved = waived.json()
        assert resolved["status"] == "completed"
        assert resolved["completionOutcome"] == "satisfied_with_exceptions"
        assert resolved["qualityGates"][-1]["result"] == "waived"
        assert resolved["qualityGates"][-1]["parentResultId"] == failed_gate["id"]
        assert resolved["qualityGates"][-1]["waiverDecisionId"] == waiver_decision["id"]
        completed_events = client.get(
            f"/api/deep-analysis/missions/{created['id']}/events",
            params={"afterSequence": 0, "limit": 500},
        ).json()
        assert completed_events[-1]["type"] == "mission_completed"
        completed_cursor = completed_events[-1]["sequence"]

        rerun = client.post(
            f"/api/deep-analysis/missions/{created['id']}/quality-gate",
            headers=headers,
            json={"expectedRevision": resolved["revision"]},
        )
        assert rerun.status_code == 200, rerun.text
        assert rerun.json()["status"] == "awaiting_input"
        assert rerun.json()["qualityGates"][-1]["result"] == "failed"
        awaiting_events = client.get(
            f"/api/deep-analysis/missions/{created['id']}/events",
            params={"afterSequence": completed_cursor},
        ).json()
        awaiting_types = [item["type"] for item in awaiting_events]
        assert "decision_requested" in awaiting_types
        assert "mission_completed" not in awaiting_types


@pytest.mark.skip(reason="claim and evidence ledger were removed")
def test_claim_evidence_ledger_resolves_exact_file_versions_and_lists_lineage(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": "inputs/variance.csv", "changeReason": "근거 테스트"},
            files={
                "file": (
                    "variance.csv",
                    "driver,amount\nmaterial,125\n".encode(),
                    "text/csv",
                )
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "Claim Evidence 검증", "objective": "변동 원인을 검증한다."},
        ).json()

        with SessionLocal() as db:
            mission = db.get(DeepAnalysisMission, created["id"])
            project_file = db.get(ProjectFile, uploaded.json()["id"])
            assert mission is not None and project_file is not None
            version = db.scalar(
                select(ProjectFileVersion).where(
                    ProjectFileVersion.project_file_id == project_file.id,
                    ProjectFileVersion.version_number
                    == project_file.current_version_number,
                )
            )
            node = db.scalar(
                select(DeepAnalysisWorkflowNode).where(
                    DeepAnalysisWorkflowNode.workflow_revision_id
                    == created["workflow"]["id"]
                )
            )
            assert version is not None and node is not None
            mission.source_manifest_json = [
                {
                    "projectFileId": project_file.id,
                    "logicalPath": project_file.logical_path,
                    "version": version.version_number,
                    "versionId": version.id,
                    "contentHash": version.content_hash,
                        "mimeType": version.mime_type,
                    "sizeBytes": version.size_bytes,
                }
            ]
            markdown = f'''# 분석 결과
원재료비가 핵심 원인입니다.
<!-- LUMINA_ANALYSIS_LEDGER
{{"claims":[{{"statement":"원재료비가 총 변동의 핵심 원인이다.","level":"key_finding","status":"verified","confidence":0.94,"materiality":"high","reportInclusion":"executive_summary","validation":{{"method":"행 합계 재계산"}},"evidence":[{{"sourceType":"project_file","stableId":"{project_file.id}","versionId":"{version.id}","contentDigest":"{version.content_hash}","locator":"row 2, amount","title":"변동 원본","stance":"support","rationale":"원재료비 125를 직접 확인"}}]}}],"openIssues":[{{"issueType":"missing_data","statement":"수량 효과 세부 데이터가 없다.","materiality":"medium","residualPercent":4.5,"requiredAction":"수량 명세 확보","reportInclusion":"open_issues"}}]}}
-->
'''
            clean, ledger = extract_analysis_ledger(markdown)
            assert "LUMINA_ANALYSIS_LEDGER" not in clean
            persist_analysis_ledger(db, mission=mission, node=node, ledger=ledger)

            _clean, invalid_ledger = extract_analysis_ledger(
                f'''<!-- LUMINA_ANALYSIS_LEDGER
{{"claims":[{{"statement":"잘못된 버전 근거 Claim","level":"key_finding","status":"verified","confidence":0.8,"materiality":"medium","evidence":[{{"sourceType":"project_file","stableId":"{project_file.id}","versionId":"wrong-version","contentDigest":"{version.content_hash}","locator":"row 2","stance":"support"}}]}}],"openIssues":[]}}
-->'''
            )
            persist_analysis_ledger(
                db, mission=mission, node=node, ledger=invalid_ledger
            )
            node_key = node.node_key
            version_id = version.id
            db.commit()

        detail = client.get(
            f"/api/deep-analysis/missions/{created['id']}"
        )
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert len(payload["claims"]) == 2
        verified = next(
            claim for claim in payload["claims"] if claim["status"] == "verified"
        )
        assert verified["sourceNodeKey"] == node_key
        assert verified["evidence"][0]["stance"] == "support"
        assert verified["evidence"][0]["evidence"]["versionId"] == version_id
        downgraded = next(
            claim for claim in payload["claims"] if claim["statement"] == "잘못된 버전 근거 Claim"
        )
        assert downgraded["status"] == "proposed"
        assert "downgradedReason" in downgraded["validation"]
        assert payload["openIssues"][0]["residualPercent"] == 4.5

        assert client.get(
            f"/api/deep-analysis/missions/{created['id']}/claims"
        ).json() == payload["claims"]
        assert client.get(
            f"/api/deep-analysis/missions/{created['id']}/evidence"
        ).json() == payload["evidence"]
        assert client.get(
            f"/api/deep-analysis/missions/{created['id']}/open-issues"
        ).json() == payload["openIssues"]


def test_mission_export_saves_generated_and_frozen_source_files_as_project_folder(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        source = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": "inputs/source.csv", "changeReason": "export test"},
            files={"file": ("source.csv", b"key,value\nA,1\n", "text/csv")},
        ).json()
        generated = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={
                "logicalPath": "심층분석/내보내기 검증/N040_최종 보고서.md",
                "changeReason": "generated export test",
            },
            files={"file": ("report.md", b"# final report\n", "text/markdown")},
        ).json()
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "내보내기 검증", "objective": "파일 저장소에 결과 폴더를 만든다."},
        ).json()
        with SessionLocal() as db:
            mission = db.get(DeepAnalysisMission, created["id"])
            project_file = db.get(ProjectFile, source["id"])
            assert mission is not None and project_file is not None
            version = db.scalar(
                select(ProjectFileVersion).where(
                    ProjectFileVersion.project_file_id == project_file.id
                )
            )
            assert version is not None
            mission.source_manifest_json = [
                {
                    "projectFileId": project_file.id,
                    "logicalPath": project_file.logical_path,
                    "version": version.version_number,
                    "versionId": version.id,
                    "contentHash": version.content_hash,
                    "mimeType": version.mime_type,
                    "sizeBytes": version.size_bytes,
                }
            ]
            node = db.scalar(
                select(DeepAnalysisWorkflowNode)
                .join(
                    DeepAnalysisWorkflowRevision,
                    DeepAnalysisWorkflowRevision.id
                    == DeepAnalysisWorkflowNode.workflow_revision_id,
                )
                .where(DeepAnalysisWorkflowRevision.mission_id == mission.id)
                .order_by(DeepAnalysisWorkflowNode.sequence.desc())
            )
            assert node is not None
            node.output_project_file_id = generated["id"]
            node.output_logical_path = generated["logicalPath"]
            db.commit()

        operation = client.post(
            f"/api/deep-analysis/missions/{created['id']}/exports",
            headers=headers,
            json={},
        )
        assert operation.status_code == 201, operation.text
        export = operation.json()
        assert export["status"] == "completed"
        assert export["scope"] == "latest"
        assert export["contentHash"] is None
        assert export["manifest"]["includeOriginals"] is True
        assert export["manifest"]["generatedFileCount"] == 1
        assert export["manifest"]["sourceFileCount"] == 1
        folder_path = export["manifest"]["folderPath"]
        assert export["filename"] == folder_path
        assert re.fullmatch(
            r"Mission 내보내기/내보내기 검증_\d{6}_\d{6}", folder_path
        )

        duplicate = client.post(
            f"/api/deep-analysis/missions/{created['id']}/exports",
            headers=headers,
            json={},
        )
        assert duplicate.status_code == 429, duplicate.text
        assert duplicate.json()["code"] == "mission_export_cooldown"

        stored_files = client.get(f"/api/projects/{project_id}/files").json()
        exported_files = [
            item for item in stored_files if item["logicalPath"].startswith(f"{folder_path}/")
        ]
        assert {item["logicalPath"] for item in exported_files} == {
            f"{folder_path}/생성 파일/N040_최종 보고서.md",
            f"{folder_path}/원본 자료/source.csv",
        }
        with SessionLocal() as db:
            assert db.scalar(
                select(ProjectFolder).where(
                    ProjectFolder.project_id == project_id,
                    ProjectFolder.logical_path == folder_path,
                )
            ) is not None
            assert len(
                db.scalars(
                    select(DeepAnalysisMissionExport).where(
                        DeepAnalysisMissionExport.mission_id == created["id"]
                    )
                ).all()
            ) == 1
        contents = {
            item["logicalPath"]: client.get(
                f"/api/projects/{project_id}/files/{item['id']}/download"
            ).content
            for item in exported_files
        }
        assert contents[f"{folder_path}/생성 파일/N040_최종 보고서.md"] == b"# final report\n"
        assert contents[f"{folder_path}/원본 자료/source.csv"] == b"key,value\nA,1\n"


def test_workflow_draft_is_separate_validated_and_activated_atomically(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "Draft 편집 검증", "objective": "분기와 합류를 편집한다."},
        ).json()
        active_id = created["workflow"]["id"]
        draft_response = client.post(
            f"/api/deep-analysis/missions/{created['id']}/revisions",
            headers=headers,
            json={"expectedRevision": 1},
        )
        assert draft_response.status_code == 201, draft_response.text
        draft = draft_response.json()
        assert draft["state"] == "draft"
        assert draft["id"] != active_id
        nodes = draft["nodes"]
        nodes[0]["positionX"] += 75
        payload_nodes = [
            {
                "nodeKey": node["nodeKey"], "nodeType": node["nodeType"],
                "title": node["title"], "purpose": node["purpose"],
                "positionX": node["positionX"], "positionY": node["positionY"],
                "config": node["config"],
            }
            for node in nodes
        ]
        payload_nodes.append(
            {
                    "nodeKey": "N999",
                "nodeType": "task",
                "title": "두 번째 작업",
                "purpose": "첫 작업 결과를 이어서 정리한다.",
                "positionX": nodes[0]["positionX"],
                "positionY": nodes[0]["positionY"] + 160,
                "config": {},
            }
        )
        cycle = client.patch(
            f"/api/deep-analysis/missions/{created['id']}/draft",
            headers=headers,
            json={"expectedRevision": 1, "nodes": payload_nodes, "edges": [
                {"sourceNodeKey": nodes[0]["nodeKey"], "targetNodeKey": "N999"},
                {"sourceNodeKey": "N999", "targetNodeKey": nodes[0]["nodeKey"]},
            ]},
        )
        assert cycle.status_code == 422
        saved = client.patch(
            f"/api/deep-analysis/missions/{created['id']}/draft",
            headers=headers,
            json={"expectedRevision": 1, "nodes": payload_nodes, "edges": [
                {"sourceNodeKey": nodes[0]["nodeKey"], "targetNodeKey": "N999"}
            ]},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["nodes"][0]["positionX"] == nodes[0]["positionX"]
        activated = client.post(
            f"/api/deep-analysis/missions/{created['id']}/draft/activate",
            headers=headers,
            json={"expectedRevision": 1},
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["revision"] == 2
        assert activated.json()["workflow"]["id"] == draft["id"]
        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": 2},
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "running"
        assert started.json()["workflow"]["nodes"][0]["status"] == "running"
        with SessionLocal() as db:
            previous = db.get(DeepAnalysisWorkflowRevision, active_id)
            assert previous is not None and previous.state == "archived"


@pytest.mark.skip(reason="workflow pattern creation was removed from the UI contract")
def test_published_pattern_is_sanitized_versioned_and_optional_for_new_mission(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        source = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "Pattern 원본", "objective": "반복 가능한 변동 분석"},
        ).json()
        with SessionLocal() as db:
            node = db.scalar(
                select(DeepAnalysisWorkflowNode).where(
                    DeepAnalysisWorkflowNode.workflow_revision_id
                    == source["workflow"]["id"]
                )
            )
            assert node is not None
            node.config_json = {
                "role": "variance_driver",
                "semanticInputRoles": ["계획 대비 실적"],
                "projectFileId": "must-not-leak",
                "resolvedDecision": {"answer": "must-not-leak"},
            }
            db.commit()

        draft_response = client.post(
            f"/api/projects/{project_id}/deep-analysis/patterns",
            headers=headers,
            json={
                "missionId": source["id"],
                "name": "변동 원인 분석",
                "description": "구조만 재사용",
            },
        )
        assert draft_response.status_code == 201, draft_response.text
        draft = draft_response.json()
        assert draft["status"] == "draft"
        first_config = draft["definition"]["nodes"][0]["config"]
        assert first_config["role"] == "variance_driver"
        assert first_config["semanticInputRoles"] == ["계획 대비 실적"]
        assert "projectFileId" not in first_config
        assert "resolvedDecision" not in first_config

        published = client.post(
            f"/api/deep-analysis/patterns/{draft['patternId']}/versions/{draft['id']}/publish",
            headers=headers,
        )
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "published"
        patterns = client.get(
            f"/api/projects/{project_id}/deep-analysis/patterns"
        ).json()
        assert patterns[0]["latestPublishedVersion"]["id"] == draft["id"]

        instantiated = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "Pattern 적용 Mission",
                "objective": "이번 달 원가 변동을 분석한다.",
                "patternVersionId": draft["id"],
            },
        )
        assert instantiated.status_code == 201, instantiated.text
        payload = instantiated.json()
        assert payload["startMode"] == "pattern_based"
        assert payload["patternVersionId"] == draft["id"]
        assert payload["workflow"]["source"] == "pattern"
        assert payload["workflow"]["nodes"][0]["id"] != source["workflow"]["nodes"][0]["id"]

        second = client.post(
            f"/api/deep-analysis/patterns/{draft['patternId']}/versions",
            headers=headers,
            json={"missionId": payload["id"], "changeSummary": "새 Mission 구조 검토"},
        )
        assert second.status_code == 201, second.text
        assert second.json()["versionNumber"] == 2
        assert published.json()["definitionDigest"] == draft["definitionDigest"]

        deleted = client.delete(
            f"/api/deep-analysis/patterns/{draft['patternId']}",
            headers=headers,
        )
        assert deleted.status_code == 204, deleted.text
        assert client.get(
            f"/api/projects/{project_id}/deep-analysis/patterns"
        ).json() == []
        with SessionLocal() as db:
            archived = db.get(DeepAnalysisWorkflowPattern, draft["patternId"])
            assert archived is not None and archived.status == "archived"
        unavailable = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "보관된 Pattern 적용",
                "patternVersionId": draft["id"],
            },
        )
        assert unavailable.status_code == 409
        assert unavailable.json()["code"] == "pattern_archived"


def test_mission_endpoints_require_auth_and_project_access(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert (
            client.get("/api/projects/missing/deep-analysis/missions").status_code
            == 401
        )
        headers = _login(client)
        denied = client.post(
            "/api/projects/missing/deep-analysis/missions",
            headers=headers,
            json={"title": "접근 불가"},
        )
        assert denied.status_code == 404


def test_mission_executes_all_nodes_and_persists_markdown_outputs(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "실행 가능한 분석",
                "objective": "실제 Run을 거쳐 Node별 Markdown을 생성한다.",
            },
        ).json()

        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "running"
        assert started.json()["workflow"]["nodes"][0]["runId"] is not None

        deadline = time.monotonic() + 10
        restored = started.json()
        while time.monotonic() < deadline and restored["status"] == "running":
            time.sleep(0.1)
            restored = client.get(f"/api/deep-analysis/missions/{created['id']}").json()

        assert restored["status"] == "completed"
        assert restored["completionOutcome"] == "satisfied"
        assert "qualityGates" not in restored
        assert "claims" not in restored
        assert all(
            node["status"] == "completed" for node in restored["workflow"]["nodes"]
        )
        assert all(node["runId"] for node in restored["workflow"]["nodes"])
        assert all(node["conversationId"] for node in restored["workflow"]["nodes"])
        assert all(node["outputMarkdown"] for node in restored["workflow"]["nodes"])
        assert all(
            "LUMINA_ANALYSIS_LEDGER" not in node["executionPrompt"]
            and "LUMINA_WORKFLOW_DECISION" not in node["executionPrompt"]
            and "Claim·Evidence" not in node["executionPrompt"]
            for node in restored["workflow"]["nodes"]
        )
        output_timestamp = datetime.fromisoformat(created["createdAt"]).astimezone(
            ZoneInfo("Asia/Seoul")
        )
        assert all(
            node["outputLogicalPath"].startswith(
                f"심층분석/실행 가능한 분석_{output_timestamp:%y%m%d_%H%M%S}/"
            )
            for node in restored["workflow"]["nodes"]
        )
        assert all(node["contextManifest"] for node in restored["workflow"]["nodes"])
        assert all(
            node["contextManifest"]["prefixHash"]
            for node in restored["workflow"]["nodes"]
        )
        incoming: dict[str, set[str]] = {
            node["nodeKey"]: set() for node in restored["workflow"]["nodes"]
        }
        for edge in restored["workflow"]["edges"]:
            incoming[edge["targetNodeKey"]].add(edge["sourceNodeKey"])

        def ancestors(node_key: str) -> set[str]:
            direct = incoming[node_key]
            return set(direct).union(*(ancestors(key) for key in direct))

        for node in restored["workflow"]["nodes"]:
            dependency_keys = {
                str(item["logicalPath"]).rsplit("/", 1)[-1].split("_", 1)[0]
                for item in node["contextManifest"]["items"]
                if item["role"] == "dependency_output"
            }
            assert dependency_keys <= ancestors(node["nodeKey"])
        assert len([
            item for item in restored["files"] if item["purpose"] == "node_output"
        ]) == len(restored["workflow"]["nodes"])
        assert all(item["projectFileVersionId"] for item in restored["files"])
        assert all("estimatedCostMicrousd" not in node for node in restored["workflow"]["nodes"])
        assert all("actualCostMicrousd" in node for node in restored["workflow"]["nodes"])

        costs = client.get(
            f"/api/deep-analysis/missions/{created['id']}/costs"
        )
        assert costs.status_code == 200, costs.text
        assert len(costs.json()["rows"]) == len(restored["workflow"]["nodes"])
        assert costs.json()["estimatedCompletionMicrousd"] >= restored["spentMicrousd"]

        events = client.get(
            f"/api/deep-analysis/missions/{created['id']}/events",
            params={"afterSequence": 0, "limit": 500},
        ).json()
        event_types = [item["type"] for item in events]
        assert event_types.count("node_started") == len(restored["workflow"]["nodes"])
        assert event_types.count("node_output_delta") >= len(restored["workflow"]["nodes"])
        assert event_types[-1] == "mission_completed"

        visible_conversations = client.get(
            f"/api/conversations?project_id={project_id}"
        ).json()["items"]
        assert all(
            item["title"] != "심층분석 · 실행 가능한 분석"
            for item in visible_conversations
        )


def test_mission_delete_checks_revision_and_cascades_workflow(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        mission = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "삭제할 분석"},
        ).json()
        workflow_id = mission["workflow"]["id"]
        node_ids = [node["id"] for node in mission["workflow"]["nodes"]]
        edge_ids = [edge["id"] for edge in mission["workflow"]["edges"]]
        created_at = datetime.fromisoformat(mission["createdAt"]).astimezone(
            ZoneInfo("Asia/Seoul")
        )
        output_path = (
            f"심층분석/삭제할 분석_{created_at:%y%m%d_%H%M%S}/"
            "N001_목표·범위 확정.md"
        )
        output = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": output_path, "changeReason": "삭제 연동 검증"},
            files={
                "file": (
                    "N001_목표·범위 확정.md",
                    "# 삭제할 산출물\n".encode(),
                    "text/markdown",
                )
            },
        )
        assert output.status_code == 201, output.text

        stale = client.delete(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            params={"expected_revision": 2},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "revision_conflict"

        deleted = client.delete(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            params={"expected_revision": 1},
        )
        assert deleted.status_code == 204, deleted.text
        assert (
            client.get(f"/api/deep-analysis/missions/{mission['id']}").status_code
            == 404
        )
        assert (
            client.get(f"/api/projects/{project_id}/deep-analysis/missions").json()
            == []
        )

        with SessionLocal() as db:
            assert db.get(DeepAnalysisMission, mission["id"]) is None
            assert db.get(DeepAnalysisWorkflowRevision, workflow_id) is None
            assert all(
                db.get(DeepAnalysisWorkflowNode, node_id) is None
                for node_id in node_ids
            )
            assert all(
                db.get(DeepAnalysisWorkflowEdge, edge_id) is None
                for edge_id in edge_ids
            )
            output_file = db.get(ProjectFile, output.json()["id"])
            assert output_file is not None
            assert output_file.status == "deleted"
            assert output_file.deleted_at is not None


def test_running_mission_can_be_cancelled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "시작할 분석"},
        ).json()
        assert all(
            node["executionPrompt"] is None
            for node in created["workflow"]["nodes"]
        )

        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "running"
        assert started.json()["executionAvailable"] is True
        assert started.json()["revision"] == 2
        assert started.json()["workflow"]["nodes"][0]["status"] == "running"
        running_node = started.json()["workflow"]["nodes"][0]
        assert running_node["executionPrompt"] is not None
        assert f"작업 세션: {running_node['nodeKey']}" in running_node["executionPrompt"]
        with SessionLocal() as db:
            stored_prompt = db.scalar(
                select(Message.canonical_text).where(
                    Message.run_id == running_node["runId"], Message.role == "user"
                )
            )
        assert running_node["executionPrompt"] == stored_prompt

        cancelled = client.post(
            f"/api/deep-analysis/missions/{created['id']}/cancel",
            headers=headers,
            json={"expectedRevision": 2},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["revision"] == 3
        assert cancelled.json()["workflow"]["nodes"][0]["status"] == "cancelled"

        duplicate_cancel = client.post(
            f"/api/deep-analysis/missions/{created['id']}/cancel",
            headers=headers,
            json={"expectedRevision": 2},
        )
        assert duplicate_cancel.status_code == 200, duplicate_cancel.text
        assert duplicate_cancel.json()["revision"] == 3


def test_mission_events_replay_and_start_command_are_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "Replay audit", "objective": "sensitive objective"},
        ).json()
        assert created["eventCursor"] == 1

        first_page = client.get(
            f"/api/deep-analysis/missions/{created['id']}/events",
            params={"afterSequence": 0},
        )
        assert first_page.status_code == 200, first_page.text
        assert [item["type"] for item in first_page.json()] == ["mission_created"]
        assert "objective" not in json.dumps(first_page.json()).lower()

        command_headers = {**headers, "Idempotency-Key": "start-once"}
        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=command_headers,
            json={"expectedRevision": 1},
        )
        assert started.status_code == 200, started.text
        duplicate = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=command_headers,
            json={"expectedRevision": 1},
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["revision"] == started.json()["revision"] == 2
        assert duplicate.json()["workflow"]["nodes"][0]["runId"] == started.json()["workflow"]["nodes"][0]["runId"]

        replay = client.get(
            f"/api/deep-analysis/missions/{created['id']}/events",
            params={"afterSequence": 1},
        )
        assert replay.status_code == 200, replay.text
        replay_types = [item["type"] for item in replay.json()]
        assert replay_types == ["node_queued", "mission_status_changed"]
        assert [item["sequence"] for item in replay.json()] == [2, 3]

        conflict = client.post(
            f"/api/deep-analysis/missions/{created['id']}/cancel",
            headers=command_headers,
            json={"expectedRevision": 2},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "idempotency_conflict"
        with SessionLocal() as db:
            assert db.query(DeepAnalysisCommand).count() == 1
            assert db.query(DeepAnalysisEvent).count() == 3


def test_mission_events_are_not_capped_and_are_deleted_with_the_mission(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "Retention audit", "objective": "Keep recent events"},
        ).json()

        with SessionLocal() as db:
            mission = db.get(DeepAnalysisMission, created["id"])
            assert mission is not None
            for index in range(250):
                emit_event(db, mission, "retention_test", {"index": index})
            db.commit()

            retained = list(
                db.scalars(
                    select(DeepAnalysisEvent)
                    .where(DeepAnalysisEvent.mission_id == mission.id)
                    .order_by(DeepAnalysisEvent.sequence)
                )
            )
            assert len(retained) == 251
            assert [retained[0].sequence, retained[-1].sequence] == [1, 251]

        response = client.get(
            f"/api/deep-analysis/missions/{created['id']}/events",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert len(response.json()) == 251
        assert [response.json()[0]["sequence"], response.json()[-1]["sequence"]] == [1, 251]

        deleted = client.delete(
            f"/api/deep-analysis/missions/{created['id']}",
            headers=headers,
            params={"expected_revision": created["revision"]},
        )
        assert deleted.status_code == 204, deleted.text
        with SessionLocal() as db:
            assert db.scalars(
                select(DeepAnalysisEvent).where(
                    DeepAnalysisEvent.mission_id == created["id"]
                )
            ).all() == []


def test_cost_breakdown_separates_cache_tokens_and_no_cache_upper_bound(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        mission = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "Cache cost audit", "budgetMicrousd": 1_000_000},
        ).json()
        started = client.post(
            f"/api/deep-analysis/missions/{mission['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        ).json()
        run_id = started["workflow"]["nodes"][0]["runId"]
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            run.provider_id = "codex"
            run.model_key = "gpt-5.5"
            run.model_display_name = "GPT-5.5"
            run.usage_json = {
                "input_tokens": 1_000,
                "cached_input_tokens": 400,
                "cache_write_tokens": 100,
                "uncached_input_tokens": 500,
                "output_tokens": 200,
                "estimated_cost_breakdown_usd": {"total": 0.009},
                "pricing_version": "public-list-2026-07-12",
                "cost_basis": "price_table_estimate",
            }
            db.commit()

        response = client.get(
            f"/api/deep-analysis/missions/{mission['id']}/costs"
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["totals"] == {
            "inputTokens": 1_000,
            "cachedInputTokens": 400,
            "cacheWriteTokens": 100,
            "uncachedInputTokens": 500,
            "outputTokens": 200,
        }
        assert payload["cacheHitRatio"] == 400 / 900
        assert payload["rows"][0]["pricingVersion"] == "public-list-2026-07-12"
        assert payload["rows"][0]["noCacheCostMicrousd"] > payload["rows"][0]["actualCostMicrousd"]
        assert payload["noCacheUpperBoundMicrousd"] >= payload["estimatedCompletionMicrousd"]


def test_running_mission_can_pause_and_resume_same_run(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "Pause recovery"},
        ).json()
        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        ).json()
        run_id = started["workflow"]["nodes"][0]["runId"]

        paused = client.post(
            f"/api/deep-analysis/missions/{created['id']}/pause",
            headers={**headers, "Idempotency-Key": "pause-once"},
            json={"expectedRevision": 2},
        )
        assert paused.status_code == 200, paused.text
        assert paused.json()["status"] == "paused"
        assert paused.json()["workflow"]["nodes"][0]["runId"] == run_id
        assert paused.json()["workflow"]["nodes"][0]["runStatus"] == "paused"

        resumed = client.post(
            f"/api/deep-analysis/missions/{created['id']}/resume",
            headers={**headers, "Idempotency-Key": "resume-once"},
            json={"expectedRevision": 3},
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "running"
        assert resumed.json()["revision"] == 4
        assert resumed.json()["workflow"]["nodes"][0]["runId"] == run_id
        assert resumed.json()["workflow"]["nodes"][0]["runStatus"] == "queued"


def test_cancelled_node_can_be_retried_with_attempt_history(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "재실행 검증"},
        ).json()

        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        ).json()
        first_run_id = started["workflow"]["nodes"][0]["runId"]
        first_conversation_id = started["workflow"]["nodes"][0]["conversationId"]
        with SessionLocal() as db:
            run = db.get(Run, first_run_id)
            assert run is not None
            run.assistant_draft = "# 중단 전 부분 분석\n\n아직 검증 중인 내용입니다."
            db.commit()
        cancelled = client.post(
            f"/api/deep-analysis/missions/{created['id']}/cancel",
            headers=headers,
            json={"expectedRevision": 2},
        ).json()
        partial_outputs = [
            item for item in cancelled["files"] if item["purpose"] == "partial_output"
        ]
        assert len(partial_outputs) == 1
        assert partial_outputs[0]["validationStatus"] == "interrupted"
        assert partial_outputs[0]["logicalPath"].endswith("_partial.md")

        retried = client.post(
            f"/api/deep-analysis/missions/{created['id']}/retry",
            headers=headers,
            json={"expectedRevision": 3, "nodeKey": "N001"},
        )
        assert retried.status_code == 200, retried.text
        payload = retried.json()
        node = payload["workflow"]["nodes"][0]
        assert payload["status"] == "running"
        assert payload["revision"] == 4
        assert node["status"] == "running"
        assert node["runId"] != first_run_id
        assert node["conversationId"] == first_conversation_id
        assert node["runHistory"] == [
            {
                "attempt": 1,
                "runId": first_run_id,
                "status": "cancelled",
                "costMicrousd": 0,
                "errorMessage": None,
                "startedAt": node["runHistory"][0]["startedAt"],
                "finishedAt": node["runHistory"][0]["finishedAt"],
            }
        ]
        assert cancelled["revision"] == 3


def test_completed_mission_can_restart_from_the_workflow_start(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={"title": "처음부터 재시작 검증"},
        ).json()
        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        ).json()
        first_run_id = started["workflow"]["nodes"][0]["runId"]

        with SessionLocal() as db:
            mission = db.get(DeepAnalysisMission, created["id"])
            assert mission is not None
            revision = db.get(DeepAnalysisWorkflowRevision, started["workflow"]["id"])
            assert revision is not None
            nodes = list(
                db.scalars(
                    select(DeepAnalysisWorkflowNode)
                    .where(DeepAnalysisWorkflowNode.workflow_revision_id == revision.id)
                    .order_by(DeepAnalysisWorkflowNode.sequence)
                )
            )
            run = db.get(Run, first_run_id)
            assert run is not None
            run.status = "completed"
            for node in nodes:
                node.status = "completed"
                node.output_markdown = f"# 이전 결과 {node.node_key}"
            mission.status = "completed"
            db.commit()

        restarted = client.post(
            f"/api/deep-analysis/missions/{created['id']}/restart",
            headers=headers,
            json={"expectedRevision": 2},
        )
        assert restarted.status_code == 200, restarted.text
        payload = restarted.json()
        nodes = payload["workflow"]["nodes"]
        running = [node for node in nodes if node["status"] == "running"]
        assert payload["status"] == "running"
        assert payload["revision"] == 3
        assert len(running) == 1
        assert running[0]["nodeKey"] == "N001"
        assert running[0]["runId"] != first_run_id
        assert running[0]["runHistory"][0]["runId"] == first_run_id
        assert all(node["outputMarkdown"] == "" for node in nodes)
        assert all(node["status"] in {"running", "planned"} for node in nodes)


def test_python_calculation_uses_frozen_csv_and_saves_script_and_result(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        "lumina.api.routes.deep_analysis.local_run_executor.enqueue",
        lambda _run_id: None,
    )
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": "inputs/cost.csv", "changeReason": "계산 테스트"},
            files={
                "file": (
                    "cost.csv",
                    "item,previous,current\nA,100,125\nB,200,180\n".encode(),
                    "text/csv",
                )
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        prior_output = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={
                "logicalPath": "심층분석/이전 분석_deadbeef/N040_최종 보고서.md",
                "changeReason": "이전 Mission 산출물",
            },
            files={
                "file": (
                    "N040_최종 보고서.md",
                    "# 이전 분석 결과\n".encode(),
                    "text/markdown",
                )
            },
        )
        assert prior_output.status_code == 201, prior_output.text
        mission = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "원가 계산",
                "objective": "@inputs/cost.csv를 기준으로 원가를 계산합니다.",
                "promptReferences": [
                    {
                        "kind": "file",
                        "referenceId": uploaded.json()["id"],
                        "versionOrDigest": uploaded.json()["contentHash"],
                        "tokenStart": 0,
                        "tokenEnd": len("@inputs/cost.csv"),
                    }
                ],
            },
        ).json()
        started = client.post(
            f"/api/deep-analysis/missions/{mission['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        ).json()
        assert [item["logicalPath"] for item in started["sourceManifest"]] == [
            "inputs/cost.csv"
        ]
        execution_prompt = started["workflow"]["nodes"][0]["executionPrompt"]
        assert "- inputs/cost.csv" in execution_prompt
        assert "fileId:" not in execution_prompt
        assert "versionId:" not in execution_prompt
        assert "sha256:" not in execution_prompt
        assert "고정 manifest" not in execution_prompt
        assert uploaded.json()["id"] not in execution_prompt
        assert started["sourceManifest"][0]["versionId"] not in execution_prompt
        assert started["sourceManifest"][0]["contentHash"] not in execution_prompt
        run_id = started["workflow"]["nodes"][0]["runId"]
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            assert run.snapshot_json["project_file_manifest"] == started["sourceManifest"]
        changed_after_start = client.post(
            f"/api/projects/{project_id}/files/{uploaded.json()['id']}/versions",
            headers=headers,
            data={"baseVersion": "1", "changeReason": "Mission 시작 후 변경"},
            files={
                "file": (
                    "cost.csv",
                    "item,previous,current\nA,100,999\nB,200,999\n".encode(),
                    "text/csv",
                )
            },
        )
        assert changed_after_start.status_code == 201, changed_after_start.text

        with SessionLocal() as db:
            run = db.get(Run, run_id)
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert run is not None and user is not None
            result = execute_python_calculation(
                db,
                ManagedLocalStorage(settings.files_dir),
                run=run,
                user=user,
                arguments={
                    "script_name": "variance.py",
                    "result_name": "variance-result.csv",
                    "input_paths": ["inputs/cost.csv"],
                    "script": (
                        "rows = INPUTS['inputs/cost.csv']\n"
                        "RESULT_ROWS = [\n"
                        "    {'item': row['item'], 'variance': float(row['current']) - float(row['previous'])}\n"
                        "    for row in rows\n"
                        "]\n"
                    ),
                },
                max_upload_bytes=settings.max_upload_bytes,
            )
            db.commit()
            assert result["rowCount"] == 2
            assert result["previewRows"] == [
                {"item": "A", "variance": 25.0},
                {"item": "B", "variance": -20.0},
            ]
            paths = list(
                db.scalars(
                    select(ProjectFile.logical_path)
                    .where(ProjectFile.project_id == project_id)
                    .order_by(ProjectFile.logical_path)
                )
            )
            assert any(path.endswith("N001_variance.py") for path in paths)
            assert any(path.endswith("N001_variance-result.csv") for path in paths)


def test_python_calculation_blocks_imports(tmp_path: Path) -> None:
    from lumina.deep_analysis.calculations import _run_script

    try:
        _run_script("import os\nRESULT_ROWS = []", {})
    except ValueError as exc:
        assert "import" in str(exc)
    else:
        raise AssertionError("unsafe import was not blocked")


def test_python_calculation_blocks_oversized_static_repetition(tmp_path: Path) -> None:
    from lumina.deep_analysis.calculations import _run_script

    try:
        _run_script("RESULT_ROWS = [{'value': 'x' * 100001}]", {})
    except ValueError as exc:
        assert "반복 크기" in str(exc)
    else:
        raise AssertionError("oversized static repetition was not blocked")


def test_project_viewer_can_read_but_cannot_mutate_missions(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        owner_headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        viewer = _create_viewer()
        membership = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={"userId": viewer["id"], "role": "viewer"},
        )
        assert membership.status_code == 201, membership.text
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=owner_headers,
            json={"title": "공유 분석"},
        )
        assert created.status_code == 201, created.text
        mission_id = created.json()["id"]

        viewer_headers = _login_viewer(client)
        listing = client.get(f"/api/projects/{project_id}/deep-analysis/missions")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [mission_id]
        assert (
            client.get(f"/api/deep-analysis/missions/{mission_id}").status_code == 200
        )

        create_denied = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=viewer_headers,
            json={"title": "허용되지 않은 분석"},
        )
        assert create_denied.status_code == 404
        update_denied = client.patch(
            f"/api/deep-analysis/missions/{mission_id}",
            headers=viewer_headers,
            json={"expectedRevision": 1, "title": "허용되지 않은 변경"},
        )
        assert update_denied.status_code == 404
        start_denied = client.post(
            f"/api/deep-analysis/missions/{mission_id}/start",
            headers=viewer_headers,
            json={"expectedRevision": 1},
        )
        assert start_denied.status_code == 404
        cancel_denied = client.post(
            f"/api/deep-analysis/missions/{mission_id}/cancel",
            headers=viewer_headers,
            json={"expectedRevision": 1},
        )
        assert cancel_denied.status_code == 404
        delete_denied = client.delete(
            f"/api/deep-analysis/missions/{mission_id}",
            headers=viewer_headers,
            params={"expected_revision": 1},
        )
        assert delete_denied.status_code == 404
