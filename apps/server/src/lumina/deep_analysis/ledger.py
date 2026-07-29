from __future__ import annotations

import json
import re
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ProjectFile, ProjectFileVersion
from .models import (
    DeepAnalysisClaim,
    DeepAnalysisClaimEvidenceLink,
    DeepAnalysisEvidenceReference,
    DeepAnalysisMission,
    DeepAnalysisOpenIssue,
    DeepAnalysisWorkflowNode,
)


_LEDGER_PATTERN = re.compile(
    r"<!--\s*LUMINA_ANALYSIS_LEDGER\s*(\{.*?\})\s*-->",
    re.IGNORECASE | re.DOTALL,
)
_CLAIM_LEVELS = {
    "observation",
    "supporting_finding",
    "key_finding",
    "recommendation",
}
_CLAIM_STATUSES = {
    "proposed",
    "supported",
    "verified",
    "disputed",
    "unresolved",
    "rejected",
}
_MATERIALITIES = {"low", "medium", "high", "critical"}
_STANCES = {"support", "contradict", "context"}
_SOURCE_TYPES = {"project_file", "generated_file", "node_output", "external"}
_ISSUE_TYPES = {
    "unexplained_residual",
    "missing_data",
    "contradiction",
    "low_confidence",
    "excluded_scope",
    "follow_up",
}


def list_claims(
    db: Session, mission_id: str
) -> list[
    tuple[
        DeepAnalysisClaim,
        str | None,
        list[tuple[DeepAnalysisClaimEvidenceLink, DeepAnalysisEvidenceReference]],
    ]
]:
    claims = list(
        db.scalars(
            select(DeepAnalysisClaim)
            .where(DeepAnalysisClaim.mission_id == mission_id)
            .order_by(DeepAnalysisClaim.created_at, DeepAnalysisClaim.id)
        )
    )
    if not claims:
        return []
    claim_ids = [claim.id for claim in claims]
    rows = list(
        db.execute(
            select(DeepAnalysisClaimEvidenceLink, DeepAnalysisEvidenceReference)
            .join(
                DeepAnalysisEvidenceReference,
                DeepAnalysisEvidenceReference.id
                == DeepAnalysisClaimEvidenceLink.evidence_id,
            )
            .where(DeepAnalysisClaimEvidenceLink.claim_id.in_(claim_ids))
            .order_by(DeepAnalysisClaimEvidenceLink.created_at)
        ).tuples()
    )
    evidence_by_claim: dict[
        str,
        list[tuple[DeepAnalysisClaimEvidenceLink, DeepAnalysisEvidenceReference]],
    ] = {}
    for link, evidence in rows:
        evidence_by_claim.setdefault(link.claim_id, []).append((link, evidence))
    node_ids = [claim.source_node_id for claim in claims if claim.source_node_id]
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
    return [
        (
            claim,
            (
                node_keys.get(claim.source_node_id)
                if claim.source_node_id is not None
                else None
            ),
            evidence_by_claim.get(claim.id, []),
        )
        for claim in claims
    ]


def list_evidence(
    db: Session, mission_id: str
) -> list[DeepAnalysisEvidenceReference]:
    return list(
        db.scalars(
            select(DeepAnalysisEvidenceReference)
            .where(DeepAnalysisEvidenceReference.mission_id == mission_id)
            .order_by(
                DeepAnalysisEvidenceReference.created_at,
                DeepAnalysisEvidenceReference.id,
            )
        )
    )


def list_open_issues(
    db: Session, mission_id: str
) -> list[tuple[DeepAnalysisOpenIssue, str | None]]:
    issues = list(
        db.scalars(
            select(DeepAnalysisOpenIssue)
            .where(DeepAnalysisOpenIssue.mission_id == mission_id)
            .order_by(DeepAnalysisOpenIssue.created_at, DeepAnalysisOpenIssue.id)
        )
    )
    node_ids = [issue.source_node_id for issue in issues if issue.source_node_id]
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
    return [
        (
            issue,
            node_keys.get(issue.source_node_id)
            if issue.source_node_id is not None
            else None,
        )
        for issue in issues
    ]


