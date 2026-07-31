from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "devtools" / "run_backend_harness.py"
_SPEC = importlib.util.spec_from_file_location("run_backend_harness", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
harness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(harness)


def test_harness_performance_gate_requires_material_absolute_and_relative_change() -> (
    None
):
    baseline = {
        "environment": {"system": "test"},
        "suites": {
            "fast": {"medianDurationSeconds": 1.0, "caseIds": ["fast"]},
            "slow": {"medianDurationSeconds": 10.0, "caseIds": ["slow"]},
        },
    }
    current = {
        "environment": {"system": "test"},
        "suites": {
            "fast": {"medianDurationSeconds": 1.4, "caseIds": ["fast"]},
            "slow": {"medianDurationSeconds": 13.1, "caseIds": ["slow"]},
        },
    }

    regressions = harness._performance_regressions(
        current=current,
        baseline=baseline,
        max_relative_regression=0.30,
        min_regression_seconds=0.50,
    )

    assert [regression["suite"] for regression in regressions] == ["slow"]


def test_harness_skips_performance_comparison_for_changed_cases_or_machine() -> None:
    baseline = {
        "environment": {"system": "Windows", "logicalCpuCount": 8},
        "suites": {"cache": {"medianDurationSeconds": 1.0, "caseIds": ["old"]}},
    }
    changed_cases = {
        "environment": dict(baseline["environment"]),
        "suites": {"cache": {"medianDurationSeconds": 5.0, "caseIds": ["new"]}},
    }
    changed_machine = {
        "environment": {"system": "Linux", "logicalCpuCount": 8},
        "suites": {"cache": {"medianDurationSeconds": 5.0, "caseIds": ["old"]}},
    }

    assert (
        harness._performance_regressions(
            current=changed_cases,
            baseline=baseline,
            max_relative_regression=0.30,
            min_regression_seconds=0.50,
        )
        == []
    )
    assert harness._performance_comparison_skips(
        current=changed_cases, baseline=baseline
    ) == [{"suite": "cache", "reason": "case_set_mismatch"}]
    assert harness._performance_comparison_skips(
        current=changed_machine, baseline=baseline
    ) == [{"suite": "cache", "reason": "environment_mismatch"}]
    assert (
        harness._performance_regressions(
            current=changed_machine,
            baseline=baseline,
            max_relative_regression=0.30,
            min_regression_seconds=0.50,
        )
        == []
    )


def test_harness_report_provenance_is_safe_and_machine_comparable() -> None:
    source_state = harness._source_state()
    environment = harness._runtime_environment()

    assert isinstance(source_state["workingTreeDirty"], bool)
    fingerprint = source_state["sourceFingerprintSha256"]
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert environment["system"]
    assert environment["machine"]
    assert environment["pythonVersion"]
    assert environment["logicalCpuCount"] is None or environment["logicalCpuCount"] > 0
