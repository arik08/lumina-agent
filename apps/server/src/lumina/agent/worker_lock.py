"""Cross-platform ownership lock for the modular-monolith Run worker."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.engine import make_url


class _DatabaseWorkerLock:
    """Keep one local Run executor per SQLite database process group."""

    def __init__(self, database_url: str) -> None:
        url = make_url(database_url)
        database = url.database
        if url.get_backend_name() == "sqlite" and database and database != ":memory:":
            database_path = Path(database).resolve()
            self.path: Path | None = database_path.with_suffix(
                f"{database_path.suffix}.worker.lock"
            )
        else:
            self.path = None
        self._handle: BinaryIO | None = None

    def acquire(self) -> bool:
        if self.path is None or self._handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                flock = getattr(fcntl, "flock")
                flock(
                    handle.fileno(),
                    getattr(fcntl, "LOCK_EX") | getattr(fcntl, "LOCK_NB"),
                )
        except (BlockingIOError, OSError):
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                getattr(fcntl, "flock")(handle.fileno(), getattr(fcntl, "LOCK_UN"))
        finally:
            handle.close()
