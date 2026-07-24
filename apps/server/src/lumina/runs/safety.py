from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEFAULT_RUN_SAFETY_SETTINGS: dict[str, int | float | bool] = {
    "max_model_turns": 400,
    "max_total_tokens": 4_000_000,
    "max_elapsed_minutes": 10_080,
    "max_cost_usd": 100.0,
    "yolo_mode": True,
}


def normalize_run_safety_settings(value: Any) -> dict[str, int | float | bool]:
    raw = value if isinstance(value, Mapping) else {}
    return {
        "max_model_turns": _bounded_int(
            raw.get("max_model_turns"), 10, 10_000, "max_model_turns"
        ),
        "max_total_tokens": _bounded_int(
            raw.get("max_total_tokens"), 100_000, 100_000_000, "max_total_tokens"
        ),
        "max_elapsed_minutes": _bounded_int(
            raw.get("max_elapsed_minutes"), 30, 525_600, "max_elapsed_minutes"
        ),
        "max_cost_usd": _bounded_float(
            raw.get("max_cost_usd"), 1.0, 10_000.0, "max_cost_usd"
        ),
        "yolo_mode": (
            raw["yolo_mode"]
            if isinstance(raw.get("yolo_mode"), bool)
            else DEFAULT_RUN_SAFETY_SETTINGS["yolo_mode"]
        ),
    }


def run_safety_payload(value: Any) -> dict[str, int | float | bool]:
    normalized = normalize_run_safety_settings(value)
    return {
        "maxModelTurns": normalized["max_model_turns"],
        "maxTotalTokens": normalized["max_total_tokens"],
        "maxElapsedMinutes": normalized["max_elapsed_minutes"],
        "maxCostUsd": normalized["max_cost_usd"],
        "yoloMode": normalized["yolo_mode"],
    }


def run_limit_snapshot(value: Any) -> dict[str, int | float | str]:
    normalized = normalize_run_safety_settings(value)
    return {
        "maxModelTurns": normalized["max_model_turns"],
        "maxTotalTokens": normalized["max_total_tokens"],
        "maxElapsedSeconds": int(normalized["max_elapsed_minutes"]) * 60,
        "maxCostUsd": normalized["max_cost_usd"],
        "costAccounting": "provider_reported_or_estimated",
    }


def run_approval_mode(value: Any) -> str:
    return "yolo" if normalize_run_safety_settings(value)["yolo_mode"] else "on_risk"


def _bounded_int(value: Any, minimum: int, maximum: int, key: str) -> int:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    ):
        return value
    return int(DEFAULT_RUN_SAFETY_SETTINGS[key])


def _bounded_float(value: Any, minimum: float, maximum: float, key: str) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = float(value)
        if minimum <= converted <= maximum:
            return converted
    return float(DEFAULT_RUN_SAFETY_SETTINGS[key])


__all__ = [
    "DEFAULT_RUN_SAFETY_SETTINGS",
    "normalize_run_safety_settings",
    "run_approval_mode",
    "run_limit_snapshot",
    "run_safety_payload",
]
