from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ProjectFile, ProjectFileVersion, User, utc_now
from ..storage import ManagedStorage
from .ledger import list_claims, list_evidence, list_open_issues
from .models import (
    DeepAnalysisMission,
    DeepAnalysisMissionExport,
    DeepAnalysisWorkflowNode,
)
from .quality import list_quality_gates
from .service import active_workflow, list_decisions


_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        + "\n"
    ).encode("utf-8")


def _csv_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def _safe_name(value: str, fallback: str) -> str:
    clean = _UNSAFE_FILENAME.sub("_", value).strip().strip(".")
    return clean[:180] or fallback


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    checksums = {
        name: {"sha256": hashlib.sha256(content).hexdigest(), "sizeBytes": len(content)}
        for name, content in sorted(entries.items())
    }
    entries["checksums.json"] = _json_bytes(
        {
            "algorithm": "SHA-256",
            "scope": "all archive entries except checksums.json",
            "entries": checksums,
        }
    )
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for name, content in sorted(entries.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return output.getvalue()


def _node_payload(node: DeepAnalysisWorkflowNode) -> dict[str, object]:
    return {
        "id": node.id,
        "nodeKey": node.node_key,
        "nodeType": node.node_type,
        "title": node.title,
        "purpose": node.purpose,
        "status": node.status,
        "sequence": node.sequence,
        "position": {"x": node.position_x, "y": node.position_y},
        "config": node.config_json,
        "runId": node.run_id,
        "outputProjectFileId": node.output_project_file_id,
        "outputLogicalPath": node.output_logical_path,
        "outputSummary": node.output_summary,
        "generatedFiles": node.generated_files_json,
        "runHistory": node.run_history_json,
        "actualCostMicrousd": node.actual_cost_microusd,
        "startedAt": node.started_at,
        "finishedAt": node.finished_at,
    }


def _file_versions(
    db: Session,
    *,
    project_file_id: str,
    all_versions: bool,
) -> list[tuple[ProjectFile, ProjectFileVersion]]:
    query = (
        select(ProjectFile, ProjectFileVersion)
        .join(ProjectFileVersion, ProjectFileVersion.project_file_id == ProjectFile.id)
        .where(ProjectFile.id == project_file_id)
    )
    if not all_versions:
        query = query.where(
            ProjectFileVersion.version_number == ProjectFile.current_version_number
        )
    return list(db.execute(query.order_by(ProjectFileVersion.version_number)).tuples())


def create_mission_export(
    db: Session,
    storage: ManagedStorage,
    *,
    mission: DeepAnalysisMission,
    user: User,
    scope: str,
    include_originals: bool,
) -> DeepAnalysisMissionExport:
    if scope not in {"latest", "report_evidence", "audit"}:
        raise ValueError("unsupported export scope")
    export = DeepAnalysisMissionExport(
        mission_id=mission.id,
        requested_by_user_id=user.id,
        scope=scope,
        include_originals=include_originals,
        status="preparing",
    )
    db.add(export)
    db.flush()

    revision, nodes, edges = active_workflow(db, mission.id)
    claims = list_claims(db, mission.id)
    evidence = list_evidence(db, mission.id)
    issues = list_open_issues(db, mission.id)
    decisions = list_decisions(db, mission.id)
    gates = list_quality_gates(db, mission.id)
    entries: dict[str, bytes] = {}
    entries["README.md"] = (
        f"# {mission.title}\n\n"
        f"- Mission ID: `{mission.id}`\n"
        f"- 상태: `{mission.status}`\n"
        f"- 완료 결과: `{mission.completion_outcome or '미확정'}`\n"
        f"- Workflow revision: `{revision.revision_number}`\n"
        f"- Export scope: `{scope}`\n"
        f"- 원본 자료 포함: `{'예' if include_originals else '아니오'}`\n\n"
        "`checksums.json`으로 각 항목의 SHA-256을 검증할 수 있습니다. "
        "Project 원본은 명시적으로 선택한 경우에만 포함됩니다.\n"
    ).encode("utf-8")
    entries["mission.json"] = _json_bytes(
        {
            "id": mission.id,
            "projectId": mission.project_id,
            "title": mission.title,
            "objective": mission.objective,
            "status": mission.status,
            "startMode": mission.start_mode,
            "patternVersionId": mission.pattern_version_id,
            "completionOutcome": mission.completion_outcome,
            "revision": mission.revision,
            "charter": mission.charter_json,
            "completionContract": mission.completion_contract_json,
            "sourceManifest": mission.source_manifest_json,
            "spentMicrousd": mission.spent_microusd,
            "createdAt": mission.created_at,
            "updatedAt": mission.updated_at,
        }
    )
    entries["workflow.json"] = _json_bytes(
        {
            "id": revision.id,
            "revisionNumber": revision.revision_number,
            "state": revision.state,
            "source": revision.source,
            "reason": revision.reason,
            "graphDigest": revision.graph_digest,
            "changeLog": revision.change_log_json,
            "nodes": [_node_payload(node) for node in nodes],
            "edges": [
                {
                    "id": edge.id,
                    "sourceNodeKey": edge.source_node_key,
                    "targetNodeKey": edge.target_node_key,
                    "edgeType": edge.edge_type,
                }
                for edge in edges
            ],
        }
    )
    entries["claims.json"] = _json_bytes(
        [
            {
                "id": claim.id,
                "sourceNodeKey": node_key,
                "statement": claim.statement,
                "level": claim.level,
                "status": claim.status,
                "confidence": claim.confidence,
                "materiality": claim.materiality,
                "staleStatus": claim.stale_status,
                "evidence": [
                    {"evidenceId": item.id, "stance": link.stance, "rationale": link.rationale}
                    for link, item in links
                ],
            }
            for claim, node_key, links in claims
        ]
    )
    entries["evidence-manifest.json"] = _json_bytes(
        [
            {
                "id": item.id,
                "sourceType": item.source_type,
                "stableId": item.stable_id,
                "versionId": item.version_id,
                "contentDigest": item.content_digest,
                "locator": item.locator,
                "title": item.title,
                "metadata": item.metadata_json,
            }
            for item in evidence
        ]
    )
    entries["decisions.csv"] = _csv_bytes(
        ["id", "question", "status", "selectedOptionId", "answer", "requestedByNode", "resolvedAt"],
        [
            [item.id, item.question, item.status, response.selected_option_id if response else "", response.answer_text if response else "", node_key or "", item.resolved_at or ""]
            for item, response, node_key in decisions
        ],
    )
    entries["costs.csv"] = _csv_bytes(
        ["nodeKey", "title", "status", "estimatedMicrousd", "actualMicrousd", "runId"],
        [[node.node_key, node.title, node.status, node.estimated_cost_microusd, node.actual_cost_microusd, node.run_id or ""] for node in nodes],
    )
    entries["open-issues.csv"] = _csv_bytes(
        ["id", "sourceNode", "type", "status", "materiality", "statement", "residualPercent", "requiredAction"],
        [[item.id, node_key or "", item.issue_type, item.status, item.materiality, item.statement, item.residual_percent if item.residual_percent is not None else "", item.required_action] for item, node_key in issues],
    )
    entries["quality-gates.json"] = _json_bytes(
        [{"id": gate.id, "reportNodeKey": node_key, "result": gate.result, "completionOutcome": gate.completion_outcome, "checks": gate.checks_json, "failureReasons": gate.failure_reasons_json, "evaluatedAt": gate.evaluated_at} for gate, node_key in gates]
    )

    file_ids: set[str] = set()
    for node in nodes:
        if scope == "report_evidence" and node.node_type != "report":
            continue
        if node.output_project_file_id:
            file_ids.add(node.output_project_file_id)
        file_ids.update(str(item.get("projectFileId")) for item in node.generated_files_json if item.get("projectFileId"))
    if scope == "report_evidence":
        file_ids.update(item.stable_id for item in evidence if item.source_type == "generated_file")

    used_names: set[str] = set()
    for file_id in sorted(file_ids):
        for project_file, version in _file_versions(db, project_file_id=file_id, all_versions=scope == "audit"):
            name = _safe_name(PurePosixPath(project_file.logical_path).name, file_id)
            if scope == "audit":
                path = PurePosixPath(name)
                name = f"{path.stem}_v{version.version_number}{path.suffix}"
            if name in used_names:
                name = f"{file_id[:8]}_{name}"
            used_names.add(name)
            entries[f"mission-files/{name}"] = storage.read_bytes(version.storage_key, expected_sha256=version.content_hash)

    if include_originals:
        for source in mission.source_manifest_json:
            file_id = str(source.get("projectFileId") or "")
            version_id = str(source.get("versionId") or "")
            row = db.execute(
                select(ProjectFile, ProjectFileVersion)
                .join(ProjectFileVersion, ProjectFileVersion.project_file_id == ProjectFile.id)
                .where(ProjectFile.id == file_id, ProjectFileVersion.id == version_id)
            ).one_or_none()
            if row is None:
                continue
            project_file, version = row
            name = _safe_name(PurePosixPath(project_file.logical_path).name, file_id)
            if scope == "audit":
                path = PurePosixPath(name)
                name = f"{path.stem}_v{version.version_number}{path.suffix}"
            entries[f"source-files/{file_id[:8]}_{name}"] = storage.read_bytes(version.storage_key, expected_sha256=version.content_hash)

    content = _zip_bytes(entries)
    digest = hashlib.sha256(content).hexdigest()
    stored = storage.put_bytes(
        f"deep-analysis-exports/{mission.id}/{export.id}.zip",
        content,
        expected_sha256=digest,
    )
    export.status = "completed"
    export.filename = f"{_safe_name(mission.title, 'mission')}_{mission.id[:8]}.zip"
    export.storage_key = stored.key
    export.content_hash = stored.sha256
    export.size_bytes = stored.size
    export.manifest_json = {"entryCount": len(entries), "scope": scope, "includeOriginals": include_originals}
    export.completed_at = utc_now()
    db.flush()
    return export
