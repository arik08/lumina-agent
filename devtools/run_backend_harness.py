from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "tests" / "evals" / "backend_harness.json"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / ".lumina-harness"
SERVER_PROJECT = REPOSITORY_ROOT / "apps" / "server"
PYTEST_CONFIG = SERVER_PROJECT / "pyproject.toml"
SOURCE_PATHS = (
    "apps/server",
    "tests/backend",
    "tests/evals",
    "devtools/run_backend_harness.py",
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic Lumina backend harness regression bank."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--trial-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-relative-regression", type=float, default=0.30)
    parser.add_argument("--min-regression-seconds", type=float, default=0.50)
    return parser.parse_args()


def _load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    suites = data.get("suites")
    if data.get("version") != 1 or not isinstance(suites, dict) or not suites:
        raise ValueError("Harness manifest must contain non-empty version 1 suites.")
    for name, suite in suites.items():
        cases = suite.get("cases") if isinstance(suite, dict) else None
        if not isinstance(name, str) or not isinstance(cases, list) or not cases:
            raise ValueError(f"Harness suite {name!r} must contain test cases.")
        if any(not isinstance(case, str) or "::" not in case for case in cases):
            raise ValueError(f"Harness suite {name!r} contains an invalid node id.")
    return data


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _case_results(junit_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(junit_path).getroot()
    results: list[dict[str, Any]] = []
    for case in root.iter("testcase"):
        status = "passed"
        if case.find("failure") is not None:
            status = "failed"
        elif case.find("error") is not None:
            status = "error"
        elif case.find("skipped") is not None:
            status = "skipped"
        results.append(
            {
                "id": f"{case.get('classname', '')}::{case.get('name', '')}",
                "status": status,
                "durationSeconds": round(float(case.get("time", "0")), 6),
            }
        )
    return results


def _git_revision() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    revision = completed.stdout.strip()
    return revision if completed.returncode == 0 and revision else None


def _source_state() -> dict[str, Any]:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *SOURCE_PATHS],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--", *SOURCE_PATHS],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", *SOURCE_PATHS],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0 or diff.returncode != 0 or untracked.returncode != 0:
        return {"workingTreeDirty": None, "sourceFingerprintSha256": None}
    digest = hashlib.sha256()
    digest.update(diff.stdout)
    for relative in sorted(line for line in untracked.stdout.splitlines() if line):
        path = (REPOSITORY_ROOT / relative).resolve()
        if path.is_file() and path.is_relative_to(REPOSITORY_ROOT):
            digest.update(relative.replace("\\", "/").encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return {
        "workingTreeDirty": bool(status.stdout.strip()),
        "sourceFingerprintSha256": digest.hexdigest(),
    }


def _runtime_environment() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "pythonVersion": platform.python_version(),
        "logicalCpuCount": os.cpu_count(),
    }