def ledger_instruction(node: DeepAnalysisWorkflowNode) -> str:
    return f"""

Claim·Evidence 기록:
- 이번 Node에서 검증 가능한 관찰·핵심 원인·권고가 생기면 Markdown 끝에 아래 HTML 주석을 하나 추가하십시오. 저장 전에 주석은 분리됩니다.
- Evidence의 stableId는 manifest의 fileId, 생성 파일의 Project file ID, 선행 Node key 또는 외부 URL이어야 합니다. Project 파일은 exact versionId·contentDigest·locator를 함께 기록하십시오.
- 확인하지 못한 사항은 Claim으로 확정하지 말고 openIssues에 남기십시오. 근거 없는 Claim은 verified로 표시하지 마십시오.
- 이번 Node에서 새 Claim이나 Open Issue가 없으면 빈 배열을 사용하십시오.
<!-- LUMINA_ANALYSIS_LEDGER
{{"claims":[{{"ref":"C1","statement":"검증 가능한 결론","level":"observation|supporting_finding|key_finding|recommendation","status":"proposed|supported|verified|disputed|unresolved|rejected","confidence":0.0,"materiality":"low|medium|high|critical","reportInclusion":"executive_summary","validation":{{"method":"검증 방법"}},"evidence":[{{"sourceType":"project_file|generated_file|node_output|external","stableId":"exact ID 또는 {node.node_key}","versionId":"exact version ID","contentDigest":"sha256","locator":"행·열·페이지·URL fragment","title":"근거 이름","stance":"support|contradict|context","rationale":"연결 이유"}}]}}],"openIssues":[{{"issueType":"unexplained_residual|missing_data|contradiction|low_confidence|excluded_scope|follow_up","statement":"미해결 내용","materiality":"low|medium|high|critical","residualAmount":null,"residualPercent":null,"requiredAction":"필요한 후속 조치","reportInclusion":"open_issues"}}]}}
-->
"""


def extract_analysis_ledger(markdown: str) -> tuple[str, dict[str, Any]]:
    match = _LEDGER_PATTERN.search(markdown)
    clean = _LEDGER_PATTERN.sub("", markdown).rstrip()
    if match is None:
        return clean, {"claims": [], "openIssues": []}
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError:
        return clean, {"claims": [], "openIssues": []}

    claims: list[dict[str, Any]] = []
    raw_claims = raw.get("claims") if isinstance(raw.get("claims"), list) else []
    for item in raw_claims:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or "").strip()[:4000]
        if not statement:
            continue
        level = str(item.get("level") or "observation")
        status = str(item.get("status") or "proposed")
        materiality = str(item.get("materiality") or "medium")
        try:
            confidence = min(
                1.0, max(0.0, float(cast(Any, item.get("confidence"))))
            )
        except (TypeError, ValueError):
            confidence = None
        evidence: list[dict[str, str | None]] = []
        evidence_value = item.get("evidence")
        raw_evidence: list[Any] = (
            evidence_value if isinstance(evidence_value, list) else []
        )
        for evidence_item in raw_evidence:
            if not isinstance(evidence_item, dict):
                continue
            source_type = str(evidence_item.get("sourceType") or "")
            stable_id = str(evidence_item.get("stableId") or "").strip()[:1000]
            stance = str(evidence_item.get("stance") or "context")
            if (
                source_type not in _SOURCE_TYPES
                or not stable_id
                or stance not in _STANCES
            ):
                continue
            evidence.append(
                {
                    "sourceType": source_type,
                    "stableId": stable_id,
                    "versionId": str(evidence_item.get("versionId") or "")[:128]
                    or None,
                    "contentDigest": str(
                        evidence_item.get("contentDigest") or ""
                    )[:128]
                    or None,
                    "locator": str(evidence_item.get("locator") or "")[:4000],
                    "title": str(evidence_item.get("title") or "")[:500],
                    "stance": stance,
                    "rationale": str(evidence_item.get("rationale") or "")[:2000],
                }
            )
            if len(evidence) >= 8:
                break
        claims.append(
            {
                "statement": statement,
                "level": level if level in _CLAIM_LEVELS else "observation",
                "status": status if status in _CLAIM_STATUSES else "proposed",
                "confidence": confidence,
                "materiality": (
                    materiality if materiality in _MATERIALITIES else "medium"
                ),
                "reportInclusion": str(item.get("reportInclusion") or "")[:80],
                "validation": (
                    dict(validation_value)
                    if isinstance(
                        validation_value := item.get("validation"),
                        dict,
                    )
                    else {}
                ),
                "evidence": evidence,
            }
        )
        if len(claims) >= 12:
            break

    issues: list[dict[str, Any]] = []
    raw_issues = (
        raw.get("openIssues") if isinstance(raw.get("openIssues"), list) else []
    )
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or "").strip()[:4000]
        if not statement:
            continue
        issue_type = str(item.get("issueType") or "follow_up")
        materiality = str(item.get("materiality") or "medium")
        issues.append(
            {
                "issueType": (
                    issue_type if issue_type in _ISSUE_TYPES else "follow_up"
                ),
                "statement": statement,
                "materiality": (
                    materiality if materiality in _MATERIALITIES else "medium"
                ),
                "residualAmount": _optional_float(item.get("residualAmount")),
                "residualPercent": _optional_float(item.get("residualPercent")),
                "requiredAction": str(item.get("requiredAction") or "")[:4000],
                "reportInclusion": str(
                    item.get("reportInclusion") or "open_issues"
                )[:80],
            }
        )
        if len(issues) >= 12:
            break
    return clean, {"claims": claims, "openIssues": issues}


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _file_evidence(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    source_type: str,
    stable_id: str,
    requested_version_id: str | None,
    requested_digest: str | None,
) -> tuple[str, str, str, str] | None:
    from .execution import output_directory

    project_file = db.get(ProjectFile, stable_id)
    if (
        project_file is None
        or project_file.project_id != mission.project_id
        or project_file.deleted_at is not None
    ):
        return None
    if source_type == "project_file":
        manifest = next(
            (
                item
                for item in mission.source_manifest_json
                if item.get("projectFileId") == stable_id
            ),
            None,
        )
        if manifest is None:
            return None
        version_id = str(manifest.get("versionId") or "")
        digest = str(manifest.get("contentHash") or "")
        if requested_version_id and requested_version_id != version_id:
            return None
        if requested_digest and requested_digest != digest:
            return None
        return version_id, digest, project_file.logical_path, str(manifest.get("version"))
    if not project_file.logical_path.startswith(f"{output_directory(mission)}/"):
        return None
    version = db.scalar(
        select(ProjectFileVersion).where(
            ProjectFileVersion.project_file_id == project_file.id,
            ProjectFileVersion.version_number == project_file.current_version_number,
        )
    )
    if version is None:
        return None
    if requested_version_id and requested_version_id != version.id:
        return None
    if requested_digest and requested_digest != version.content_hash:
        return None
    return version.id, version.content_hash, project_file.logical_path, str(version.version_number)


