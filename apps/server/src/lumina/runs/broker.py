from __future__ import annotations

import asyncio
from collections import defaultdict


class RunEventBroker:
    """Process-local wake-up hints; the database remains the event source of truth."""

    def __init__(self) -> None:
        self._conditions: dict[str, asyncio.Condition] = defaultdict(asyncio.Condition)

    async def notify(self, run_id: str) -> None:
        condition = self._conditions[run_id]
        async with condition:
            condition.notify_all()

    async def wait(self, run_id: str, timeout: float = 15.0) -> None:
        condition = self._conditions[run_id]
        async with condition:
            try:
                await asyncio.wait_for(condition.wait(), timeout=timeout)
            except TimeoutError:
                return

    def discard(self, run_id: str) -> None:
        self._conditions.pop(run_id, None)


event_broker = RunEventBroker()
