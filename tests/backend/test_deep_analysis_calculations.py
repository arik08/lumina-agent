from __future__ import annotations

import asyncio
import threading
import time

from lumina.deep_analysis import calculations


def test_prepared_python_calculation_does_not_block_event_loop(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking_script(
        _script: str, _inputs: dict[str, list[dict[str, str]]]
    ) -> list[dict[str, int]]:
        started.set()
        if not release.wait(timeout=2):
            raise TimeoutError("test did not release calculation worker")
        return [{"value": 1}]

    monkeypatch.setattr(calculations, "_run_script", blocking_script)
    prepared = calculations.PreparedPythonCalculation(
        script="RESULT_ROWS = []",
        input_paths=(),
        inputs={},
        script_path="analysis/calculation.py",
        result_path="analysis/result.csv",
    )

    async def exercise() -> None:
        task = asyncio.create_task(
            calculations.run_prepared_python_calculation_async(prepared)
        )
        assert await asyncio.to_thread(started.wait, 1)
        before_yield = time.perf_counter()
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.2)
        assert time.perf_counter() - before_yield < 0.1
        release.set()
        completed = await task
        assert completed.rows == [{"value": 1}]
        assert b"value" in completed.result_content

    try:
        asyncio.run(exercise())
    finally:
        release.set()
