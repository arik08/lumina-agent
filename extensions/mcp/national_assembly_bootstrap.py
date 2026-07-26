"""Bootstrap the upstream Korean National Assembly MCP server for Lumina."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path


REPO_URL = "https://github.com/hollobit/assembly-api-mcp.git"
REPO_REVISION = "f74c6b452c59d87e2fa7265fd985b90e4057a8ef"
DEFAULT_CACHE_DIR = Path(".cache") / "mcp" / "assembly-api-mcp"
DEFAULT_ASSEMBLY_API_KEY = "sample"


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


def _checkout_revision(server_dir: Path, *, offline: bool) -> bool:
    current_revision = subprocess.run(
        _resolve_command(["git", "rev-parse", "HEAD"]),
        cwd=str(server_dir),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if current_revision == REPO_REVISION:
        return False
    if offline:
        raise RuntimeError(
            "The cached National Assembly MCP is not at the required revision "
            f"{REPO_REVISION} and cannot be updated while offline."
        )
    _run(["git", "fetch", "--depth", "1", "origin", REPO_REVISION], server_dir)
    _run(["git", "checkout", "--detach", REPO_REVISION], server_dir)
    return True


def _ensure_server_built(server_dir: Path, *, offline: bool = False) -> Path:
    index_js = server_dir / "dist" / "index.js"
    package_json = server_dir / "package.json"

    if not server_dir.exists():
        if offline:
            raise RuntimeError(
                "The National Assembly MCP is not cached and cannot be installed while offline."
            )
        server_dir.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--depth", "1", REPO_URL, str(server_dir)], Path.cwd())
    elif not package_json.exists():
        raise RuntimeError(
            f"{server_dir} exists but does not look like assembly-api-mcp. "
            "Remove it or set NATIONAL_ASSEMBLY_MCP_DIR to a valid checkout."
        )

    if not (server_dir / ".git").exists():
        if index_js.exists():
            return index_js
        raise RuntimeError(
            f"{server_dir} is not a Git checkout and does not contain dist/index.js."
        )

    revision_changed = _checkout_revision(server_dir, offline=offline)
    if index_js.exists() and not revision_changed:
        return index_js

    if offline:
        raise RuntimeError(
            "The National Assembly MCP build is missing and cannot install Node dependencies while offline."
        )
    npm_install = (
        ["npm", "ci"]
        if (server_dir / "package-lock.json").exists()
        else ["npm", "install"]
    )
    _run(npm_install, server_dir)
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

    install_only = "--install-only" in sys.argv[1:]
    offline = "--offline" in sys.argv[1:]
    forwarded_args = [
        argument
        for argument in sys.argv[1:]
        if argument not in {"--install-only", "--offline"}
    ]
    index_js = _ensure_server_built(_server_dir(), offline=offline)
    if install_only:
        _log(f"installed pinned upstream revision {REPO_REVISION}")
        return
    os.environ.setdefault("ASSEMBLY_API_KEY", DEFAULT_ASSEMBLY_API_KEY)
    args = [node, str(index_js), *forwarded_args]
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
