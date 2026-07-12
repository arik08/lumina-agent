from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lumina.storage import (
    InvalidStorageKey,
    ManagedLocalStorage,
    StorageConflictError,
    StorageIntegrityError,
)


def test_local_storage_writes_atomically_and_verifies_hash(tmp_path: Path) -> None:
    storage = ManagedLocalStorage(tmp_path / "managed")
    content = "설비 점검 결과".encode()
    expected = hashlib.sha256(content).hexdigest()

    stored = storage.put_bytes(
        "artifacts/session-1/report.html",
        content,
        expected_sha256=expected,
    )

    assert stored.sha256 == expected
    assert stored.size == len(content)
    assert storage.read_bytes(stored.key, expected_sha256=expected) == content
    assert storage.metadata(stored.key) == stored
    assert not list((tmp_path / "managed").rglob(".lumina-*.tmp"))


@pytest.mark.parametrize(
    "key",
    [
        "../outside.txt",
        "nested/../../outside.txt",
        "/absolute.txt",
        "C:/windows.txt",
        r"nested\windows.txt",
        "nested//empty.txt",
        "nested/./dot.txt",
        " trailing.txt",
    ],
)
def test_local_storage_rejects_path_traversal_and_ambiguous_keys(
    tmp_path: Path,
    key: str,
) -> None:
    storage = ManagedLocalStorage(tmp_path / "managed")
    with pytest.raises(InvalidStorageKey):
        storage.put_bytes(key, b"blocked")


def test_local_storage_is_immutable_by_default(tmp_path: Path) -> None:
    storage = ManagedLocalStorage(tmp_path / "managed")
    key = "files/project-1/source.md"
    first = storage.put_bytes(key, b"first")

    assert storage.put_bytes(key, b"first") == first
    with pytest.raises(StorageConflictError):
        storage.put_bytes(key, b"second")
    assert storage.read_bytes(key) == b"first"


def test_hash_mismatch_does_not_create_an_object(tmp_path: Path) -> None:
    storage = ManagedLocalStorage(tmp_path / "managed")
    key = "attachments/upload.bin"
    with pytest.raises(StorageIntegrityError, match="does not match"):
        storage.put_bytes(key, b"content", expected_sha256="0" * 64)
    assert not storage.exists(key)


def test_content_addressed_save_is_repeatable(tmp_path: Path) -> None:
    storage = ManagedLocalStorage(tmp_path / "managed")
    first = storage.save_content("artifacts", b"same content", extension="HTML")
    second = storage.save_content("artifacts", b"same content", extension="html")

    assert first == second
    assert first.key.endswith(".html")
    assert (
        storage.read_bytes(first.key, expected_sha256=first.sha256) == b"same content"
    )


def test_read_detects_tampering(tmp_path: Path) -> None:
    root = tmp_path / "managed"
    storage = ManagedLocalStorage(root)
    stored = storage.put_bytes("artifacts/result.txt", b"original")
    (root / "artifacts" / "result.txt").write_bytes(b"tampered")

    with pytest.raises(StorageIntegrityError, match="failed"):
        storage.read_bytes(stored.key, expected_sha256=stored.sha256)
