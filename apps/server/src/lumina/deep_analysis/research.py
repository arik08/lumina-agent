from __future__ import annotations

from difflib import unified_diff
import re
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Message, ProjectFile, ProjectFileVersion, utc_now
from .models import DeepAnalysisMission, DeepAnalysisWorkflowNode
from .service import active_workflow


_FACT_CANDIDATE = re.compile(
    r"(?:\d{1,3}(?:[,.]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?%|\b(?:19|20)\d{2}\b)"
)
_CITATION_MARKER = re.compile(
    r"(?:https?://|\[\d{1,2}\]|【\d{1,2}】|[①②③④⑤⑥⑦⑧⑨⑩]|\[source:)"
)


def _run_context(
    nodes: list[DeepAnalysisWorkflowNode],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    run_ids: list[str] = []
    context: dict[str, dict[str, Any]] = {}
    for node in nodes:
        for item in node.run_history_json:
            if not isinstance(item, dict) or not item.get("runId"):
                continue
            run_id = str(item["runId"])
            run_ids.append(run_id)
            context[run_id] = {
                "nodeKey": node.node_key,
                "nodeTitle": node.title,
                "attempt": int(item.get("attempt") or 1),
            }
        if node.run_id:
            run_ids.append(node.run_id)
            context[node.run_id] = {
                "nodeKey": node.node_key,
                "nodeTitle": node.title,
                "attempt": len(node.run_history_json) + 1,
            }
    return list(dict.fromkeys(run_ids)), context


def _domain_matches(hostname: str, domain: str) -> bool:
    normalized_host = hostname.casefold().rstrip(".")
    normalized_domain = domain.casefold().rstrip(".")
    return normalized_host == normalized_domain or normalized_host.endswith(
        f".{normalized_domain}"
    )


def _policy_status(source: dict[str, Any], policy: dict[str, Any]) -> str:
    hostname = (urlsplit(str(source.get("normalizedUrl") or "")).hostname or "").casefold()
    if not hostname:
        return "not_applicable"
    included = [str(value) for value in policy.get("domains", []) if value]
    excluded = [str(value) for value in policy.get("excludedDomains", []) if value]
    if any(_domain_matches(hostname, domain) for domain in excluded):
        return "excluded_domain"
    if policy.get("mode") == "restrict" and not any(
        _domain_matches(hostname, domain) for domain in included
    ):
        return "outside_restricted_domains"
    if policy.get("mode") == "prioritize" and included and not any(
        _domain_matches(hostname, domain) for domain in included
    ):
        return "supplemental_domain"
    return "allowed"


def mission_research_inspector(
    db: Session, mission: DeepAnalysisMission
) -> dict[str, Any]:
    _revision, nodes, _edges = active_workflow(db, mission.id)
    run_ids, run_context = _run_context(nodes)
    messages = (
        list(
            db.scalars(
                select(Message)
                .where(
                    Message.run_id.in_(run_ids),
                    Message.role == "assistant",
                    Message.status == "completed",
                )
                .order_by(Message.created_at, Message.id)
            )
        )
        if run_ids
        else []
    )
    settings = mission.execution_settings_json or {}
    policy = settings.get("webSourcePolicy")
    if not isinstance(policy, dict):
        policy = {"mode": "all", "domains": [], "excludedDomains": []}

    sources: list[dict[str, Any]] = []
    source_positions: dict[str, int] = {}
    citations: list[dict[str, Any]] = []
    verification_states: set[str] = set()
    for message in messages:
        metadata = message.metadata_json or {}
        verification = str(metadata.get("researchVerification") or "")
        if verification:
            verification_states.add(verification)
        context = run_context.get(str(message.run_id), {})
        for raw in metadata.get("sources", []):
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("sourceId") or raw.get("normalizedUrl") or "")
            if not key:
                continue
            occurrence = {
                **context,
                "runId": message.run_id,
                "messageId": message.id,
            }
            position = source_positions.get(key)
            if position is None:
                item = dict(raw)
                item["sourceKind"] = "web"
                item["occurrences"] = [occurrence]
                item["policyStatus"] = _policy_status(item, policy)
                source_positions[key] = len(sources)
                sources.append(item)
            else:
                sources[position]["occurrences"].append(occurrence)
                if raw.get("citationStatus") == "cited":
                    sources[position]["citationStatus"] = "cited"
        for raw in metadata.get("citations", []):
            if isinstance(raw, dict):
                citations.append({**raw, **context, "runId": message.run_id})

    combined_output = "\n".join(node.output_markdown for node in nodes if node.output_markdown)
    for raw in mission.source_manifest_json:
        if not isinstance(raw, dict) or not raw.get("projectFileId"):
            continue
        logical_path = str(raw.get("logicalPath") or "")
        cited = bool(logical_path and logical_path in combined_output)
        source_id = f"project:{raw['projectFileId']}:{raw.get('contentHash') or ''}"
        sources.append(
            {
                "sourceId": source_id,
                "sourceKind": "project_file",
                "title": logical_path,
                "logicalPath": logical_path,
                "projectFileId": raw["projectFileId"],
                "version": raw.get("version"),
                "contentHash": raw.get("contentHash"),
                "citationStatus": "cited" if cited else "reference_only",
                "policyStatus": "not_applicable",
                "occurrences": [],
            }
        )

    fact_candidates: list[dict[str, Any]] = []
    for node in nodes:
        if node.node_type != "report" or not node.output_markdown:
            continue
        in_code_fence = False
        for line_number, raw_line in enumerate(node.output_markdown.splitlines(), start=1):
            line = raw_line.strip()
            if line.startswith("```"):
                in_code_fence = not in_code_fence
                continue
            if (
                in_code_fence
                or not line
                or line.startswith("#")
                or set(line) <= {"|", "-", ":", " "}
                or not _FACT_CANDIDATE.search(line)
                or _CITATION_MARKER.search(line)
            ):
                continue
            fact_candidates.append(
                {
                    "nodeKey": node.node_key,
                    "lineNumber": line_number,
                    "text": line[:280],
                    "status": "citation_review_needed",
                }
            )
            if len(fact_candidates) >= 30:
                break

    cited_count = sum(item.get("citationStatus") == "cited" for item in sources)
    policy_violations = [
        item
        for item in sources
        if item.get("policyStatus") in {"excluded_domain", "outside_restricted_domains"}
    ]
    return {
        "missionId": mission.id,
        "generatedAt": utc_now(),
        "summary": {
            "sourceCount": len(sources),
            "citedSourceCount": cited_count,
            "referenceOnlyCount": len(sources) - cited_count,
            "webSourceCount": sum(item.get("sourceKind") == "web" for item in sources),
            "projectSourceCount": sum(
                item.get("sourceKind") == "project_file" for item in sources
            ),
            "citationCount": len(citations),
            "citationReviewNeededCount": len(fact_candidates),
            "policyViolationCount": len(policy_violations),
            "researchVerification": sorted(verification_states),
        },
        "sources": sources,
        "citations": citations,
        "citationReviewCandidates": fact_candidates,
    }


