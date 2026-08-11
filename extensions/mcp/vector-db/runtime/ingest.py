"""CLI wrapper for the local Vector GraphRAG store."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import main


if __name__ == "__main__":
    raise SystemExit(main())
