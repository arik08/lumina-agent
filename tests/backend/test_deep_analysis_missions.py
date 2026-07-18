from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.auth.service import create_user
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.deep_analysis.calculations import execute_python_calculation
from lumina.deep_analysis.models import (
    DeepAnalysisClaim,
    DeepAnalysisDecision,
    DeepAnalysisDecisionResponse,
    DeepAnalysisMission,
    DeepAnalysisWorkflowEdge,
    DeepAnalysisWorkflowNode,
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
    Run,
    User,
)
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
        assert [node["nodeKey"] for node in mission["workflow"]["nodes"]] == [
            "N001",
            "N010",
            "N020",
            "N025",
            "N030",
            "N035",
            "N040",
        ]
        assert len(mission["workflow"]["edges"]) == 7
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
        assert detail["workflow"]["changeLog"][-1]["action"] == "question_updated"
        assert "의사결정형" in detail["workflow"]["reason"]


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
        outgoing: dict[str, int] = {}
        incoming: dict[str, int] = {}
        for source, target in plan_edges(plan):
            outgoing[source] = outgoing.get(source, 0) + 1
            incoming[target] = incoming.get(target, 0) + 1
        assert max(outgoing.values()) >= 2, plan.kind
        assert max(incoming.values()) >= 2, plan.kind


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

        rerun = client.post(
            f"/api/deep-analysis/missions/{created['id']}/quality-gate",
            headers=headers,
            json={"expectedRevision": resolved["revision"]},
        )
        assert rerun.status_code == 200, rerun.text
        assert rerun.json()["status"] == "awaiting_input"
        assert rerun.json()["qualityGates"][-1]["result"] == "failed"


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
        assert restored["qualityGates"][-1]["result"] == "passed"
        assert all(
            node["status"] == "completed" for node in restored["workflow"]["nodes"]
        )
        assert all(node["runId"] for node in restored["workflow"]["nodes"])
        assert all(node["outputMarkdown"] for node in restored["workflow"]["nodes"])
        assert all(
            node["outputLogicalPath"].startswith("심층분석/실행 가능한 분석_")
            for node in restored["workflow"]["nodes"]
        )
        assert restored["completionContract"]["finalOutputPath"].endswith(
            "N040_최종 보고서.md"
        )

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
        output_path = (
            f"심층분석/삭제할 분석_{mission['id'][:8]}/N001_목표·범위 확정.md"
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

        started = client.post(
            f"/api/deep-analysis/missions/{created['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "running"
        assert started.json()["executionAvailable"] is True
        assert started.json()["revision"] == 2
        assert started.json()["charter"]["confirmed"] is True
        assert started.json()["workflow"]["nodes"][0]["status"] == "running"

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
        cancelled = client.post(
            f"/api/deep-analysis/missions/{created['id']}/cancel",
            headers=headers,
            json={"expectedRevision": 2},
        ).json()

        with SessionLocal() as db:
            source_node = db.scalar(
                select(DeepAnalysisWorkflowNode).where(
                    DeepAnalysisWorkflowNode.run_id == first_run_id
                )
            )
            assert source_node is not None
            stale_claim = DeepAnalysisClaim(
                mission_id=created["id"],
                source_node_id=source_node.id,
                statement="재실행 전 결론",
                level="key_finding",
                status="supported",
                confidence=0.8,
                materiality="high",
                report_inclusion="executive_summary",
                validation_json={},
            )
            db.add(stale_claim)
            db.commit()
            stale_claim_id = stale_claim.id

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
        with SessionLocal() as db:
            refreshed_claim = db.get(DeepAnalysisClaim, stale_claim_id)
            assert refreshed_claim is not None
            assert refreshed_claim.stale_status == "review_required"


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
            json={"title": "원가 계산"},
        ).json()
        started = client.post(
            f"/api/deep-analysis/missions/{mission['id']}/start",
            headers=headers,
            json={"expectedRevision": 1},
        ).json()
        assert [item["logicalPath"] for item in started["sourceManifest"]] == [
            "inputs/cost.csv"
        ]
        run_id = started["workflow"]["nodes"][0]["runId"]
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
