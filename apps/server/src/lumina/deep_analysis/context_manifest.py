from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ProjectFile, ProjectFileVersion, Run
from .models import (
    DeepAnalysisContextManifest,
    DeepAnalysisMission,
    DeepAnalysisMissionFileLink,
    DeepAnalysisWorkflowNode,
)


def stable_prefix_hash(
    mission: DeepAnalysisMission,
    *,
    tool_profile: str,
) -> str:
    context_revision = int(
        mission.charter_json.get("confirmedMissionRevision") or mission.revision
    )
    canonical = json.dumps(
        {
            "schema": 1,
            "organizationId": mission.organization_id,
            "projectId": mission.project_id,
            "missionId": mission.id,
            "missionContextRevision": context_revision,
            "autonomyMode": mission.autonomy_mode,
            "toolProfile": tool_profile,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def persist_context_manifest(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    run: Run,
    files: list[dict[str, Any]],
    tool_profile: str,
    dynamic_context_characters: int,
) -> DeepAnalysisContextManifest:
    existing = db.scalar(
        select(DeepAnalysisContextManifest).where(
            DeepAnalysisContextManifest.run_id == run.id
        )
    )
    if existing is not None:
        return existing
    items = [
        {
            "kind": "exact",
            "stableId": item.get("projectFileId"),
            "versionId": item.get("versionId"),
            "contentDigest": item.get("contentHash"),
            "logicalPath": item.get("logicalPath"),
            "role": "dependency_output" if item.get("generated") else "mission_source",
            "order": index,
        }
        for index, item in enumerate(files)
    ]
    context_revision = int(
        mission.charter_json.get("confirmedMissionRevision") or mission.revision
    )
    manifest = DeepAnalysisContextManifest(
        mission_id=mission.id,
        node_id=node.id,
        run_id=run.id,
        mission_context_revision=context_revision,
        prefix_hash=stable_prefix_hash(mission, tool_profile=tool_profile),
        tool_profile=tool_profile,
        item_count=len(items),
        token_estimate=max(0, round(dynamic_context_characters / 4)),
        items_json=items,
        lineage_json={
            "workflowRevisionId": node.workflow_revision_id,
            "nodeKey": node.node_key,
            "sourceManifestFrozen": True,
            "compressionApplied": False,
        },
    )
    db.add(manifest)
    db.flush()
    for item in files:
        if item.get("projectFileId") and item.get("versionId"):
            link_file(
                db,
                mission=mission,
                project_file_id=str(item["projectFileId"]),
                version_id=str(item["versionId"]),
                node=None,
                run=None,
                purpose="dependency_input" if item.get("generated") else "source_reference",
                validation_status="exact_version",
                metadata={"logicalPath": item.get("logicalPath")},
            )
    return manifest


def link_file(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    project_file_id: str,
    version_id: str,
    node: DeepAnalysisWorkflowNode | None,
    run: Run | None,
    purpose: str,
    validation_status: str,
    metadata: dict[str, Any] | None = None,
) -> DeepAnalysisMissionFileLink:
    existing = db.scalar(
        select(DeepAnalysisMissionFileLink).where(
            DeepAnalysisMissionFileLink.mission_id == mission.id,
            DeepAnalysisMissionFileLink.project_file_id == project_file_id,
            DeepAnalysisMissionFileLink.project_file_version_id == version_id,
            DeepAnalysisMissionFileLink.purpose == purpose,
            DeepAnalysisMissionFileLink.producing_run_id
            == (run.id if run is not None else None),
        )
    )
    if existing is not None:
        return existing
    link = DeepAnalysisMissionFileLink(
        mission_id=mission.id,
        project_file_id=project_file_id,
        project_file_version_id=version_id,
        producing_node_id=node.id if node is not None else None,
        producing_run_id=run.id if run is not None else None,
        purpose=purpose,
        validation_status=validation_status,
        stale_status="fresh",
        metadata_json=metadata or {},
    )
    db.add(link)
    db.flush()
    return link


def current_file_version(
    db: Session, project_file_id: str
) -> tuple[ProjectFile, ProjectFileVersion] | None:
    return db.execute(
        select(ProjectFile, ProjectFileVersion)
        .join(
            ProjectFileVersion,
            (ProjectFileVersion.project_file_id == ProjectFile.id)
            & (ProjectFileVersion.version_number == ProjectFile.current_version_number),
        )
        .where(ProjectFile.id == project_file_id)
    ).one_or_none()
