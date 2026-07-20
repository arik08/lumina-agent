from __future__ import annotations

import asyncio


class RunEventBroker:
    """Process-local wake-up hints; the database remains the event source of truth."""

    def __init__(self) -> None:
        self._conditions: dict[str, asyncio.Condition] = {}
        self._waiters: dict[str, int] = {}

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


event_broker = RunEventBroker()
