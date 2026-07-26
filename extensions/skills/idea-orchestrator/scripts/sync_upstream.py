from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse


SKILL_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = SKILL_ROOT / "references"
MANIFEST_PATH = REFERENCES / "upstream-sources.json"
ALLOWED_HOST = "raw.githubusercontent.com"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest() -> dict[str, object]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("files"), list):
        raise ValueError("upstream-sources.json must contain a files array")
    revision = str(manifest.get("revision", ""))
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise ValueError("revision must be a pinned lowercase 40-character Git commit")
    return manifest


def safe_target(name: str) -> Path:
    if Path(name).name != name or not name.startswith("upstream-"):
        raise ValueError(f"unsafe target name: {name}")
    target = (REFERENCES / name).resolve()
    if target.parent != REFERENCES.resolve():
        raise ValueError(f"target escapes references directory: {name}")
    return target


def entries(manifest: dict[str, object]):
    for raw in manifest["files"]:  # type: ignore[index]
        if not isinstance(raw, dict):
            raise ValueError("each files entry must be an object")
        source = str(raw.get("source", ""))
        target = safe_target(str(raw.get("target", "")))
        expected = str(raw.get("sha256", ""))
        if not source or source.startswith(("/", "\\")) or ".." in Path(source).parts:
            raise ValueError(f"unsafe source path: {source}")
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise ValueError(f"invalid SHA-256 for {source}")
        yield source, target, expected


def check() -> int:
    failures = 0
    for source, target, expected in entries(load_manifest()):
        if not target.is_file():
            print(f"MISSING {target.relative_to(SKILL_ROOT)} ({source})")
            failures += 1
            continue
        actual = sha256(target.read_bytes())
        if actual != expected:
            print(f"MISMATCH {target.relative_to(SKILL_ROOT)} expected={expected} actual={actual}")
            failures += 1
        else:
            print(f"OK {target.relative_to(SKILL_ROOT)}")
    return 1 if failures else 0


def sync() -> int:
    manifest = load_manifest()
    revision = str(manifest["revision"])
    base = f"https://{ALLOWED_HOST}/neurofoo/agent-skills/{revision}/"
    staged: list[tuple[Path, bytes]] = []
    for source, target, expected in entries(manifest):
        url = base + "/".join(quote(part, safe="") for part in source.split("/"))
        if urlparse(url).hostname != ALLOWED_HOST:
            raise ValueError(f"unexpected download host: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "Lumina-Idea-Orchestrator-Sync/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read()
        actual = sha256(data)
        if actual != expected:
            raise ValueError(f"digest mismatch for {source}: expected {expected}, got {actual}")
        staged.append((target, data))
    for target, data in staged:
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
        print(f"SYNCED {target.relative_to(SKILL_ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify or refresh pinned upstream method cards.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Verify local files without network access.")
    mode.add_argument("--sync", action="store_true", help="Download pinned files and verify SHA-256.")
    args = parser.parse_args()
    try:
        return check() if args.check else sync()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
