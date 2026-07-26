from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Artifact, ArtifactVersion
from .storage import ManagedLocalStorage, StorageError


logger = logging.getLogger(__name__)
_MAX_CITATION_ARTIFACT_BYTES = 5_000_000
_CITATION_ARTIFACT_MIME_TYPES = frozenset(
    {"text/html", "text/markdown", "text/plain", "application/xhtml+xml"}
)


def run_artifact_citation_texts(
    db: Session, storage: ManagedLocalStorage, run_ids: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    ordered_run_ids = tuple(dict.fromkeys(run_ids))
    if not ordered_run_ids:
        return {}
    rows = db.execute(
        select(Artifact, ArtifactVersion)
        .join(
            ArtifactVersion,
            (ArtifactVersion.artifact_id == Artifact.id)
            & (ArtifactVersion.version_number == Artifact.current_version_number),
        )
        .where(
            Artifact.source_run_id.in_(ordered_run_ids),
            Artifact.deleted_at.is_(None),
            Artifact.mime_type.in_(_CITATION_ARTIFACT_MIME_TYPES),
            ArtifactVersion.size_bytes <= _MAX_CITATION_ARTIFACT_BYTES,
        )
        .order_by(Artifact.created_at, Artifact.id)
    ).all()
    texts_by_run: dict[str, list[str]] = {}
    for artifact, version in rows:
        if artifact.source_run_id is None:
            continue
        try:
            content = storage.read_bytes(
                version.storage_key, expected_sha256=version.content_hash
            )
        except StorageError:
            logger.warning(
                "Skipping unavailable artifact content while resolving citations",
                extra={
                    "run_id": artifact.source_run_id,
                    "artifact_version_id": version.id,
                },
            )
            continue
        texts_by_run.setdefault(artifact.source_run_id, []).append(
            content.decode("utf-8-sig", errors="replace")
        )
    return {run_id: tuple(texts) for run_id, texts in texts_by_run.items()}


__all__ = ["run_artifact_citation_texts"]
