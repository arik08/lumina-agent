from __future__ import annotations

from types import SimpleNamespace

from lumina.agent.executor import (
    _artifact_model_request_tokens,
    _configured_max_output_tokens,
)
from lumina.context.service import _compaction_threshold, _context_budget


def test_executor_uses_configured_output_limit_without_exceeding_hard_max() -> None:
    assert (
        _configured_max_output_tokens(
            {
                "configured_max_output_tokens": 42_000,
                "max_output_tokens": 128_000,
            }
        )
        == 42_000
    )
    assert (
        _configured_max_output_tokens(
            {
                "configured_max_output_tokens": 256_000,
                "max_output_tokens": 128_000,
            }
        )
        == 128_000
    )


def test_artifact_target_gets_myharness_style_headroom_within_hard_max() -> None:
    capabilities = {
        "configured_max_output_tokens": 4_096,
        "max_output_tokens": 64_000,
    }

    assert _artifact_model_request_tokens(capabilities, 12_000) == 15_000
    assert _artifact_model_request_tokens(capabilities, 40_000) == 50_000
    assert _artifact_model_request_tokens(capabilities, None) == 4_096
    assert (
        _artifact_model_request_tokens({"max_output_tokens": 45_000}, 40_000) == 45_000
    )


def test_ten_thousand_artifact_target_keeps_pgpt_configured_headroom() -> None:
    pgpt_capabilities = {
        "configured_max_output_tokens": 42_000,
        "max_output_tokens": 128_000,
    }

    assert _artifact_model_request_tokens(pgpt_capabilities, 10_000) == 42_000


def test_context_budget_reserves_configured_output_limit() -> None:
    run = SimpleNamespace(
        snapshot_json={
            "execution": {
                "capabilities": {
                    "context_window": 100_000,
                    "max_output_tokens": 80_000,
                    "configured_max_output_tokens": 10_000,
                }
            }
        },
        provider_id="mock",
        runtime_model_id="mock-agent",
    )

    context_window, effective_input_budget = _context_budget(run, ())

    assert context_window == 100_000
    assert effective_input_budget == 85_904


def test_context_policy_falls_back_to_catalog_metadata() -> None:
    run = SimpleNamespace(
        snapshot_json={"execution": {"capabilities": {}}},
        provider_id="codex",
        model_key="gpt-5.5",
        runtime_model_id="deployment-alias",
    )

    context_window, effective_input_budget = _context_budget(run, ())

    assert context_window == 272_000
    assert _compaction_threshold(run, effective_input_budget) == int(
        effective_input_budget * 0.85
    )


def test_context_budget_honors_measured_input_limit() -> None:
    run = SimpleNamespace(
        snapshot_json={
            "execution": {
                "capabilities": {
                    "context_window": 1_050_000,
                    "max_input_tokens": 911_900,
                    "configured_max_output_tokens": 42_000,
                }
            }
        },
        provider_id="pgpt",
        model_key="gpt-5.5",
        runtime_model_id="gpt-5.5",
    )

    context_window, effective_input_budget = _context_budget(run, ())

    assert context_window == 1_050_000
    assert effective_input_budget == 907_804
