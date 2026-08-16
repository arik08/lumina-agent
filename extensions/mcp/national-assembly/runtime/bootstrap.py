"""Launch the repository-bundled Korean National Assembly MCP server."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path


BUNDLED_INDEX = Path(__file__).with_name("index.js")
COMPATIBILITY_PATCH = Path(__file__).with_name("assembly-api-mcp-network-retry.patch")


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


def _patch_can_apply(server_dir: Path, *, reverse: bool = False) -> bool:
    args = ["git", "apply"]
    if reverse:
        args.append("--reverse")
    args.extend(["--check", "--ignore-space-change", str(COMPATIBILITY_PATCH)])
    result = subprocess.run(
        _resolve_command(args),
        cwd=str(server_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _apply_compatibility_patch(server_dir: Path) -> bool:
    if _patch_can_apply(server_dir):
        _run(["git", "apply", str(COMPATIBILITY_PATCH)], server_dir)
        return True
    if _patch_can_apply(server_dir, reverse=True):
        return False
    raise RuntimeError(
        "The assembly-api-mcp compatibility patch does not match this checkout. "
        "Update the patch or unset NATIONAL_ASSEMBLY_MCP_DIR to use the bundled server."
    )


def _ensure_override_built(server_dir: Path) -> Path:
    """Build an explicitly requested developer checkout.

    Normal Lumina runs never call this path: they use the committed bundle.
    """
    index_js = server_dir / "dist" / "index.js"
    package_json = server_dir / "package.json"
    if not package_json.exists():
        raise RuntimeError(
            f"{server_dir} does not look like assembly-api-mcp. "
            "Unset NATIONAL_ASSEMBLY_MCP_DIR to use the bundled server."
        )

    patch_applied = _apply_compatibility_patch(server_dir)
    if index_js.exists() and not patch_applied:
        return index_js

    _run(["npm", "install"], server_dir)
    _run(["npm", "run", "build"], server_dir)
    if not index_js.exists():
        raise RuntimeError(f"Expected built server at {index_js}, but it was not created.")
    return index_js


def _server_index() -> Path:
    override = os.environ.get("NATIONAL_ASSEMBLY_MCP_DIR", "").strip()
    if override:
        return _ensure_override_built(Path(override).expanduser().resolve())
    if not BUNDLED_INDEX.exists():
        raise RuntimeError(f"Bundled National Assembly MCP server is missing: {BUNDLED_INDEX}")
    return BUNDLED_INDEX


def main() -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to run the national assembly MCP server.")

    args = [node, str(_server_index()), *sys.argv[1:]]
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