def _run_trial(
    *,
    uv_executable: str,
    suite_name: str,
    cases: list[str],
    trial: int,
    junit_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    command = [
        uv_executable,
        "run",
        "--project",
        str(SERVER_PROJECT),
        "pytest",
        "-c",
        str(PYTEST_CONFIG),
        "-q",
        *cases,
        f"--junitxml={junit_path}",
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - started
        print(
            f"[{suite_name}] trial {trial}: TIMEOUT ({duration:.3f}s)",
            flush=True,
        )
        return {
            "trial": trial,
            "passed": False,
            "exitCode": None,
            "durationSeconds": round(duration, 6),
            "cases": (_case_results(junit_path) if junit_path.is_file() else []),
            "failureOutput": f"Trial exceeded {timeout_seconds:g} seconds.",
        }
    duration = time.perf_counter() - started
    case_results = _case_results(junit_path) if junit_path.is_file() else []
    passed = (
        bool(case_results)
        and completed.returncode == 0
        and all(result["status"] == "passed" for result in case_results)
    )
    print(
        f"[{suite_name}] trial {trial}: "
        f"{'PASS' if passed else 'FAIL'} ({duration:.3f}s)",
        flush=True,
    )
    return {
        "trial": trial,
        "passed": passed,
        "exitCode": completed.returncode,
        "durationSeconds": round(duration, 6),
        "cases": case_results,
        "failureOutput": (
            "\n".join((completed.stdout + completed.stderr).splitlines()[-80:])
            if not passed
            else None
        ),
    }


def _summarize_suite(
    *, description: str, case_ids: list[str], trials: list[dict[str, Any]]
) -> dict[str, Any]:
    durations = [float(trial["durationSeconds"]) for trial in trials]
    return {
        "description": description,
        "caseIds": case_ids,
        "passed": all(bool(trial["passed"]) for trial in trials),
        "passRate": round(
            sum(1 for trial in trials if trial["passed"]) / len(trials), 4
        ),
        "medianDurationSeconds": round(statistics.median(durations), 6),
        "p95DurationSeconds": round(_percentile(durations, 0.95), 6),
        "trials": trials,
    }


def _performance_regressions(
    *,
    current: dict[str, Any],
    baseline: dict[str, Any],
    max_relative_regression: float,
    min_regression_seconds: float,
) -> list[dict[str, Any]]:
    if current.get("environment") != baseline.get("environment"):
        return []
    regressions: list[dict[str, Any]] = []
    baseline_suites = baseline.get("suites", {})
    for name, suite in current["suites"].items():
        previous = baseline_suites.get(name)
        if not isinstance(previous, dict):
            continue
        if previous.get("caseIds") != suite.get("caseIds"):
            continue
        previous_median = float(previous.get("medianDurationSeconds", 0.0))
        current_median = float(suite["medianDurationSeconds"])
        if previous_median <= 0:
            continue
        absolute_change = current_median - previous_median
        relative_change = absolute_change / previous_median
        if (
            absolute_change >= min_regression_seconds
            and relative_change > max_relative_regression
        ):
            regressions.append(
                {
                    "suite": name,
                    "baselineMedianSeconds": previous_median,
                    "currentMedianSeconds": current_median,
                    "relativeRegression": round(relative_change, 4),
                }
            )
    return regressions


def _performance_comparison_skips(
    *, current: dict[str, Any], baseline: dict[str, Any]
) -> list[dict[str, str]]:
    current_environment = current.get("environment")
    baseline_environment = baseline.get("environment")
    if current_environment != baseline_environment:
        return [
            {"suite": name, "reason": "environment_mismatch"}
            for name in current["suites"]
        ]
    baseline_suites = baseline.get("suites", {})
    skipped: list[dict[str, str]] = []
    for name, suite in current["suites"].items():
        previous = baseline_suites.get(name)
        if not isinstance(previous, dict):
            skipped.append({"suite": name, "reason": "baseline_suite_missing"})
        elif previous.get("caseIds") != suite.get("caseIds"):
            skipped.append({"suite": name, "reason": "case_set_mismatch"})
    return skipped


def main() -> int:
    args = _arguments()
    if args.trials < 1:
        raise ValueError("--trials must be at least 1.")
    if args.trial_timeout_seconds <= 0:
        raise ValueError("--trial-timeout-seconds must be positive.")
    if args.max_relative_regression < 0 or args.min_regression_seconds < 0:
        raise ValueError("Regression thresholds must be non-negative.")

    uv_executable = shutil.which("uv")
    if uv_executable is None:
        raise RuntimeError("uv is required to run the backend harness.")

    manifest_path = args.manifest.resolve()
    manifest = _load_manifest(manifest_path)
    selected = set(args.suite)
    available = set(manifest["suites"])
    unknown = selected - available
    if unknown:
        raise ValueError(f"Unknown harness suites: {', '.join(sorted(unknown))}")

    generated_at = datetime.now(UTC)
    output_path = (
        args.output.resolve()
        if args.output is not None
        else DEFAULT_OUTPUT_DIRECTORY
        / f"backend-harness-{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": generated_at.isoformat(),
        "gitRevision": _git_revision(),
        **_source_state(),
        "environment": _runtime_environment(),
        "manifest": str(manifest_path.relative_to(REPOSITORY_ROOT)),
        "trialCount": args.trials,
        "policy": {
            "requiredPassRate": 1.0,
            "trialTimeoutSeconds": args.trial_timeout_seconds,
            "maxRelativeMedianRegression": args.max_relative_regression,
            "minAbsoluteMedianRegressionSeconds": args.min_regression_seconds,
        },
        "suites": {},
    }
    with tempfile.TemporaryDirectory(prefix="lumina-harness-") as temporary:
        temporary_path = Path(temporary)
        for suite_name, suite in manifest["suites"].items():
            if selected and suite_name not in selected:
                continue
            trials = [
                _run_trial(
                    uv_executable=uv_executable,
                    suite_name=suite_name,
                    cases=suite["cases"],
                    trial=trial,
                    junit_path=temporary_path / f"{suite_name}-{trial}.xml",
                    timeout_seconds=args.trial_timeout_seconds,
                )
                for trial in range(1, args.trials + 1)
            ]
            report["suites"][suite_name] = _summarize_suite(
                description=suite.get("description", ""),
                case_ids=list(suite["cases"]),
                trials=trials,
            )

    regressions: list[dict[str, Any]] = []
    comparison_skips: list[dict[str, str]] = []
    if args.baseline is not None:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        comparison_skips = _performance_comparison_skips(
            current=report,
            baseline=baseline,
        )
        regressions = _performance_regressions(
            current=report,
            baseline=baseline,
            max_relative_regression=args.max_relative_regression,
            min_regression_seconds=args.min_regression_seconds,
        )
    report["performanceRegressions"] = regressions
    report["performanceComparisonSkipped"] = comparison_skips
    report["passed"] = (
        all(suite["passed"] for suite in report["suites"].values()) and not regressions
    )
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Report: {output_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Harness error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
