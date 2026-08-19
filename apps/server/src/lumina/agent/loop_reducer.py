from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProviderRoundAction = Literal[
    "execute_tools",
    "reject_incomplete_tools",
    "continue_output",
    "append_truncation_notice",
    "retry_empty",
    "resolve_empty",
    "finish_text",
]
ToolBatchNextAction = Literal["continue_model", "fail_run"]
ToolLoopEvent = Literal["tool_loop_warning", "tool_loop_detected"]


@dataclass(frozen=True, slots=True)
class ProviderRoundDecision:
    action: ProviderRoundAction
    empty_response_retry_attempt: int
    output_continuation_count: int


@dataclass(frozen=True, slots=True)
class CompletedToolBatchDecision:
    next_action: ToolBatchNextAction
    loop_event: ToolLoopEvent | None
    inject_loop_warning: bool


def decide_provider_round(
    *,
    has_tool_calls: bool,
    has_visible_text: bool,
    output_truncated: bool,
    empty_response_retry_attempt: int,
    output_continuation_count: int,
    max_empty_response_retries: int,
    max_auto_continuations: int,
) -> ProviderRoundDecision:
    if has_tool_calls:
        return ProviderRoundDecision(
            action=("reject_incomplete_tools" if output_truncated else "execute_tools"),
            empty_response_retry_attempt=0,
            output_continuation_count=0,
        )
    if output_truncated and has_visible_text:
        if output_continuation_count < max_auto_continuations:
            return ProviderRoundDecision(
                action="continue_output",
                empty_response_retry_attempt=0,
                output_continuation_count=output_continuation_count + 1,
            )
        return ProviderRoundDecision(
            action="append_truncation_notice",
            empty_response_retry_attempt=0,
            output_continuation_count=output_continuation_count,
        )
    if not has_visible_text:
        if empty_response_retry_attempt < max_empty_response_retries:
            return ProviderRoundDecision(
                action="retry_empty",
                empty_response_retry_attempt=empty_response_retry_attempt + 1,
                output_continuation_count=output_continuation_count,
            )
        return ProviderRoundDecision(
            action="resolve_empty",
            empty_response_retry_attempt=empty_response_retry_attempt,
            output_continuation_count=output_continuation_count,
        )
    return ProviderRoundDecision(
        action="finish_text",
        empty_response_retry_attempt=0,
        output_continuation_count=0,
    )


def decide_completed_tool_batch(
    *,
    repeat_count: int,
    warning_repeat_count: int,
    maximum_repeat_count: int,
) -> CompletedToolBatchDecision:
    if repeat_count >= maximum_repeat_count:
        return CompletedToolBatchDecision(
            next_action="fail_run",
            loop_event="tool_loop_detected",
            inject_loop_warning=False,
        )
    if repeat_count >= warning_repeat_count:
        return CompletedToolBatchDecision(
            next_action="continue_model",
            loop_event="tool_loop_warning",
            inject_loop_warning=True,
        )
    return CompletedToolBatchDecision(
        next_action="continue_model",
        loop_event=None,
        inject_loop_warning=False,
    )


__all__ = [
    "CompletedToolBatchDecision",
    "ProviderRoundDecision",
    "decide_completed_tool_batch",
    "decide_provider_round",
]
