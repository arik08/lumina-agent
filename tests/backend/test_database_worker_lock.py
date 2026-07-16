from __future__ import annotations

from pathlib import Path

from lumina.agent.executor import _DatabaseWorkerLock


def test_sqlite_worker_lock_is_exclusive_and_reusable(tmp_path: Path) -> None:
    database_path = tmp_path / "worker-lock.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    first = _DatabaseWorkerLock(database_url)
    second = _DatabaseWorkerLock(database_url)

    try:
        assert first.path == database_path.with_suffix(".db.worker.lock")
        assert first.acquire() is True
        assert first.acquire() is True
        assert second.acquire() is False

        first.release()

        assert second.acquire() is True
    finally:
        first.release()
        second.release()


def test_non_file_database_does_not_create_worker_lock() -> None:
    for database_url in (
        "sqlite:///:memory:",
        "postgresql+psycopg://user:password@localhost/lumina",
    ):
        worker_lock = _DatabaseWorkerLock(database_url)
        assert worker_lock.path is None
        assert worker_lock.acquire() is True
        worker_lock.release()
