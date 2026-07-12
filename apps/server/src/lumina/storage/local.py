from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
from pathlib import Path

from .base import (
    InvalidStorageKey,
    StorageConflictError,
    StorageError,
    StorageIntegrityError,
    StorageNotFoundError,
    StoredObject,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXTENSION = re.compile(r"^[A-Za-z0-9]{1,16}$")


class ManagedLocalStorage:
    """Local development storage with opaque keys and atomic replacement."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        self._write_lock = threading.RLock()

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        expected_sha256: str | None = None,
        overwrite: bool = False,
    ) -> StoredObject:
        content = bytes(data)
        digest = hashlib.sha256(content).hexdigest()
        if expected_sha256 is not None:
            _validate_digest(expected_sha256)
            if digest != expected_sha256:
                raise StorageIntegrityError(
                    "Content SHA-256 does not match the expected digest."
                )

        target = self._path_for_key(key)
        with self._write_lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            target = self._path_for_key(key)
            if target.exists() and not overwrite:
                existing = self._metadata(key, target)
                if existing.sha256 == digest:
                    return existing
                raise StorageConflictError(
                    f"Storage key already contains different content: {key}"
                )

            fd, temporary_name = tempfile.mkstemp(
                prefix=".lumina-",
                suffix=".tmp",
                dir=target.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                if overwrite:
                    os.replace(temporary, target)
                else:
                    try:
                        os.link(temporary, target)
                    except FileExistsError:
                        existing = self._metadata(key, target)
                        if existing.sha256 == digest:
                            return existing
                        raise StorageConflictError(
                            f"Storage key already contains different content: {key}"
                        ) from None
                    except OSError as exc:
                        raise StorageError(
                            f"Atomic storage commit failed: {key}"
                        ) from exc
                os.chmod(target, 0o600)
                _fsync_directory(target.parent)
            finally:
                temporary.unlink(missing_ok=True)

        return StoredObject(key=key, sha256=digest, size=len(content))

    def read_bytes(self, key: str, *, expected_sha256: str | None = None) -> bytes:
        path = self._path_for_key(key)
        if not path.is_file():
            raise StorageNotFoundError(f"Storage object does not exist: {key}")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if expected_sha256 is not None:
            _validate_digest(expected_sha256)
            if digest != expected_sha256:
                raise StorageIntegrityError(
                    f"Stored content failed SHA-256 verification: {key}"
                )
        return content

    def exists(self, key: str) -> bool:
        return self._path_for_key(key).is_file()

    def delete(self, key: str) -> None:
        path = self._path_for_key(key)
        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise StorageNotFoundError(f"Storage object does not exist: {key}") from exc

    def save_content(
        self,
        namespace: str,
        data: bytes,
        *,
        extension: str | None = None,
    ) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        suffix = ""
        if extension:
            normalized_extension = extension.removeprefix(".")
            if not _EXTENSION.fullmatch(normalized_extension):
                raise InvalidStorageKey(
                    "Storage extension must contain 1-16 ASCII letters or digits."
                )
            suffix = f".{normalized_extension.lower()}"
        key = f"{namespace}/{digest[:2]}/{digest}{suffix}"
        return self.put_bytes(key, data, expected_sha256=digest)

    def metadata(self, key: str) -> StoredObject:
        path = self._path_for_key(key)
        if not path.is_file():
            raise StorageNotFoundError(f"Storage object does not exist: {key}")
        return self._metadata(key, path)

    def _metadata(self, key: str, path: Path) -> StoredObject:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return StoredObject(key=key, sha256=digest.hexdigest(), size=size)

    def _path_for_key(self, key: str) -> Path:
        parts = _validate_key(key)
        candidate = self.root.joinpath(*parts).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise InvalidStorageKey("Storage key escapes the managed root.") from exc
        return candidate


def _validate_key(key: str) -> tuple[str, ...]:
    if not key or key != key.strip():
        raise InvalidStorageKey(
            "Storage key must be non-empty and contain no outer whitespace."
        )
    if "\\" in key or "\x00" in key or ":" in key or key.startswith("/"):
        raise InvalidStorageKey("Storage key must be a relative POSIX-style key.")
    parts = tuple(key.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise InvalidStorageKey("Storage key contains an invalid path segment.")
    return parts


def _validate_digest(value: str) -> None:
    if not _SHA256.fullmatch(value):
        raise StorageIntegrityError(
            "Expected SHA-256 must be 64 lowercase hexadecimal characters."
        )


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
