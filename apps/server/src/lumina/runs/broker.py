from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any


class RunEventBroker:
    """Process-local wake-up hints; the database remains the event source of truth."""

    def __init__(self) -> None:
        self._conditions: dict[str, asyncio.Condition] = {}
        self._waiters: dict[str, int] = {}
        self._artifact_progress_revisions: dict[str, int] = {}
        self._artifact_progress: dict[str, tuple[int, dict[str, Any]]] = {}

    async def publish_artifact_progress(
        self, run_id: str, payload: Mapping[str, Any]
    ) -> None:
        """Publish high-frequency progress without turning every frame into audit history."""
        revision = self._artifact_progress_revisions.get(run_id, 0) + 1
        self._artifact_progress_revisions[run_id] = revision
        self._artifact_progress[run_id] = (revision, dict(payload))
        await self.notify(run_id)

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
        condition = self._conditions.get(run_id)
        if condition is None:
            return
        async with condition:
            condition.notify_all()

    async def wait(self, run_id: str, timeout: float = 15.0) -> None:
        condition = self._conditions.setdefault(run_id, asyncio.Condition())
        self._waiters[run_id] = self._waiters.get(run_id, 0) + 1
        try:
            async with condition:
                try:
                    await asyncio.wait_for(condition.wait(), timeout=timeout)
                except TimeoutError:
                    return
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
        self.clear_artifact_progress(run_id)


event_broker = RunEventBroker()
