"""Pure calculations for model requests, usage accounting, and Run limits."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..models import Run, utc_now
from ..providers import ProviderMessage
from ..providers.catalog import estimate_model_cost_parts, model_operational_profile


_AUTO_EFFORT_COMPLEX_PATTERN = re.compile(
    r"(?:심층|전수|종합\s*분석|근본\s*원인|원인\s*분석|아키텍처|설계|구현|"
    r"디버그|버그|리팩터|보안|취약점|재무|법률|의료|증명|최적화|"
    r"deep\s+(?:analysis|research)|exhaustive|root\s+cause|architecture|"
    r"implement|debug|refactor|security|vulnerabilit|financial|legal|medical|"
    r"prove|optimi[sz])",
    re.IGNORECASE,
)
_AUTO_EFFORT_RESEARCH_PATTERN = re.compile(
    r"(?:최신|검색|찾아|조사|뉴스|자료\s*확인|research|search|latest|current)",
    re.IGNORECASE,
)
_EXPLICIT_DEEP_WEB_RESEARCH = re.compile(
    r"(?:심층|철저|전수|광범위|종합적|deep\s+research|in[- ]depth|exhaustive|comprehensive)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RunLimitViolation:
    code: str
    message: str
    limit: int | float | str | None
    observed: int | float | str | None

    def event_payload(self) -> dict[str, Any]:
        return {"code": self.code, "limit": self.limit, "observed": self.observed}


def _usage_payload(
    usage: Any,
    *,
    provider_id: str | None = None,
    model: str | None = None,
    model_key: str | None = None,
) -> dict[str, Any]:
    payload = {
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "uncached_input_tokens": usage.uncached_input_tokens,
        "output_tokens": usage.output_tokens,
        "raw": dict(usage.raw),
    }
    if usage.reasoning_tokens is not None:
        payload["reasoning_tokens"] = usage.reasoning_tokens
    subscription_usage = usage.raw.get("billing") == "subscription_usage"
    reported_cost = _reported_cost_usd(usage.raw)
    estimated_cost = estimate_model_cost_parts(
        provider_id or "",
        model_key or model or "",
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        output_tokens=usage.output_tokens,
    )
    if estimated_cost is not None:
        payload["estimated_cost_breakdown_usd"] = estimated_cost
    if reported_cost is not None and not subscription_usage:
        payload["cost_usd"] = reported_cost
        payload["cost_basis"] = "provider_reported"
    elif estimated_cost is not None:
        payload["cost_usd"] = estimated_cost["total"]
        payload["cost_basis"] = (
            "subscription_price_table_estimate"
            if subscription_usage
            else "price_table_estimate"
        )
        profile = model_operational_profile(provider_id or "", model_key or model or "")
        if profile is not None and profile.token_pricing is not None:
            payload["pricing_version"] = profile.token_pricing.version
    return payload


def _effective_reasoning_effort(
    requested_effort: str | None,
    *,
    provider_id: str,
    user_message: str,
    artifact_required: bool,
    attachment_count: int,
    reference_count: int,
    web_research_budget: tuple[int, int],
    artifact_drafting: bool = False,
) -> str | None:
    normalized = (requested_effort or "").strip().casefold()
    if normalized != "auto":
        return normalized or None
    if provider_id.strip().casefold() == "google":
        # Supported Gemini models use provider-side dynamic thinking when no
        # explicit thinking control is sent.
        return None
    if artifact_drafting:
        return "low"

    message = " ".join(user_message.split())
    if _EXPLICIT_DEEP_WEB_RESEARCH.search(message):
        return "high"
    if (
        artifact_required
        or attachment_count >= 3
        or reference_count >= 3
        or _AUTO_EFFORT_COMPLEX_PATTERN.search(message)
        or _AUTO_EFFORT_RESEARCH_PATTERN.search(message)
    ):
        return "medium"
    return "low"


def _provider_prompt_cache_key(
    *,
    user_scope: str,
    provider_id: str,
    model: str,
    messages: Sequence[ProviderMessage],
    tools: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    if not user_scope:
        return "", ""
    stable_system = next(
        (message.content or "" for message in messages if message.role == "system"),
        "",
    )
    stable_tools = sorted(
        (dict(tool) for tool in tools),
        key=lambda tool: str(
            tool.get("function", {}).get("name", "")
            if isinstance(tool.get("function"), Mapping)
            else tool.get("name", "")
        ),
    )
    static_payload = {
        "provider": provider_id.strip().casefold(),
        "model": model.strip().casefold(),
        "system": stable_system,
        "tools": stable_tools,
    }
    static_digest = hashlib.sha256(
        json.dumps(
            static_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    cache_digest = hashlib.sha256(
        f"{user_scope}\0{static_digest}".encode("utf-8")
    ).hexdigest()[:48]
    return f"lumina:user:v2:{cache_digest}", static_digest


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, parsed)


def _optional_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _configured_max_output_tokens(capabilities: Any) -> int | None:
    if not isinstance(capabilities, Mapping):
        return None
    configured = _optional_positive_int(
        capabilities.get(
            "configured_max_output_tokens",
            capabilities.get("configuredMaxOutputTokens"),
        )
    )
    hard_max = _optional_positive_int(
        capabilities.get("max_output_tokens", capabilities.get("maxOutputTokens"))
    )
    if configured is not None and hard_max is not None:
        return min(configured, hard_max)
    return configured


def _artifact_model_request_tokens(
    capabilities: Any, target_output_tokens: int | None
) -> int | None:
    """Give an explicit Artifact target headroom while respecting model hard limits."""
    configured = _configured_max_output_tokens(capabilities)
    target = _optional_positive_int(target_output_tokens)
    if target is None:
        return configured
    requested = max(target, int(target * 1.25))
    if configured is not None:
        requested = max(configured, requested)
    hard_max = (
        _optional_positive_int(
            capabilities.get("max_output_tokens", capabilities.get("maxOutputTokens"))
        )
        if isinstance(capabilities, Mapping)
        else None
    )
    return min(requested, hard_max) if hard_max is not None else requested


def _run_deadline(run: Run) -> datetime | None:
    limits = run.snapshot_json.get("limits", {})
    if not isinstance(limits, Mapping):
        return None
    value = limits.get("deadline")
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        max_elapsed_seconds = _nonnegative_int(limits.get("maxElapsedSeconds"))
        if max_elapsed_seconds <= 0 or run.started_at is None:
            return None
        parsed = run.started_at + timedelta(seconds=max_elapsed_seconds)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _run_limit_violation(run: Run) -> RunLimitViolation | None:
    limits = run.snapshot_json.get("limits", {})
    if not isinstance(limits, Mapping):
        return None

    max_model_turns = _nonnegative_int(limits.get("maxModelTurns"))
    model_turns = _nonnegative_int(run.usage_json.get("model_turns"))
    if max_model_turns and model_turns >= max_model_turns:
        return RunLimitViolation(
            code="run_model_turn_limit_reached",
            message="관리자가 설정한 Run 모델 Turn 한도에 도달했습니다.",
            limit=max_model_turns,
            observed=model_turns,
        )

    max_total_tokens = _nonnegative_int(limits.get("maxTotalTokens"))
    total_tokens = _nonnegative_int(
        run.usage_json.get("input_tokens")
    ) + _nonnegative_int(run.usage_json.get("output_tokens"))
    if max_total_tokens and total_tokens >= max_total_tokens:
        return RunLimitViolation(
            code="run_token_limit_reached",
            message="관리자가 설정한 Run 누적 Token 한도에 도달했습니다.",
            limit=max_total_tokens,
            observed=total_tokens,
        )

    max_cost_usd = _nonnegative_float(limits.get("maxCostUsd"))
    cost_usd = _nonnegative_float(run.usage_json.get("cost_usd"))
    if max_cost_usd and cost_usd >= max_cost_usd:
        return RunLimitViolation(
            code="run_cost_limit_reached",
            message="관리자가 설정한 Run 예상 비용 한도에 도달했습니다.",
            limit=max_cost_usd,
            observed=cost_usd,
        )

    deadline = _run_deadline(run)
    if deadline is not None and utc_now() >= deadline:
        return RunLimitViolation(
            code="run_deadline_reached",
            message="관리자가 설정한 Run 실행 시간 한도에 도달했습니다.",
            limit=deadline.isoformat(),
            observed=utc_now().isoformat(),
        )
    return None


def _nonnegative_float(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = float(value)
        if math.isfinite(converted) and converted >= 0:
            return converted
    return 0.0


def _reported_cost_usd(raw: Any) -> float | None:
    if not isinstance(raw, Mapping):
        return None
    for key in ("cost_usd", "total_cost_usd", "estimated_cost_usd", "cost"):
        value = raw.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if parsed >= 0 and math.isfinite(parsed):
            return parsed
    return None
