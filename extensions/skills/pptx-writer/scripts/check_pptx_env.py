#!/usr/bin/env python3
"""Check the local runtime needed by the pptx-writer skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
NODE_RUNTIME = SKILL_ROOT / "node-runtime"

PYTHON_MODULES = {
    "python-pptx": "pptx",
    "markitdown[pptx]": "markitdown",
    "PyMuPDF": "fitz",
    "mammoth": "mammoth",
    "markdownify": "markdownify",
    "beautifulsoup4": "bs4",
    "openpyxl": "openpyxl",
    "svglib": "svglib",
    "reportlab": "reportlab",
    "Pillow": "PIL",
    "numpy": "numpy",
    "requests": "requests",
    "curl_cffi": "curl_cffi",
}

NODE_MODULES = ["pptxgenjs", "jszip", "fast-xml-parser"]
OPTIONAL_BINARIES = ["soffice", "pdftoppm"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _check_python_modules() -> list[CheckResult]:
    results: list[CheckResult] = []
    for package, module in PYTHON_MODULES.items():
        ok = importlib.util.find_spec(module) is not None
        detail = module if ok else f"missing import module {module}"
        results.append(CheckResult(package, ok, detail))
    return results


def _check_node_modules() -> list[CheckResult]:
    node = shutil.which("node")
    if not node:
        return [CheckResult("node", False, "node executable not found on PATH")]

    results = [CheckResult("node", True, node)]
    for module in NODE_MODULES:
        script = f"require.resolve({module!r})"
        proc = subprocess.run(
            [node, "-e", script],
            cwd=NODE_RUNTIME if NODE_RUNTIME.exists() else SKILL_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        detail = proc.stdout.strip() or proc.stderr.strip()
        results.append(CheckResult(module, proc.returncode == 0, detail or "resolved"))
    return results


def _check_optional_binaries() -> list[CheckResult]:
    return [
        CheckResult(binary, shutil.which(binary) is not None, shutil.which(binary) or "optional")
        for binary in OPTIONAL_BINARIES
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print missing dependencies but exit 0.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of a human-readable report.",
    )
    args = parser.parse_args()

    required = _check_python_modules() + _check_node_modules()
    optional = _check_optional_binaries()
    missing = [result for result in required if not result.ok]

    payload = {
        "skill_root": str(SKILL_ROOT),
        "required": [asdict(result) for result in required],
        "optional": [asdict(result) for result in optional],
        "ok": not missing,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"PPTX writer environment: {'OK' if not missing else 'MISSING DEPENDENCIES'}")
        for result in required:
            mark = "OK" if result.ok else "MISS"
            print(f"[{mark}] {result.name}: {result.detail}")
        for result in optional:
            mark = "OK" if result.ok else "OPT"
            print(f"[{mark}] {result.name}: {result.detail}")

    return 0 if args.report_only or not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

