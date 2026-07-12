#!/usr/bin/env python3
"""Run the vendored pptx-from-layouts generator when available."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
VENDORED_SCRIPT = SKILL_ROOT / "vendor" / "pptx-from-layouts" / "scripts" / "generate.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outline", type=Path, help="Markdown outline input.")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args, extra = parser.parse_known_args()

    if not VENDORED_SCRIPT.exists():
        raise SystemExit(f"Vendored generator not found: {VENDORED_SCRIPT}")

    command = [
        sys.executable,
        str(VENDORED_SCRIPT),
        "--output",
        str(args.output),
        "--template",
        str(args.template),
        str(args.outline),
    ]
    command.extend(extra)
    return subprocess.run(command, cwd=SKILL_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
