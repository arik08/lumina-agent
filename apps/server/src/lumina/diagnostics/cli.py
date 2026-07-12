from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from ..config import REPOSITORY_ROOT
from .environment import DiagnosticEnvironment
from .service import run_diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lumina.diagnostics",
        description="Run redacted Lumina installation and operation diagnostics.",
    )
    network_group = parser.add_mutually_exclusive_group()
    network_group.add_argument(
        "--network",
        action="store_true",
        help="Opt in to external P-GPT or database connection checks.",
    )
    network_group.add_argument(
        "--no-network",
        action="store_true",
        help="Run static checks only (the default).",
    )
    parser.add_argument(
        "--pgpt", action="store_true", help="Check P-GPT configuration."
    )
    parser.add_argument(
        "--database", action="store_true", help="Check DATABASE_URL and migrations."
    )
    parser.add_argument(
        "--require-postgres",
        action="store_true",
        help="Fail unless DATABASE_URL uses PostgreSQL.",
    )
    parser.add_argument(
        "--require-company-ca",
        action="store_true",
        help="Fail unless a company CA or combined bundle is configured.",
    )
    parser.add_argument("--company-ca", type=Path)
    parser.add_argument("--ca-bundle", type=Path)
    parser.add_argument("--trust-runtime-dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.timeout > 120:
        parser.error("--timeout must be greater than 0 and at most 120 seconds")
    if args.network and not (args.pgpt or args.database):
        parser.error("--network requires --pgpt or --database")
    repo_root = args.repo_root.expanduser().resolve()
    env_file = args.env_file or repo_root / ".env"
    environment = DiagnosticEnvironment.load(env_file)
    report = run_diagnostics(
        environment=environment,
        repo_root=repo_root,
        network=bool(args.network),
        check_pgpt=bool(args.pgpt),
        check_database=bool(args.database),
        require_company_ca=bool(args.require_company_ca),
        require_postgres=bool(args.require_postgres),
        company_ca=args.company_ca,
        ca_bundle=args.ca_bundle,
        trust_runtime_dir=args.trust_runtime_dir,
        timeout_seconds=float(args.timeout),
    )
    if args.json_output:
        print(json.dumps(report.as_dict(), ensure_ascii=False, separators=(",", ":")))
    else:
        for step in report.steps:
            print(f"[{step.status.upper():7}] {step.stage}: {step.message}")
        print("Diagnostics passed." if report.ok else "Diagnostics failed.")
    return 0 if report.ok else 1


__all__ = ["build_parser", "main"]
