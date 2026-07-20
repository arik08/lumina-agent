from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any


class RunEventBroker:
    """Process-local wake-up hints; the database remains the event source of truth."""

    def __init__(self) -> None:
        self._conditions: dict[str, asyncio.Condition] = {}
        self._waiters: dict[str, int] = {}
        self._wake_revisions: dict[str, int] = {}
        self._durable_revisions: dict[str, int] = {}
        self._next_wake_revision = 0
        self._artifact_progress_revisions: dict[str, int] = {}
        self._artifact_progress: dict[str, tuple[int, dict[str, Any]]] = {}
        self._assistant_draft_revisions: dict[str, int] = {}
        self._assistant_drafts: dict[str, tuple[int, str, str, list[str]]] = {}

    def seed_assistant_draft(self, run_id: str, message_id: str, text: str) -> None:
        """Seed recovered durable text before newly streamed deltas arrive."""
        if not text or run_id in self._assistant_drafts:
            return
        self._assistant_draft_revisions[run_id] = 0
        self._assistant_drafts[run_id] = (0, message_id, text, [])

    async def publish_assistant_draft(
        self, run_id: str, message_id: str, delta: str
    ) -> None:
        """Publish an append-only live draft without durable write amplification."""
        if not delta:
            return
        revision = self._assistant_draft_revisions.get(run_id, 0) + 1
        self._assistant_draft_revisions[run_id] = revision
        current = self._assistant_drafts.get(run_id)
        if current is None or current[1] != message_id:
            base_text = ""
            chunks = [delta]
        else:
            base_text = current[2]
            chunks = current[3]
            chunks.append(delta)
        self._assistant_drafts[run_id] = (
            revision,
            message_id,
            base_text,
            chunks,
        )
        await self._notify(run_id, durable=False)

    def latest_assistant_draft(
        self, run_id: str, *, after_revision: int = 0
    ) -> tuple[int, dict[str, str | bool]] | None:
        current = self._assistant_drafts.get(run_id)
        if current is None or current[0] <= after_revision:
            return None
        revision, message_id, base_text, chunks = current
        append = after_revision > 0
        text = "".join(chunks[after_revision:]) if append else base_text + "".join(chunks)
        return revision, {"messageId": message_id, "text": text, "append": append}

    def clear_assistant_draft(self, run_id: str) -> None:
        self._assistant_drafts.pop(run_id, None)
        self._assistant_draft_revisions.pop(run_id, None)

    async def publish_artifact_progress(
        self, run_id: str, payload: Mapping[str, Any]
    ) -> None:
        """Publish high-frequency progress without turning every frame into audit history."""
        revision = self._artifact_progress_revisions.get(run_id, 0) + 1
        self._artifact_progress_revisions[run_id] = revision
        self._artifact_progress[run_id] = (revision, dict(payload))
        await self._notify(run_id, durable=False)

    def latest_artifact_progress(
        self, run_id: str, *, after_revision: int = 0
    ) -> tuple[int, dict[str, Any]] | None:
        current = self._artifact_progress.get(run_id)
        if current is None or current[0] <= after_revision:
            return None
        return current[0], dict(current[1])

    def clear_artifact_progress(self, run_id: str) -> None:
        self._artifact_progress.pop(run_id, None)
        self._artifact_progress_revisions.pop(run_id, None)

    async def notify(self, run_id: str) -> None:
        await self._notify(run_id, durable=True)

    async def _notify(self, run_id: str, *, durable: bool) -> None:
        self._next_wake_revision += 1
        self._wake_revisions[run_id] = self._next_wake_revision
        if durable:
            self._durable_revisions[run_id] = self._next_wake_revision
        condition = self._conditions.get(run_id)
        if condition is None:
            return
        async with condition:
            condition.notify_all()

    def revisions(self, run_id: str) -> tuple[int, int]:
        return (
            self._wake_revisions.get(run_id, 0),
            self._durable_revisions.get(run_id, 0),
        )

    async def wait(
        self,
        run_id: str,
        timeout: float = 15.0,
        *,
        after_revision: int | None = None,
    ) -> tuple[int, bool]:
        condition = self._conditions.setdefault(run_id, asyncio.Condition())
        self._waiters[run_id] = self._waiters.get(run_id, 0) + 1
        timed_out = False
        try:
            async with condition:
                expected_revision = (
                    self._wake_revisions.get(run_id, 0)
                    if after_revision is None
                    else after_revision
                )
                if self._wake_revisions.get(run_id, 0) <= expected_revision:
                    try:
                        await asyncio.wait_for(condition.wait(), timeout=timeout)
                    except TimeoutError:
                        timed_out = True
                return self._wake_revisions.get(run_id, 0), timed_out
        finally:
            remaining = self._waiters.get(run_id, 1) - 1
            if remaining <= 0:
                self._waiters.pop(run_id, None)
                if self._conditions.get(run_id) is condition:
                    self._conditions.pop(run_id, None)
            else:
                self._waiters[run_id] = remaining

    def discard(self, run_id: str) -> None:
        self._conditions.pop(run_id, None)
        self._waiters.pop(run_id, None)
        self._wake_revisions.pop(run_id, None)
        self._durable_revisions.pop(run_id, None)
        self.clear_artifact_progress(run_id)
        self.clear_assistant_draft(run_id)


event_broker = RunEventBroker()
