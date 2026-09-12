"""Apply the small Lumina compatibility patch, then start korean-law-mcp."""

from __future__ import annotations

import subprocess
import hashlib
import shutil
import sys
from pathlib import Path


RUNTIME = Path(__file__).resolve().parent


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(
            f"Unsupported korean-law-mcp runtime: patch anchor missing in {path}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def apply_compatibility_patch(runtime: Path = RUNTIME) -> None:
    package = runtime / "node_modules" / "korean-law-mcp" / "build"
    _replace_once(
        package / "tools" / "search.js",
        "let xmlText = await apiClient.searchLaw(input.query, input.apiKey, input.display);",
        "let xmlText = await apiClient.searchLaw(input.query, input.apiKey, Math.max(input.display, 50));",
    )
    annex_path = package / "tools" / "annex.js"
    if "const normalizeName = (value)" not in annex_path.read_text(encoding="utf-8"):
        _replace_once(
            annex_path,
            """    // 쿼리에서 단어 추출
    const queryWords = queryName.split(/\\s+/).filter((w) => w.length > 0);""",
            """    // 법제처 별표 검색은 부분 LIKE 결과를 섞으므로 정확한 관련법령명을 먼저 고른다.
    const normalizeName = (value) => String(value || \"\").replace(/<[^>]+>/g, \"\").replace(/\\s+/g, \"\").trim();
    const queryKey = normalizeName(queryName);
    const exact = annexList.filter((annex) => normalizeName(annex.관련자치법규명 || annex.관련법령명 || annex.관련행정규칙명) === queryKey);
    if (exact.length > 0)
        return exact;
    // 쿼리에서 단어 추출
    const queryWords = queryName.split(/\\s+/).filter((w) => w.length > 0);""",
        )
    _replace_once(
        package / "tools" / "annex.js",
        """    if (exact.length > 0)
        return exact;
    // 쿼리에서 단어 추출""",
        """    if (exact.length > 0)
        return exact;
    // 관련법령명이 있는 결과가 모두 불일치하면 부분 LIKE 오탐이므로 버린다.
    if (queryKey && annexList.some((annex) => normalizeName(annex.관련자치법규명 || annex.관련법령명 || annex.관련행정규칙명)))
        return [];
    // 쿼리에서 단어 추출""",
    )
    # eflaw requires efYd with MST. The promulgation-date endpoint accepts MST
    # alone and retains that exact version instead of substituting today's ID.
    _replace_once(
        package / "lib" / "api-client.js",
        '            target: "eflaw",',
        '            target: params.mst && !params.efYd ? "law" : "eflaw",',
    )
    law_text = package / "tools" / "law-text.js"
    _replace_once(
        law_text,
        "    jo: z.string().optional().describe(",
        '    search: z.string().optional().describe("조문 제목 검색어. 공백으로 구분한 검색어 중 하나와 일치하는 조문 본문을 반환"),\n'
        "    jo: z.string().optional().describe(",
    )
    _replace_once(
        law_text,
        "${input.efYd || 'current'}`;",
        "${input.efYd || 'current'}:${input.search || ''}`;",
    )
    _replace_once(
        law_text,
        "        if (articleUnits.length === 0) {",
        """        if (input.search?.trim()) {
            const terms = input.search.trim().split(/\\s+/);
            articleUnits = articleUnits.filter(unit => unit.조문여부 === "조문"
                && terms.some(term => String(unit.조문제목 || "").includes(term)));
        }
        if (articleUnits.length === 0) {""",
    )
    _replace_once(
        law_text,
        "        if (!input.jo && articleUnits.length > 20) {",
        "        if (!input.jo && !input.search && articleUnits.length > 20) {",
    )
    _replace_once(
        package / "tools" / "scenarios" / "penalty.js",
        '            search: "벌칙",',
        '            search: "벌칙 과태료 과징금",',
    )


def prepare_runtime(runtime: Path = RUNTIME, *, offline: bool = False) -> None:
    """Install the locked, platform-specific dependencies before MCP startup."""
    lock_hash = hashlib.sha256((runtime / "package-lock.json").read_bytes()).hexdigest()
    marker = runtime / "node_modules" / ".lumina-lock-sha256"
    entrypoint = runtime / "node_modules" / "korean-law-mcp" / "build" / "index.js"
    if (
        not entrypoint.is_file()
        or not marker.is_file()
        or marker.read_text() != lock_hash
    ):
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            raise RuntimeError("Node.js/npm is required to prepare korean-law MCP")
        subprocess.run(
            [
                npm,
                "ci",
                "--omit=dev",
                "--no-audit",
                "--no-fund",
                *(["--offline"] if offline else []),
            ],
            cwd=runtime,
            check=True,
            stdout=sys.stderr,
            stderr=sys.stderr,
            timeout=600,
        )
        apply_compatibility_patch(runtime)
        marker.write_text(lock_hash, encoding="ascii")
    else:
        apply_compatibility_patch(runtime)


def main() -> int:
    if "--prepare" in sys.argv[1:]:
        prepare_runtime(offline="--offline" in sys.argv[1:])
        return 0
    entrypoint = RUNTIME / "node_modules" / "korean-law-mcp" / "build" / "index.js"
    if not entrypoint.is_file():
        raise RuntimeError(
            "korean-law dependencies are missing. Run installer.bat or "
            "python extensions/mcp/korean-law/runtime/bootstrap.py --prepare from the repository root."
        )
    marker = RUNTIME / "node_modules" / ".lumina-lock-sha256"
    digest = hashlib.sha256((RUNTIME / "package-lock.json").read_bytes()).hexdigest()
    if not marker.is_file() or marker.read_text(encoding="ascii") != digest:
        raise RuntimeError("korean-law dependencies are stale. Run installer.bat.")
    return subprocess.call(["node", str(entrypoint)])


if __name__ == "__main__":
    raise SystemExit(main())
