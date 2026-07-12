#!/usr/bin/env python3
"""Small Windows-safe wrapper for the OpenWeb CLI.

PowerShell can strip JSON quotes when passing params directly to npx. This
wrapper calls npx without a shell and passes the JSON object as one argv item.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


PACKAGE = "@openweb-org/openweb@latest"


def _npx_command() -> str:
    found = shutil.which("npx.cmd") or shutil.which("npx")
    if found:
        return found
    nodejs_npx = Path(r"C:\Program Files\nodejs\npx.cmd")
    if nodejs_npx.exists():
        return str(nodejs_npx)
    raise SystemExit("openweb_call error: could not find npx/npx.cmd on PATH")


def _usage() -> str:
    return (
        "Usage:\n"
        "  python .skills/openweb/scripts/openweb_call.py sites\n"
        "  python .skills/openweb/scripts/openweb_call.py <site>\n"
        "  python .skills/openweb/scripts/openweb_call.py <site> <operation> '<json-params>'\n"
        "  python .skills/openweb/scripts/openweb_call.py <site> <operation> key=value [key=value ...]\n"
        "\n"
        "Examples:\n"
        "  python .skills/openweb/scripts/openweb_call.py arxiv searchPapers "
        "\"search_query=all:quarterly steel demand\" max_results=5\n"
        "  python .skills/openweb/scripts/openweb_call.py wikipedia getPageSummary "
        "title=World_Wide_Web\n"
    )


def _coerce_value(raw: str) -> object:
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _normalize_json(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"openweb_call error: params must be valid JSON: {exc}") from exc
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def _normalize_params(args: list[str]) -> str:
    if len(args) == 1 and "=" not in args[0]:
        raw = args[0]
        if raw.startswith("@"):
            raw = Path(raw[1:]).read_text(encoding="utf-8")
        return _normalize_json(raw)

    params: dict[str, object] = {}
    for arg in args:
        if "=" not in arg:
            raise SystemExit(
                "openweb_call error: params must be JSON, @json-file, or key=value pairs"
            )
        key, value = arg.split("=", 1)
        if not key:
            raise SystemExit("openweb_call error: empty param key")
        params[key] = _coerce_value(value)
    return json.dumps(params, ensure_ascii=False, separators=(",", ":"))


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(_usage(), end="")
        return 0 if argv else 2

    cmd = [_npx_command(), "-y", PACKAGE]

    if len(argv) == 1:
        cmd.append(argv[0])
    elif len(argv) == 2:
        cmd.extend(argv)
    elif len(argv) >= 3:
        site, operation, *params = argv
        cmd.extend([site, operation, _normalize_params(params)])
    else:
        print(_usage(), file=sys.stderr, end="")
        return 2

    proc = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
