from __future__ import annotations

import pytest

from lumina.agent.loop_reducer import decide_provider_round
from lumina.agent.tool_runtime_policy import decide_tool_replay, tool_replay_policy


@pytest.mark.parametrize(
    ("crash_position", "execution_status", "expected_action"),
    (
        ("before_tool_record", None, "execute"),
        ("while_streaming_arguments", "streaming", "execute"),
        ("after_external_invocation_started", "running", "fail_closed"),
        ("after_result_persisted", "completed", "reuse_result"),
        ("after_terminal_failure", "failed", "fail_closed"),
        ("after_terminal_cancellation", "cancelled", "fail_closed"),
    ),
)
def test_tool_crash_position_matrix(
    crash_position: str,
    execution_status: str | None,
    expected_action: str,
) -> None:
    del crash_position

    decision = decide_tool_replay(
        tool_replay_policy("write_file"),
        execution_status=execution_status,
    )

    assert decision.action == expected_action


@pytest.mark.parametrize(
    (
        "fault_position",
        "has_tool_calls",
        "has_visible_text",
        "output_truncated",
        "empty_attempt",
        "continuation_count",
        "expected_action",
    ),
    (
        ("before_provider_output", False, False, False, 0, 0, "retry_empty"),
        ("after_partial_text_limit", False, True, True, 0, 0, "continue_output"),
        ("after_text_completed", False, True, False, 0, 0, "finish_text"),
        ("after_tool_arguments", True, False, False, 0, 0, "execute_tools"),
        (
            "during_truncated_tool_arguments",
            True,
            False,
            True,
            0,
            0,
            "reject_incomplete_tools",
        ),
        ("after_empty_retry_budget", False, False, False, 1, 0, "resolve_empty"),
        (
            "after_continuation_budget",
            False,
            True,
            True,
            0,
            4,
            "append_truncation_notice",
        ),
    ),
)
def test_provider_round_fault_matrix(
    fault_position: str,
    has_tool_calls: bool,
    has_visible_text: bool,
    output_truncated: bool,
    empty_attempt: int,
    continuation_count: int,
    expected_action: str,
) -> None:
    del fault_position

    decision = decide_provider_round(
        has_tool_calls=has_tool_calls,
        has_visible_text=has_visible_text,
        output_truncated=output_truncated,
        empty_response_retry_attempt=empty_attempt,
        output_continuation_count=continuation_count,
        max_empty_response_retries=1,
        max_auto_continuations=4,
    )

    assert decision.action == expected_action
