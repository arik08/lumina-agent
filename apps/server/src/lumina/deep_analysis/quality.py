from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import utc_now
from .models import (
    DeepAnalysisDecision,
    DeepAnalysisMission,
    DeepAnalysisQualityGateResult,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowRevision,
)


def list_quality_gates(
    db: Session, mission_id: str
) -> list[tuple[DeepAnalysisQualityGateResult, str | None]]:
    gates = list(
        db.scalars(
            select(DeepAnalysisQualityGateResult)
            .where(DeepAnalysisQualityGateResult.mission_id == mission_id)
            .order_by(
                DeepAnalysisQualityGateResult.created_at,
                DeepAnalysisQualityGateResult.id,
            )
        )
    )
    node_ids = [gate.report_node_id for gate in gates if gate.report_node_id]
    node_keys = (
        {
            node.id: node.node_key
            for node in db.scalars(
                select(DeepAnalysisWorkflowNode).where(
                    DeepAnalysisWorkflowNode.id.in_(node_ids)
                )
            )
        }
        if node_ids
        else {}
    )
    return [(gate, node_keys.get(gate.report_node_id)) for gate in gates]


def _check(
    check_id: str,
    passed: bool,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "passed" if passed else "failed",
        "message": message,
        "details": details,
    }


def evaluate_quality_gate(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    revision: DeepAnalysisWorkflowRevision,
    report_node: DeepAnalysisWorkflowNode,
    nodes: list[DeepAnalysisWorkflowNode],
) -> DeepAnalysisQualityGateResult:
    contract = dict(mission.completion_contract_json)
    charter = dict(mission.charter_json)
    checks: list[dict[str, Any]] = []

    checks.append(
        _check(
            "mission_charter",
            bool(charter.get("confirmed")) and bool(str(charter.get("purpose") or "").strip()),
            "Mission Charter가 실행 시작 시 확정되어야 합니다.",
        )
    )
    unhealthy = [
        node.node_key
        for node in nodes
        if node.status in {"failed", "cancelled", "stale", "validation_failed"}
    ]
    checks.append(
        _check(
            "node_health",
            not bool(contract.get("requireNoFailedNodes", True)) or not unhealthy,
            "실패·중단·stale Node가 없어야 합니다.",
            nodeKeys=unhealthy,
        )
    )
    required_types = {
        str(item)
        for item in contract.get("requiredNodeTypes", [])
        if str(item).strip()
    }
    completed_types = {
        node.node_type for node in nodes if node.status == "completed"
    }
    missing_types = sorted(required_types - completed_types)
    checks.append(
        _check(
            "required_node_types",
            not missing_types,
            "Completion Contract의 필수 Node 종류가 완료되어야 합니다.",
            missingNodeTypes=missing_types,
        )
    )
    require_report = bool(contract.get("requireReport", True))
    report_present = bool(
        report_node.output_project_file_id and report_node.output_markdown.strip()
    )
    checks.append(
        _check(
            "report_output",
            not require_report or report_present,
            "최종 보고서 Markdown과 저장 파일이 있어야 합니다.",
        )
    )
    required_sections = [
        str(item).strip()
        for item in contract.get("requiredSections", [])
        if str(item).strip()
    ]
    normalized_report = report_node.output_markdown.casefold()
    missing_sections = [
        section for section in required_sections if section.casefold() not in normalized_report
    ]
    checks.append(
        _check(
            "required_report_sections",
            not missing_sections,
            "보고서에 합의한 필수 섹션이 포함되어야 합니다.",
            missingSections=missing_sections,
        )
    )
    minimum_coverage = float(contract.get("minimumEvidenceCoverage") or 0.0)
    measured_coverage = float(contract.get("measuredEvidenceCoverage") or 0.0)
    checks.append(
        _check(
            "evidence_coverage",
            measured_coverage >= minimum_coverage,
            "핵심 Claim의 Evidence coverage가 기준 이상이어야 합니다.",
            minimum=minimum_coverage,
            measured=measured_coverage,
        )
    )
    maximum_open_issues = int(contract.get("maximumOpenIssues") or 0)
    measured_open_issues = int(contract.get("measuredOpenIssues") or 0)
    checks.append(
        _check(
            "open_issues",
            measured_open_issues <= maximum_open_issues,
            "미해결 항목 수가 허용 한도 이하여야 합니다.",
            maximum=maximum_open_issues,
            measured=measured_open_issues,
        )
    )
    maximum_residual = contract.get("maximumUnexplainedResidualPercent")
    measured_residual = contract.get("measuredUnexplainedResidualPercent")
    residual_passed = maximum_residual is None or (
        measured_residual is not None
        and float(measured_residual) <= float(maximum_residual)
    )
    checks.append(
        _check(
            "numeric_reconciliation",
            residual_passed,
            "미설명 수치 잔차가 허용 비율 이하여야 합니다.",
            maximumPercent=maximum_residual,
            measuredPercent=measured_residual,
        )
    )
    requires_review = bool(contract.get("requiresFinalReview", False))
    checks.append(
        _check(
            "final_review",
            not requires_review,
            "최종 사용자 검토가 필요합니다.",
        )
    )

    failed_checks = [item for item in checks if item["status"] == "failed"]
    gate = DeepAnalysisQualityGateResult(
        mission_id=mission.id,
        workflow_revision_id=revision.id,
        report_node_id=report_node.id,
        result="passed" if not failed_checks else "failed",
        completion_outcome="satisfied" if not failed_checks else "not_satisfied",
        checks_json=checks,
        failure_reasons_json=[str(item["message"]) for item in failed_checks],
        evaluated_at=utc_now(),
    )
    db.add(gate)
    db.flush()

    if not failed_checks:
        mission.status = "completed"
        mission.completion_outcome = "satisfied"
        quality_status = "passed"
    elif bool(contract.get("allowWaiver", True)):
        decision = DeepAnalysisDecision(
            mission_id=mission.id,
            workflow_revision_id=revision.id,
            requested_by_node_id=report_node.id,
            question="Completion Contract 미충족 항목을 예외로 승인하고 종료할까요?",
            options_json=[
                {
                    "id": "accept_exceptions",
                    "label": "예외를 기록하고 종료",
                    "description": "미충족 항목과 위험을 남기고 결과를 확정합니다.",
                },
                {
                    "id": "keep_open",
                    "label": "미충족 상태로 유지",
                    "description": "영향 Node를 보완하거나 다시 실행할 수 있게 열어 둡니다.",
                },
            ],
            recommendation_option_id="keep_open",
            recommendation_rationale="완료 기준을 충족한 뒤 확정하는 편이 결과 신뢰도가 높습니다.",
            impact_json={
                "kind": "quality_gate_waiver",
                "qualityGateResultId": gate.id,
            },
            affected_node_keys_json=[report_node.node_key],
            status="pending",
        )
        db.add(decision)
        mission.status = "awaiting_input"
        mission.completion_outcome = None
        quality_status = "waiver_required"
    else:
        mission.status = "blocked"
        mission.completion_outcome = "not_satisfied"
        quality_status = "failed"

    mission.completion_contract_json = {
        **contract,
        "qualityGate": quality_status,
        "latestQualityGateResultId": gate.id,
        "finalOutputFileId": report_node.output_project_file_id,
        "finalOutputPath": report_node.output_logical_path,
    }
    db.flush()
    return gate


