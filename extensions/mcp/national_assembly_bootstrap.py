"""Bootstrap the upstream Korean National Assembly MCP server for MyHarness."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path


REPO_URL = "https://github.com/hollobit/assembly-api-mcp.git"
DEFAULT_CACHE_DIR = Path(".myharness") / "mcp-cache" / "assembly-api-mcp"


def _log(message: str) -> None:
    print(f"[national-assembly-mcp] {message}", file=sys.stderr, flush=True)


def _is_noisy_startup_log(line: str) -> bool:
    return (
        line.startswith("[national-assembly-mcp] starting upstream server:")
        or line.strip() == "[assembly-api-mcp] MCP 서버가 시작되었습니다."
    )


def _forward_filtered_stderr(stream) -> None:
    for raw_line in iter(stream.readline, ""):
        if not raw_line:
            break
        if _is_noisy_startup_log(raw_line.rstrip("\r\n")):
            continue
        sys.stderr.write(raw_line)
        sys.stderr.flush()


def _resolve_command(args: list[str]) -> list[str]:
    executable = shutil.which(args[0])
    if executable is None:
        raise RuntimeError(f"Required command not found: {args[0]}")
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", executable, *args[1:]]
    return [executable, *args[1:]]


def _run(args: list[str], cwd: Path) -> None:
    _log(f"running: {' '.join(args)}")
    subprocess.run(_resolve_command(args), cwd=str(cwd), check=True, stdout=sys.stderr, stderr=sys.stderr)


def _server_dir() -> Path:
    override = os.environ.get("NATIONAL_ASSEMBLY_MCP_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.cwd() / DEFAULT_CACHE_DIR).resolve()


def _ensure_server_built(server_dir: Path) -> Path:
    index_js = server_dir / "dist" / "index.js"
    package_json = server_dir / "package.json"
    if index_js.exists():
        return index_js

    if not server_dir.exists():
        server_dir.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--depth", "1", REPO_URL, str(server_dir)], Path.cwd())
    elif not package_json.exists():
        raise RuntimeError(
            f"{server_dir} exists but does not look like assembly-api-mcp. "
            "Remove it or set NATIONAL_ASSEMBLY_MCP_DIR to a valid checkout."
        )

    _run(["npm", "install"], server_dir)
    _run(["npm", "run", "build"], server_dir)
    if not index_js.exists():
        raise RuntimeError(f"Expected built server at {index_js}, but it was not created.")
    return index_js


def main() -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to run the national assembly MCP server.")
    if not shutil.which("git"):
        raise RuntimeError("git is required for the first national assembly MCP bootstrap.")
    if not shutil.which("npm"):
        raise RuntimeError("npm is required for the first national assembly MCP bootstrap.")

    index_js = _ensure_server_built(_server_dir())
    args = [node, str(index_js), *sys.argv[1:]]
    process = subprocess.Popen(
        args,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stderr is not None
    stderr_thread = threading.Thread(target=_forward_filtered_stderr, args=(process.stderr,), daemon=True)
    stderr_thread.start()
    return_code = process.wait()
    stderr_thread.join(timeout=1)
    sys.exit(return_code)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _log(str(exc))
        sys.exit(1)
