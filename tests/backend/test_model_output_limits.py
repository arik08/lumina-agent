from __future__ import annotations

from types import SimpleNamespace

from lumina.agent.executor import _configured_max_output_tokens
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
    assert effective_input_budget > 80_000


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