def _node_evidence(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    stable_id: str,
) -> tuple[str, str, str, str, str] | None:
    from .execution import output_directory

    row = db.execute(
        select(DeepAnalysisWorkflowNode, ProjectFile, ProjectFileVersion)
        .join(ProjectFile, ProjectFile.id == DeepAnalysisWorkflowNode.output_project_file_id)
        .join(
            ProjectFileVersion,
            (ProjectFileVersion.project_file_id == ProjectFile.id)
            & (ProjectFileVersion.version_number == ProjectFile.current_version_number),
        )
        .where(
            DeepAnalysisWorkflowNode.node_key == stable_id,
            ProjectFile.project_id == mission.project_id,
            ProjectFile.logical_path.startswith(f"{output_directory(mission)}/"),
        )
    ).one_or_none()
    if row is None:
        return None
    node, project_file, version = row
    return node.id, version.id, version.content_hash, project_file.logical_path, str(version.version_number)


def persist_analysis_ledger(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    ledger: dict[str, Any],
) -> None:
    for item in ledger.get("claims", []):
        claim = DeepAnalysisClaim(
            mission_id=mission.id,
            source_node_id=node.id,
            statement=item["statement"],
            level=item["level"],
            status=item["status"],
            confidence=item["confidence"],
            materiality=item["materiality"],
            report_inclusion=item["reportInclusion"],
            validation_json=item["validation"],
        )
        db.add(claim)
        db.flush()
        support_count = 0
        for raw_evidence in item["evidence"]:
            source_type = str(raw_evidence["sourceType"])
            stable_id = str(raw_evidence["stableId"])
            source_node_id: str | None = None
            version_id = raw_evidence.get("versionId")
            digest = raw_evidence.get("contentDigest")
            title = str(raw_evidence.get("title") or stable_id)
            metadata: dict[str, Any] = {}
            if source_type in {"project_file", "generated_file"}:
                resolved = _file_evidence(
                    db,
                    mission=mission,
                    source_type=source_type,
                    stable_id=stable_id,
                    requested_version_id=version_id,
                    requested_digest=digest,
                )
                if resolved is None:
                    continue
                version_id, digest, path, version_number = resolved
                title = title or path
                metadata = {"logicalPath": path, "version": version_number}
            elif source_type == "node_output":
                resolved_node = _node_evidence(
                    db, mission=mission, stable_id=stable_id
                )
                if resolved_node is None:
                    continue
                source_node_id, version_id, digest, path, version_number = resolved_node
                title = title or path
                metadata = {
                    "logicalPath": path,
                    "version": version_number,
                    "nodeKey": stable_id,
                }
            elif not (version_id or digest) or not raw_evidence.get("locator"):
                continue
            evidence = db.scalar(
                select(DeepAnalysisEvidenceReference).where(
                    DeepAnalysisEvidenceReference.mission_id == mission.id,
                    DeepAnalysisEvidenceReference.source_type == source_type,
                    DeepAnalysisEvidenceReference.stable_id == stable_id,
                    DeepAnalysisEvidenceReference.version_id == version_id,
                    DeepAnalysisEvidenceReference.content_digest == digest,
                    DeepAnalysisEvidenceReference.locator
                    == str(raw_evidence.get("locator") or ""),
                )
            )
            if evidence is None:
                evidence = DeepAnalysisEvidenceReference(
                    mission_id=mission.id,
                    source_node_id=source_node_id,
                    source_type=source_type,
                    stable_id=stable_id,
                    version_id=version_id,
                    content_digest=digest,
                    locator=str(raw_evidence.get("locator") or ""),
                    title=title,
                    metadata_json=metadata,
                )
                db.add(evidence)
                db.flush()
            db.add(
                DeepAnalysisClaimEvidenceLink(
                    claim_id=claim.id,
                    evidence_id=evidence.id,
                    stance=str(raw_evidence["stance"]),
                    rationale=str(raw_evidence.get("rationale") or ""),
                )
            )
            if raw_evidence["stance"] == "support":
                support_count += 1
        if claim.status == "verified" and support_count == 0:
            claim.status = "proposed"
            claim.validation_json = {
                **claim.validation_json,
                "downgradedReason": "verified Claim에 exact supporting Evidence가 없습니다.",
            }

    for item in ledger.get("openIssues", []):
        db.add(
            DeepAnalysisOpenIssue(
                mission_id=mission.id,
                source_node_id=node.id,
                issue_type=item["issueType"],
                statement=item["statement"],
                materiality=item["materiality"],
                residual_amount=item["residualAmount"],
                residual_percent=item["residualPercent"],
                required_action=item["requiredAction"],
                report_inclusion=item["reportInclusion"],
            )
        )
    db.flush()


