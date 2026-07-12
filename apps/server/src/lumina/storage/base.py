from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class StorageError(RuntimeError):
    """Base error for managed content storage."""


class InvalidStorageKey(StorageError):
    pass


class StorageNotFoundError(StorageError):
    pass


class StorageConflictError(StorageError):
    pass


class StorageIntegrityError(StorageError):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    sha256: str
    size: int


@runtime_checkable
class ManagedStorage(Protocol):
    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        expected_sha256: str | None = None,
        overwrite: bool = False,
    ) -> StoredObject: ...

    def read_bytes(self, key: str, *, expected_sha256: str | None = None) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...
