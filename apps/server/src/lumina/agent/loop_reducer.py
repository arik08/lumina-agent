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


@dataclass(frozen=True, slots=True)
class ProviderRoundDecision:
    action: ProviderRoundAction
    empty_response_retry_attempt: int
    output_continuation_count: int


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


__all__ = ["ProviderRoundDecision", "decide_provider_round"]
