"""
Confidence scoring for per-slide quality assessment.

Computes a 0.0-1.0 confidence score per slide by aggregating existing
signals from GenerationResult data. No new analysis is performed --
this module reads warnings, status, and shrink info to produce weighted
scores and human-readable flags.

Slides scoring below CONFIDENCE_THRESHOLD (0.8) are flagged for review
with descriptions of what reduced confidence.

Usage:
    from scripts.confidence import compute_confidence, CONFIDENCE_THRESHOLD

    scores = compute_confidence(generation_result_dict)
    flagged = [s for s in scores if s.score < CONFIDENCE_THRESHOLD]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add .claude/ to path for schema imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schemas.pipeline_state import SlideConfidence  # noqa: E402

# Dimension weights (must sum to 1.0)
CONFIDENCE_DIMENSIONS: dict[str, float] = {
    "layout_fit": 0.25,
    "content_overflow": 0.30,
    "content_shrink": 0.20,
    "generation_status": 0.25,
}

# Slides scoring below this are flagged for review
CONFIDENCE_THRESHOLD: float = 0.8

# Status-to-score mapping
_STATUS_SCORES: dict[str, float] = {
    "success": 1.0,
    "partial": 0.6,
    "failed": 0.0,
    "skipped": 0.0,
}


def score_slide(
    slide_result: dict, shrink_info: dict | None = None
) -> SlideConfidence:
    """Compute confidence for one slide from its SlideResult-shaped dict.

    Args:
        slide_result: Dict with keys: slide_number, status, warnings (list[str]).
        shrink_info: Optional dict with final_size and original_size for shrink ratio.

    Returns:
        SlideConfidence with weighted score, dimension sub-scores, and flags.
    """
    slide_number = slide_result.get("slide_number", 0)
    status = slide_result.get("status", "success")
    warnings = slide_result.get("warnings", [])

    dimensions: dict[str, float] = {}
    flags: list[str] = []

    # Layout fit: 1.0 normally, 0.4 if fallback triggered
    has_fallback = any("fallback" in w.lower() for w in warnings)
    dimensions["layout_fit"] = 0.4 if has_fallback else 1.0
    if has_fallback:
        flags.append("Layout fallback triggered -- slide used generic layout")

    # Content overflow: 1.0 normally, 0.3 if overflow detected
    has_overflow = any("overflow" in w.lower() for w in warnings)
    dimensions["content_overflow"] = 0.3 if has_overflow else 1.0
    if has_overflow:
        flags.append("Text overflow detected -- content exceeds placeholder bounds")

    # Content shrink: 1.0 normally, ratio from shrink_info (min 0.3)
    if shrink_info and shrink_info.get("original_size", 0) > 0:
        ratio = shrink_info["final_size"] / shrink_info["original_size"]
        dimensions["content_shrink"] = max(0.3, min(1.0, ratio))
        if ratio < 1.0:
            pct = int((1.0 - ratio) * 100)
            flags.append(f"Content shrunk by {pct}% to fit placeholder")
    else:
        dimensions["content_shrink"] = 1.0

    # Generation status: map to score
    status_str = status if isinstance(status, str) else str(status)
    # Handle enum values (e.g. SlideStatus.SUCCESS -> "success")
    if "." in status_str:
        status_str = status_str.split(".")[-1].lower()
    dimensions["generation_status"] = _STATUS_SCORES.get(status_str.lower(), 0.0)
    if status_str.lower() != "success":
        flags.append(f"Generation status: {status_str}")

    # Weighted sum
    score = sum(
        dimensions[dim] * weight
        for dim, weight in CONFIDENCE_DIMENSIONS.items()
    )
    # Clamp to valid range
    score = max(0.0, min(1.0, score))

    return SlideConfidence(
        slide_number=slide_number,
        score=round(score, 4),
        flags=flags,
        dimensions=dimensions,
    )


def compute_confidence(generation_result: dict) -> list[SlideConfidence]:
    """Compute confidence scores for all slides in a GenerationResult.

    Args:
        generation_result: Dict with "results" key containing list of
            SlideResult-shaped dicts.

    Returns:
        List of SlideConfidence, one per slide in results.
    """
    results = generation_result.get("results", [])
    return [score_slide(slide) for slide in results]