def _report_diff(
    db: Session, nodes: list[DeepAnalysisWorkflowNode]
) -> dict[str, Any]:
    outputs: list[tuple[str, int, str]] = []
    for node in nodes:
        if node.node_type != "report":
            continue
        attempts = [
            (int(item.get("attempt") or 1), str(item.get("runId") or ""))
            for item in node.run_history_json
            if isinstance(item, dict) and item.get("runId")
        ]
        if node.run_id:
            attempts.append((len(node.run_history_json) + 1, node.run_id))
        run_ids = [run_id for _attempt, run_id in attempts]
        message_by_run = {
            str(message.run_id): message.canonical_text
            for message in db.scalars(
                select(Message)
                .where(
                    Message.run_id.in_(run_ids),
                    Message.role == "assistant",
                    Message.status == "completed",
                )
                .order_by(Message.created_at, Message.id)
            )
        } if run_ids else {}
        for attempt, run_id in attempts:
            text = message_by_run.get(run_id, "")
            if text:
                outputs.append((node.node_key, attempt, text))
    if len(outputs) < 2:
        return {"available": False, "addedLines": 0, "removedLines": 0, "lines": []}
    previous = outputs[-2]
    current = outputs[-1]
    all_lines = list(
        unified_diff(
            previous[2].splitlines(),
            current[2].splitlines(),
            fromfile=f"{previous[0]} attempt {previous[1]}",
            tofile=f"{current[0]} attempt {current[1]}",
            lineterm="",
        )
    )
    visible_lines = all_lines[:400]
    return {
        "available": True,
        "fromAttempt": previous[1],
        "toAttempt": current[1],
        "addedLines": sum(line.startswith("+") and not line.startswith("+++") for line in all_lines),
        "removedLines": sum(line.startswith("-") and not line.startswith("---") for line in all_lines),
        "truncated": len(all_lines) > len(visible_lines),
        "lines": visible_lines,
    }