def resolve_quality_gate_decision(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    decision: DeepAnalysisDecision,
    selected_option_id: str,
) -> None:
    source_gate_id = str(decision.impact_json.get("qualityGateResultId") or "")
    source_gate = db.get(DeepAnalysisQualityGateResult, source_gate_id)
    if source_gate is None or source_gate.mission_id != mission.id:
        mission.status = "blocked"
        mission.completion_outcome = "not_satisfied"
        return
    if selected_option_id == "accept_exceptions":
        waived = DeepAnalysisQualityGateResult(
            mission_id=mission.id,
            workflow_revision_id=source_gate.workflow_revision_id,
            report_node_id=source_gate.report_node_id,
            parent_result_id=source_gate.id,
            waiver_decision_id=decision.id,
            result="waived",
            completion_outcome="satisfied_with_exceptions",
            checks_json=list(source_gate.checks_json),
            failure_reasons_json=list(source_gate.failure_reasons_json),
            evaluated_at=utc_now(),
        )
        db.add(waived)
        db.flush()
        mission.status = "completed"
        mission.completion_outcome = "satisfied_with_exceptions"
        mission.completion_contract_json = {
            **mission.completion_contract_json,
            "qualityGate": "waived",
            "latestQualityGateResultId": waived.id,
            "waiverDecisionId": decision.id,
        }
    else:
        mission.status = "blocked"
        mission.completion_outcome = "not_satisfied"
        mission.completion_contract_json = {
            **mission.completion_contract_json,
            "qualityGate": "failed",
            "waiverDecisionId": decision.id,
        }
