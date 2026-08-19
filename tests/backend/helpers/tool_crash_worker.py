from __future__ import annotations

import sys
import time
from pathlib import Path

from sqlalchemy import select

from lumina.agent.executor import LocalRunExecutor
from lumina.agent.tool_runtime_policy import tool_replay_policy
from lumina.config import Settings
from lumina.db import SessionLocal, configure_database
from lumina.models import Run


def main() -> None:
    database_path = Path(sys.argv[1]).resolve()
    data_dir = Path(sys.argv[2]).resolve()
    run_id = sys.argv[3]
    phase = sys.argv[4]
    marker_path = Path(sys.argv[5]).resolve()
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        data_dir=data_dir,
        files_dir=data_dir / "files",
        artifacts_dir=data_dir / "artifacts",
        cookie_secure=False,
    )
    configure_database(settings.database_url)
    executor = LocalRunExecutor(settings)
    with SessionLocal() as db:
        run = db.scalar(select(Run).where(Run.id == run_id))
        if run is None:
            raise RuntimeError("Crash-test Run does not exist")
        run.worker_id = executor._worker_id
        db.commit()

    call = {
        "id": f"subprocess-{phase}-call",
        "name": (
            "write_file" if phase in {"running", "external_effect"} else "web_search"
        ),
    }
    arguments = (
        {"path": "crash-result.txt", "content": "safe"}
        if phase in {"running", "external_effect"}
        else {"query": "steel"}
    )
    tool_id = executor._start_tool_execution_database(
        run_id,
        call,
        arguments,
        tool_replay_policy(str(call["name"])),
    )
    if phase == "external_effect":
        (data_dir / "external-side-effect.txt").write_text(
            "invoked-once", encoding="utf-8"
        )
    elif phase == "completed":
        executor._complete_tool_execution_database(
            run_id,
            tool_id,
            {"items": ["persisted-before-process-kill"]},
            "Crash-test result persisted.",
            None,
            None,
        )
    elif phase != "running":
        raise ValueError(f"Unsupported crash-test phase: {phase}")

    marker_path.write_text(phase, encoding="utf-8")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
