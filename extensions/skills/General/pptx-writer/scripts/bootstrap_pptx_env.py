#!/usr/bin/env python3
"""Install dependencies used by the pptx-writer skill."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
NODE_RUNTIME = SKILL_ROOT / "node-runtime"

PYTHON_PACKAGES = [
    "python-pptx",
    "markitdown[pptx]",
    "PyMuPDF",
    "mammoth",
    "markdownify",
    "beautifulsoup4",
    "openpyxl",
    "svglib",
    "reportlab",
    "Pillow",
    "numpy",
    "requests",
    "curl_cffi",
]


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def install_python() -> None:
    _run([sys.executable, "-m", "pip", "install", "--upgrade", *PYTHON_PACKAGES])


def install_node() -> None:
    if not (NODE_RUNTIME / "package.json").exists():
        print(f"[INFO] No node-runtime package.json at {NODE_RUNTIME}; skipping Node packages.")
        return
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm was not found on PATH.")
    _run([npm, "install", "--no-fund", "--no-audit"], cwd=NODE_RUNTIME)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-node", action="store_true")
    args = parser.parse_args()

    if not args.skip_python:
        install_python()
    if not args.skip_node:
        install_node()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

