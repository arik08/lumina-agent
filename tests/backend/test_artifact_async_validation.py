from __future__ import annotations

import asyncio
import hashlib
import threading
import time

import pytest

from lumina.artifacts import service


def test_artifact_validation_does_not_block_event_loop(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking_validation(
        *, kind: str, mime_type: str, content: bytes
    ) -> service.ArtifactValidation:
        assert (kind, mime_type, content) == ("pdf", "application/pdf", b"pdf")
        started.set()
        if not release.wait(timeout=2):
            raise TimeoutError("test did not release validation worker")
        return "passed", {"contentHash": hashlib.sha256(content).hexdigest()}

    monkeypatch.setattr(service, "validate_artifact_content", blocking_validation)

    async def exercise() -> None:
        task = asyncio.create_task(
            service.validate_artifact_content_async(
                kind="pdf", mime_type="application/pdf", content=b"pdf"
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        before_yield = time.perf_counter()
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.2)
        assert time.perf_counter() - before_yield < 0.1
        release.set()
        status, validation = await task
        assert status == "passed"
        assert validation["contentHash"] == hashlib.sha256(b"pdf").hexdigest()

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_precomputed_artifact_validation_must_match_content() -> None:
    with pytest.raises(ValueError, match="does not match"):
        service._resolve_artifact_validation(
            kind="pdf",
            mime_type="application/pdf",
            content=b"current",
            precomputed=(
                "passed",
                {"contentHash": hashlib.sha256(b"stale").hexdigest()},
            ),
        )