def claim_context(db: Session, mission_id: str) -> str:
    claims = list(
        db.scalars(
            select(DeepAnalysisClaim)
            .where(
                DeepAnalysisClaim.mission_id == mission_id,
                DeepAnalysisClaim.stale_status == "fresh",
                DeepAnalysisClaim.status.not_in({"rejected"}),
            )
            .order_by(DeepAnalysisClaim.created_at, DeepAnalysisClaim.id)
        )
    )
    issues = list(
        db.scalars(
            select(DeepAnalysisOpenIssue)
            .where(
                DeepAnalysisOpenIssue.mission_id == mission_id,
                DeepAnalysisOpenIssue.status == "open",
            )
            .order_by(DeepAnalysisOpenIssue.created_at, DeepAnalysisOpenIssue.id)
        )
    )
    lines = [
        f"- [Claim:{claim.id}] {claim.level}/{claim.status}: {claim.statement}"
        for claim in claims[-80:]
    ]
    issue_lines = [
        f"- [Issue:{issue.id}] {issue.issue_type}: {issue.statement}"
        for issue in issues[-40:]
    ]
    return (
        "현재 Claim Ledger(보고서에서 관련 문장 뒤에 [Claim:ID]를 유지):\n"
        + ("\n".join(lines) if lines else "- 아직 등록된 Claim이 없습니다.")
        + "\n현재 Open Issue:\n"
        + ("\n".join(issue_lines) if issue_lines else "- 없음")
    )
