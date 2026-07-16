from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from lumina.artifacts.service import create_artifact
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.models import Artifact, ArtifactVersion, Project, User
from lumina.storage import ManagedLocalStorage


@pytest.mark.parametrize("failure_stage", ["version", "current_version"])
def test_artifact_version_flush_failure_cleans_managed_content(
    tmp_path: Path, failure_stage: str
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'artifact-cleanup.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    storage = ManagedLocalStorage(settings.artifacts_dir)

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert user is not None
        project = db.scalar(select(Project).where(Project.owner_user_id == user.id))
        assert project is not None
        real_flush = db.flush

        def fail_version_flush(*args: object, **kwargs: object) -> None:
            version_pending = any(isinstance(item, ArtifactVersion) for item in db.new)
            current_version_pending = any(
                isinstance(item, Artifact) and item.current_version_number == 1
                for item in db.dirty
            )
            if (failure_stage == "version" and version_pending) or (
                failure_stage == "current_version" and current_version_pending
            ):
                raise RuntimeError(f"forced artifact {failure_stage} flush failure")
            real_flush(*args, **kwargs)

        with patch.object(db, "flush", side_effect=fail_version_flush):
            with pytest.raises(
                RuntimeError, match=f"forced artifact {failure_stage} flush failure"
            ):
                create_artifact(
                    db,
                    storage,
                    user=user,
                    project_id=project.id,
                    conversation_id=None,
                    source_run_id=None,
                    display_name="정리 검증.html",
                    kind="html",
                    mime_type="text/html",
                    content=(
                        b"<!doctype html><html><head><title>cleanup</title></head>"
                        b"<body>cleanup</body></html>"
                    ),
                )

    assert not [path for path in settings.artifacts_dir.rglob("*") if path.is_file()]