def mission_refresh_preview(
    db: Session, mission: DeepAnalysisMission
) -> dict[str, Any]:
    _revision, nodes, _edges = active_workflow(db, mission.id)
    file_ids = [
        str(item.get("projectFileId"))
        for item in mission.source_manifest_json
        if isinstance(item, dict) and item.get("projectFileId")
    ]
    rows: list[tuple[ProjectFile, ProjectFileVersion]] = (
        list(
            db.execute(
                select(ProjectFile, ProjectFileVersion)
                .join(
                    ProjectFileVersion,
                    (ProjectFileVersion.project_file_id == ProjectFile.id)
                    & (
                        ProjectFileVersion.version_number
                        == ProjectFile.current_version_number
                    ),
                )
                .where(
                    ProjectFile.project_id == mission.project_id,
                    ProjectFile.id.in_(file_ids),
                    ProjectFile.deleted_at.is_(None),
                )
            ).tuples()
        )
        if file_ids
        else []
    )
    current = {project_file.id: (project_file, version) for project_file, version in rows}
    changed_sources: list[dict[str, Any]] = []
    refreshed_manifest: list[dict[str, Any]] = []
    missing_source_count = 0
    for raw in mission.source_manifest_json:
        if not isinstance(raw, dict) or not raw.get("projectFileId"):
            continue
        file_id = str(raw["projectFileId"])
        latest = current.get(file_id)
        if latest is None:
            missing_source_count += 1
            changed_sources.append(
                {
                    "projectFileId": file_id,
                    "logicalPath": raw.get("logicalPath"),
                    "status": "missing",
                    "fromVersion": raw.get("version"),
                    "toVersion": None,
                }
            )
            continue
        project_file, version = latest
        refreshed = {
            "projectFileId": project_file.id,
            "logicalPath": project_file.logical_path,
            "version": version.version_number,
            "versionId": version.id,
            "contentHash": version.content_hash,
            "mimeType": version.mime_type,
            "sizeBytes": version.size_bytes,
        }
        refreshed_manifest.append(refreshed)
        if str(raw.get("contentHash") or "") != version.content_hash:
            changed_sources.append(
                {
                    "projectFileId": project_file.id,
                    "logicalPath": project_file.logical_path,
                    "status": "changed",
                    "fromVersion": raw.get("version"),
                    "toVersion": version.version_number,
                    "fromContentHash": raw.get("contentHash"),
                    "toContentHash": version.content_hash,
                }
            )
    has_refreshable_changes = any(
        item.get("status") == "changed" for item in changed_sources
    )
    return {
        "missionId": mission.id,
        "checkedAt": utc_now(),
        "hasChanges": bool(changed_sources),
        "canRefresh": has_refreshable_changes and missing_source_count == 0,
        "changedSources": changed_sources,
        "missingSourceCount": missing_source_count,
        "affectedNodeKeys": [node.node_key for node in nodes] if changed_sources else [],
        "refreshedSourceManifest": refreshed_manifest,
        "reportDiff": _report_diff(db, nodes),
    }


__all__ = ["mission_refresh_preview", "mission_research_inspector"]
