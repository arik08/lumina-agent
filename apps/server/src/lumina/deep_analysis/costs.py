from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Run
from ..providers.catalog import estimate_model_cost_parts
from .models import DeepAnalysisMission, DeepAnalysisWorkflowNode
from .service import active_workflow


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _integer(value: Any) -> int:
    return int(_number(value))


def _usage_cost_microusd(usage: dict[str, Any]) -> int:
    value = usage.get("cost_usd")
    if value is None and isinstance(usage.get("estimated_cost_breakdown_usd"), dict):
        value = usage["estimated_cost_breakdown_usd"].get("total")
    return round(_number(value) * 1_000_000)


def _no_cache_cost_microusd(run: Run) -> int | None:
    usage = run.usage_json or {}
    input_tokens = _integer(usage.get("input_tokens"))
    output_tokens = _integer(usage.get("output_tokens"))
    parts = estimate_model_cost_parts(
        run.provider_id,
        run.model_key,
        input_tokens=input_tokens,
        cached_input_tokens=0,
        cache_write_tokens=0,
        output_tokens=output_tokens,
    )
    if parts is None:
        return None
    return round(parts["total"] * 1_000_000)


def _run_row(
    *,
    node: DeepAnalysisWorkflowNode,
    run: Run,
    attempt: int,
    is_retry: bool,
) -> dict[str, Any]:
    usage = run.usage_json or {}
    input_tokens = _integer(usage.get("input_tokens"))
    cached_tokens = _integer(usage.get("cached_input_tokens"))
    cache_write_tokens = _integer(usage.get("cache_write_tokens"))
    uncached_tokens = _integer(
        usage.get(
            "uncached_input_tokens",
            max(0, input_tokens - cached_tokens - cache_write_tokens),
        )
    )
    output_tokens = _integer(usage.get("output_tokens"))
    actual = _usage_cost_microusd(usage)
    no_cache = _no_cache_cost_microusd(run)
    return {
        "nodeKey": node.node_key,
        "nodeTitle": node.title,
        "stage": node.node_type,
        "attempt": attempt,
        "isRetry": is_retry,
        "runId": run.id,
        "status": run.status,
        "providerId": run.provider_id,
        "modelKey": run.model_key,
        "modelDisplayName": run.model_display_name,
        "date": (run.finished_at or run.started_at or run.created_at).date().isoformat(),
        "inputTokens": input_tokens,
        "cachedInputTokens": cached_tokens,
        "cacheWriteTokens": cache_write_tokens,
        "uncachedInputTokens": uncached_tokens,
        "outputTokens": output_tokens,
        "actualCostMicrousd": actual,
        "noCacheCostMicrousd": no_cache,
        "estimatedCacheSavingMicrousd": (
            max(0, no_cache - actual) if no_cache is not None else None
        ),
        "pricingVersion": (
            str(usage.get("pricing_version"))
            if usage.get("pricing_version")
            else None
        ),
        "costBasis": str(usage.get("cost_basis") or "unknown"),
    }


def mission_costs(db: Session, mission: DeepAnalysisMission) -> dict[str, Any]:
    _revision, nodes, _edges = active_workflow(db, mission.id)
    run_ids: set[str] = set()
    for node in nodes:
        if node.run_id:
            run_ids.add(node.run_id)
        for history in node.run_history_json:
            if isinstance(history, dict) and history.get("runId"):
                run_ids.add(str(history["runId"]))
    runs = {
        item.id: item
        for item in db.scalars(select(Run).where(Run.id.in_(run_ids)))
    } if run_ids else {}

    rows: list[dict[str, Any]] = []
    for node in nodes:
        history_ids = [
            str(item.get("runId"))
            for item in node.run_history_json
            if isinstance(item, dict) and item.get("runId")
        ]
        for index, run_id in enumerate(history_ids, start=1):
            run = runs.get(run_id)
            if run is not None:
                rows.append(_run_row(node=node, run=run, attempt=index, is_retry=index > 1))
        if node.run_id and node.run_id not in history_ids:
            run = runs.get(node.run_id)
            if run is not None:
                attempt = len(history_ids) + 1
                rows.append(_run_row(node=node, run=run, attempt=attempt, is_retry=attempt > 1))

    totals = {
        "inputTokens": sum(item["inputTokens"] for item in rows),
        "cachedInputTokens": sum(item["cachedInputTokens"] for item in rows),
        "cacheWriteTokens": sum(item["cacheWriteTokens"] for item in rows),
        "uncachedInputTokens": sum(item["uncachedInputTokens"] for item in rows),
        "outputTokens": sum(item["outputTokens"] for item in rows),
    }
    cacheable = totals["cachedInputTokens"] + totals["uncachedInputTokens"]
    no_cache_known = [
        int(item["noCacheCostMicrousd"])
        for item in rows
        if item["noCacheCostMicrousd"] is not None
    ]
    completed_nodes = [node for node in nodes if node.status == "completed"]
    remaining_nodes = [node for node in nodes if node.status in {"planned", "ready", "running"}]
    average_actual = (
        round(sum(node.actual_cost_microusd for node in completed_nodes) / len(completed_nodes))
        if completed_nodes
        else 0
    )
    estimated_remaining = average_actual * len(remaining_nodes)
    average_no_cache = round(sum(no_cache_known) / len(no_cache_known)) if no_cache_known else average_actual
    estimated_completion = mission.spent_microusd + estimated_remaining
    no_cache_upper = sum(no_cache_known) + average_no_cache * len(remaining_nodes)
    return {
        "missionId": mission.id,
        "spentMicrousd": mission.spent_microusd,
        "budgetMicrousd": mission.budget_microusd,
        "budgetUsageRatio": (
            mission.spent_microusd / mission.budget_microusd
            if mission.budget_microusd
            else None
        ),
        "estimatedCompletionMicrousd": estimated_completion,
        "noCacheUpperBoundMicrousd": max(estimated_completion, no_cache_upper),
        "estimatedCacheSavingMicrousd": sum(
            int(item["estimatedCacheSavingMicrousd"] or 0) for item in rows
        ),
        "cacheHitRatio": totals["cachedInputTokens"] / cacheable if cacheable else 0.0,
        "totals": totals,
        "rows": rows,
    }
