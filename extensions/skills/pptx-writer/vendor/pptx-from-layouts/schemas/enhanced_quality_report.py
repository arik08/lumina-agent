"""
Enhanced Quality Report schema with confidence scoring.

This schema extends the basic QualityReport with:
- Confidence scoring for overall and per-component assessments
- Confidence factors that explain what influenced the confidence level
- Statistical metadata for score reliability

The confidence score indicates how reliable the quality assessment is,
based on factors like:
- Number of slides analyzed (more slides = more confidence)
- Component coverage (all Tier 2 validators ran = higher confidence)
- Consistency of results (uniform issues = higher confidence)
- Severity distribution (extreme scores are less confident)

Usage:
    from schemas.enhanced_quality_report import (
        EnhancedQualityReport,
        ConfidenceScore,
        ConfidenceFactor,
        compute_confidence_score,
    )

    # Compute confidence from a basic QualityReport
    confidence = compute_confidence_score(
        quality_report=report,
        slide_count=15,
        tier2_coverage={"typography": True, "whitespace": True, "visual_type": False, "column_balance": False},
    )

    # Create enhanced report
    enhanced = EnhancedQualityReport(
        **report.to_dict(),
        confidence=confidence,
    )
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class ConfidenceLevel(str, Enum):
    """Categorical confidence level for human-readable interpretation."""

    HIGH = "high"          # 80-100%: Very reliable assessment
    MEDIUM = "medium"      # 60-79%: Reasonably reliable, some uncertainty
    LOW = "low"            # 40-59%: Limited reliability, interpret with caution
    VERY_LOW = "very_low"  # 0-39%: Insufficient data for reliable assessment


class ConfidenceFactorType(str, Enum):
    """Types of factors that influence confidence scoring."""

    SAMPLE_SIZE = "sample_size"              # Slide count impact
    COMPONENT_COVERAGE = "component_coverage"  # Tier 2 validator coverage
    SCORE_CONSISTENCY = "score_consistency"    # Variance in component scores
    ISSUE_DISTRIBUTION = "issue_distribution"  # Spread of issues across slides
    EDGE_SCORE = "edge_score"                  # Extreme scores (very high/low)


class ConfidenceFactor(BaseModel):
    """A factor that influences the confidence score.

    Each factor contributes positively or negatively to overall confidence.
    Factors explain WHY the confidence is at a certain level.
    """

    model_config = ConfigDict(extra="forbid")

    factor_type: ConfidenceFactorType = Field(
        description="The type of factor influencing confidence"
    )
    weight: float = Field(
        ge=0.0,
        le=1.0,
        description="Relative importance of this factor (0-1)"
    )
    raw_value: float = Field(
        description="The raw value used for calculation (e.g., slide count, coverage %)"
    )
    contribution: float = Field(
        ge=-1.0,
        le=1.0,
        description="Contribution to confidence (-1 to 1, where 1 is maximum positive)"
    )
    explanation: str = Field(
        description="Human-readable explanation of this factor's impact"
    )


class ComponentConfidence(BaseModel):
    """Confidence score for a single scoring component.

    Each Tier 2 validator (typography, whitespace, etc.) gets its own
    confidence assessment based on the quality of input data.
    """

    model_config = ConfigDict(extra="forbid")

    component_name: str = Field(
        description="Name of the component (e.g., 'typography_hierarchy')"
    )
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="The component's quality score (0-100) if available"
    )
    confidence: float = Field(
        ge=0.0,
        le=100.0,
        description="Confidence in this component's score (0-100%)"
    )
    samples_analyzed: int = Field(
        ge=0,
        description="Number of samples (slides, shapes, etc.) analyzed"
    )
    issues_found: int = Field(
        ge=0,
        description="Number of issues detected by this component"
    )
    data_quality: str = Field(
        default="sufficient",
        description="Quality of input data: 'sufficient', 'limited', 'insufficient'"
    )


class ConfidenceScore(BaseModel):
    """Complete confidence assessment for a quality report.

    The confidence score indicates reliability of the quality assessment.
    Higher confidence means the scores are more trustworthy.
    """

    model_config = ConfigDict(extra="forbid")

    overall: float = Field(
        ge=0.0,
        le=100.0,
        description="Overall confidence percentage (0-100%)"
    )
    factors: list[ConfidenceFactor] = Field(
        default_factory=list,
        description="Factors that influenced the confidence calculation"
    )
    component_confidences: list[ComponentConfidence] = Field(
        default_factory=list,
        description="Per-component confidence breakdown"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional statistical metadata"
    )

    @computed_field
    @property
    def level(self) -> ConfidenceLevel:
        """Categorical confidence level derived from overall percentage."""
        if self.overall >= 80:
            return ConfidenceLevel.HIGH
        elif self.overall >= 60:
            return ConfidenceLevel.MEDIUM
        elif self.overall >= 40:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.VERY_LOW

    @computed_field
    @property
    def level_description(self) -> str:
        """Human-readable description of the confidence level."""
        descriptions = {
            ConfidenceLevel.HIGH: "Assessment is highly reliable with comprehensive data coverage.",
            ConfidenceLevel.MEDIUM: "Assessment is reasonably reliable but may have some gaps.",
            ConfidenceLevel.LOW: "Assessment has limited reliability; interpret with caution.",
            ConfidenceLevel.VERY_LOW: "Insufficient data for reliable assessment; results are indicative only.",
        }
        return descriptions[self.level]


class EnhancedQualityReport(BaseModel):
    """Extended quality report with confidence scoring.

    This model extends the basic QualityReport with:
    - Confidence scoring for reliability assessment
    - Per-component confidence breakdown
    - Factors explaining confidence level
    - Statistical metadata

    The enhanced report is suitable for:
    - Automated decision making (confidence threshold gating)
    - Human review prioritization (low confidence = needs attention)
    - Trend analysis (track confidence over time)
    """

    model_config = ConfigDict(extra="allow")

    # Core fields from QualityReport
    file_path: str = Field(description="Path to the analyzed presentation")
    slide_count: int = Field(ge=0, description="Number of slides in the presentation")
    score: float = Field(ge=0.0, le=100.0, description="Overall quality score (0-100)")
    passed: bool = Field(description="Whether the presentation passed quality checks")
    summary: dict[str, int] = Field(
        description="Issue count summary: {errors, warnings, info}"
    )
    layout_coverage: dict[str, Any] = Field(
        default_factory=dict,
        description="Layout usage and coverage statistics"
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable recommendations for improvement"
    )
    issues: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of quality issues found"
    )

    # Optional Tier 2 and heuristic data (from QualityReport)
    tier2: dict[str, Any] | None = Field(
        default=None,
        description="Tier 2 validator results (typography, visual_type, etc.)"
    )
    heuristic_scoring: dict[str, Any] | None = Field(
        default=None,
        description="Heuristic score breakdown by component"
    )

    # Enhanced confidence scoring
    confidence: ConfidenceScore = Field(
        description="Confidence assessment for this quality report"
    )

    @classmethod
    def from_quality_report_dict(
        cls,
        report_dict: dict[str, Any],
        confidence: ConfidenceScore,
    ) -> "EnhancedQualityReport":
        """Create EnhancedQualityReport from a QualityReport.to_dict() output.

        Args:
            report_dict: Output from QualityReport.to_dict()
            confidence: Pre-computed confidence score

        Returns:
            EnhancedQualityReport with confidence data
        """
        return cls(
            file_path=report_dict.get("file_path", ""),
            slide_count=report_dict.get("slide_count", 0),
            score=report_dict.get("score", 0.0),
            passed=report_dict.get("passed", False),
            summary=report_dict.get("summary", {"errors": 0, "warnings": 0, "info": 0}),
            layout_coverage=report_dict.get("layout_coverage", {}),
            recommendations=report_dict.get("recommendations", []),
            issues=report_dict.get("issues", []),
            tier2=report_dict.get("tier2"),
            heuristic_scoring=report_dict.get("heuristic_scoring"),
            confidence=confidence,
        )


# =============================================================================
# CONFIDENCE SCORING ALGORITHM
# =============================================================================

# Default weights for confidence factors
DEFAULT_CONFIDENCE_WEIGHTS = {
    ConfidenceFactorType.SAMPLE_SIZE: 0.30,          # Slide count
    ConfidenceFactorType.COMPONENT_COVERAGE: 0.25,   # Tier 2 coverage
    ConfidenceFactorType.SCORE_CONSISTENCY: 0.20,    # Score variance
    ConfidenceFactorType.ISSUE_DISTRIBUTION: 0.15,   # Issue spread
    ConfidenceFactorType.EDGE_SCORE: 0.10,           # Extreme score penalty
}

# Thresholds for sample size confidence
MIN_SLIDES_FOR_CONFIDENCE = 3       # Minimum slides for any confidence
IDEAL_SLIDES_FOR_CONFIDENCE = 15    # Target slides for full confidence


def _sigmoid(x: float, k: float = 1.0, x0: float = 0.0) -> float:
    """Sigmoid function for smooth scaling.

    Args:
        x: Input value
        k: Steepness parameter (higher = steeper)
        x0: Midpoint (where output = 0.5)

    Returns:
        Value between 0 and 1
    """
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - x0)))
    except OverflowError:
        return 0.0 if x < x0 else 1.0


def _compute_sample_size_contribution(
    slide_count: int,
    min_slides: int = MIN_SLIDES_FOR_CONFIDENCE,
    ideal_slides: int = IDEAL_SLIDES_FOR_CONFIDENCE,
) -> tuple[float, str]:
    """Compute confidence contribution from sample size (slide count).

    More slides = higher confidence, with diminishing returns.

    Args:
        slide_count: Number of slides analyzed
        min_slides: Minimum for meaningful analysis
        ideal_slides: Target for full confidence

    Returns:
        Tuple of (contribution: -1 to 1, explanation: str)
    """
    if slide_count < min_slides:
        contribution = -0.5 + (slide_count / min_slides) * 0.5
        explanation = f"Only {slide_count} slides analyzed (minimum {min_slides} recommended)"
    elif slide_count < ideal_slides:
        # Linear interpolation from 0 to 0.8
        progress = (slide_count - min_slides) / (ideal_slides - min_slides)
        contribution = progress * 0.8
        explanation = f"{slide_count} slides analyzed ({ideal_slides}+ recommended for high confidence)"
    else:
        # Sigmoid curve for diminishing returns above ideal
        extra = slide_count - ideal_slides
        bonus = _sigmoid(extra, k=0.1, x0=10) * 0.2
        contribution = 0.8 + bonus
        explanation = f"{slide_count} slides analyzed (excellent sample size)"

    return min(1.0, max(-1.0, contribution)), explanation


def _compute_component_coverage_contribution(
    tier2_coverage: dict[str, bool],
) -> tuple[float, str]:
    """Compute confidence contribution from Tier 2 validator coverage.

    More validators running = higher confidence.

    Args:
        tier2_coverage: Dict of {component_name: ran_successfully}

    Returns:
        Tuple of (contribution: -1 to 1, explanation: str)
    """
    if not tier2_coverage:
        return -0.3, "No Tier 2 validators ran (core checks only)"

    total = len(tier2_coverage)
    active = sum(1 for v in tier2_coverage.values() if v)
    coverage_pct = active / total if total > 0 else 0

    if coverage_pct >= 1.0:
        contribution = 1.0
        explanation = f"All {total} Tier 2 validators ran successfully"
    elif coverage_pct >= 0.75:
        contribution = 0.7
        explanation = f"{active}/{total} Tier 2 validators ran ({coverage_pct:.0%} coverage)"
    elif coverage_pct >= 0.5:
        contribution = 0.4
        explanation = f"Only {active}/{total} Tier 2 validators ran ({coverage_pct:.0%} coverage)"
    else:
        contribution = -0.2 + coverage_pct * 0.4
        explanation = f"Limited validation: only {active}/{total} validators ran"

    return contribution, explanation


def _compute_score_consistency_contribution(
    component_scores: dict[str, float | None],
) -> tuple[float, str]:
    """Compute confidence contribution from score consistency across components.

    Low variance = higher confidence (components agree).
    High variance = lower confidence (mixed signals).

    Args:
        component_scores: Dict of {component_name: score or None}

    Returns:
        Tuple of (contribution: -1 to 1, explanation: str)
    """
    scores = [s for s in component_scores.values() if s is not None]

    if len(scores) < 2:
        return 0.0, "Not enough components for consistency analysis"

    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    std_dev = math.sqrt(variance)

    # Normalize by score range (0-100)
    normalized_std = std_dev / 100.0

    if normalized_std <= 0.05:  # Very consistent (std <= 5 points)
        contribution = 0.8
        explanation = f"Component scores highly consistent (std dev: {std_dev:.1f})"
    elif normalized_std <= 0.10:  # Reasonably consistent
        contribution = 0.5
        explanation = f"Component scores reasonably consistent (std dev: {std_dev:.1f})"
    elif normalized_std <= 0.20:  # Moderate variance
        contribution = 0.1
        explanation = f"Component scores show moderate variance (std dev: {std_dev:.1f})"
    else:  # High variance
        contribution = -0.3
        explanation = f"Component scores vary significantly (std dev: {std_dev:.1f})"

    return contribution, explanation


def _compute_issue_distribution_contribution(
    issues: list[dict[str, Any]],
    slide_count: int,
) -> tuple[float, str]:
    """Compute confidence contribution from issue distribution across slides.

    Issues spread across many slides = higher confidence (systematic analysis).
    Issues concentrated on few slides = lower confidence (may be isolated).

    Args:
        issues: List of issue dicts with slide_number field
        slide_count: Total slides in presentation

    Returns:
        Tuple of (contribution: -1 to 1, explanation: str)
    """
    if slide_count == 0:
        return 0.0, "No slides to analyze"

    if not issues:
        # No issues found - this is fine, but doesn't boost confidence
        return 0.3, "No issues found (clean presentation)"

    # Count slides with issues
    slides_with_issues = set()
    for issue in issues:
        slide_num = issue.get("slide_number", 0)
        if slide_num > 0:  # Exclude global issues (slide_number=0)
            slides_with_issues.add(slide_num)

    coverage = len(slides_with_issues) / slide_count if slide_count > 0 else 0

    # Some issues spread across slides is good for confidence
    # (shows validator examined multiple slides)
    if 0.2 <= coverage <= 0.6:
        contribution = 0.5
        explanation = f"Issues found across {len(slides_with_issues)}/{slide_count} slides (good coverage)"
    elif coverage < 0.2:
        contribution = 0.2
        explanation = f"Issues concentrated on {len(slides_with_issues)}/{slide_count} slides"
    else:
        # Too many slides with issues suggests systematic problems
        contribution = 0.3
        explanation = f"Issues found on {len(slides_with_issues)}/{slide_count} slides (widespread)"

    return contribution, explanation


def _compute_edge_score_contribution(score: float) -> tuple[float, str]:
    """Compute confidence contribution based on score extremity.

    Scores near 0 or 100 have lower confidence (may be edge cases).
    Mid-range scores have natural higher confidence.

    Args:
        score: The quality score (0-100)

    Returns:
        Tuple of (contribution: -1 to 1, explanation: str)
    """
    # Distance from center (50)
    distance_from_center = abs(score - 50)

    # Perfect scores are suspicious (may have missed things)
    if score >= 98:
        contribution = -0.2
        explanation = f"Near-perfect score ({score:.0f}) may indicate incomplete analysis"
    elif score <= 5:
        contribution = -0.3
        explanation = f"Very low score ({score:.0f}) may indicate data quality issues"
    elif distance_from_center <= 15:
        contribution = 0.3
        explanation = f"Score ({score:.0f}) is in a reliable mid-range"
    else:
        # Slight penalty for extreme but not suspicious scores
        penalty = (distance_from_center - 15) / 50 * 0.2
        contribution = 0.1 - penalty
        explanation = f"Score ({score:.0f}) is moderately extreme"

    return contribution, explanation


def compute_confidence_score(
    score: float,
    slide_count: int,
    issues: list[dict[str, Any]],
    tier2_coverage: dict[str, bool] | None = None,
    component_scores: dict[str, float | None] | None = None,
    tier2_results: dict[str, Any] | None = None,
    weights: dict[ConfidenceFactorType, float] | None = None,
) -> ConfidenceScore:
    """Compute comprehensive confidence score for a quality report.

    The confidence score indicates how reliable the quality assessment is.
    Higher confidence means the scores can be trusted for decision-making.

    Args:
        score: Overall quality score (0-100)
        slide_count: Number of slides analyzed
        issues: List of issue dicts from QualityReport
        tier2_coverage: Optional dict of {component: ran_successfully}
        component_scores: Optional dict of {component: score}
        tier2_results: Optional Tier 2 results dict for component confidence
        weights: Optional custom weights for factors

    Returns:
        ConfidenceScore with overall confidence and breakdown
    """
    weights = weights or DEFAULT_CONFIDENCE_WEIGHTS.copy()
    factors: list[ConfidenceFactor] = []

    # 1. Sample size contribution
    contribution, explanation = _compute_sample_size_contribution(slide_count)
    factors.append(ConfidenceFactor(
        factor_type=ConfidenceFactorType.SAMPLE_SIZE,
        weight=weights[ConfidenceFactorType.SAMPLE_SIZE],
        raw_value=float(slide_count),
        contribution=contribution,
        explanation=explanation,
    ))

    # 2. Component coverage contribution
    if tier2_coverage is None:
        tier2_coverage = {}
    contribution, explanation = _compute_component_coverage_contribution(tier2_coverage)
    factors.append(ConfidenceFactor(
        factor_type=ConfidenceFactorType.COMPONENT_COVERAGE,
        weight=weights[ConfidenceFactorType.COMPONENT_COVERAGE],
        raw_value=sum(1 for v in tier2_coverage.values() if v) / max(1, len(tier2_coverage)) * 100,
        contribution=contribution,
        explanation=explanation,
    ))

    # 3. Score consistency contribution
    if component_scores is None:
        component_scores = {}
    contribution, explanation = _compute_score_consistency_contribution(component_scores)
    factors.append(ConfidenceFactor(
        factor_type=ConfidenceFactorType.SCORE_CONSISTENCY,
        weight=weights[ConfidenceFactorType.SCORE_CONSISTENCY],
        raw_value=len([s for s in component_scores.values() if s is not None]),
        contribution=contribution,
        explanation=explanation,
    ))

    # 4. Issue distribution contribution
    contribution, explanation = _compute_issue_distribution_contribution(issues, slide_count)
    factors.append(ConfidenceFactor(
        factor_type=ConfidenceFactorType.ISSUE_DISTRIBUTION,
        weight=weights[ConfidenceFactorType.ISSUE_DISTRIBUTION],
        raw_value=float(len(issues)),
        contribution=contribution,
        explanation=explanation,
    ))

    # 5. Edge score contribution
    contribution, explanation = _compute_edge_score_contribution(score)
    factors.append(ConfidenceFactor(
        factor_type=ConfidenceFactorType.EDGE_SCORE,
        weight=weights[ConfidenceFactorType.EDGE_SCORE],
        raw_value=score,
        contribution=contribution,
        explanation=explanation,
    ))

    # Compute overall confidence
    # Base confidence is 50%, factors adjust up/down
    base_confidence = 50.0
    weighted_contribution = sum(
        f.contribution * f.weight * 100 for f in factors
    )
    overall = base_confidence + weighted_contribution
    overall = max(0.0, min(100.0, overall))

    # Build component confidences
    component_confidences: list[ComponentConfidence] = []

    # Core quality always has some confidence based on slide count
    core_conf = min(100.0, 50.0 + (slide_count / IDEAL_SLIDES_FOR_CONFIDENCE) * 50)
    component_confidences.append(ComponentConfidence(
        component_name="core_quality",
        score=score,
        confidence=core_conf,
        samples_analyzed=slide_count,
        issues_found=len(issues),
        data_quality="sufficient" if slide_count >= MIN_SLIDES_FOR_CONFIDENCE else "limited",
    ))

    # Add Tier 2 component confidences
    if tier2_results:
        for comp_name, comp_data in tier2_results.items():
            if comp_data is None or not isinstance(comp_data, dict):
                continue

            has_error = comp_data.get("error") is not None
            comp_score = comp_data.get("score")
            summary = comp_data.get("summary", {})
            issue_count = sum(summary.get(k, 0) for k in ["errors", "warnings", "info"])

            if has_error:
                confidence = 0.0
                data_quality = "insufficient"
            elif comp_score is not None:
                # Confidence based on score being available and slide count
                confidence = min(100.0, 40.0 + (slide_count / IDEAL_SLIDES_FOR_CONFIDENCE) * 60)
                data_quality = "sufficient"
            else:
                confidence = 20.0
                data_quality = "limited"

            component_confidences.append(ComponentConfidence(
                component_name=comp_name,
                score=comp_score,
                confidence=confidence,
                samples_analyzed=slide_count,
                issues_found=issue_count,
                data_quality=data_quality,
            ))

    # Build metadata
    metadata = {
        "algorithm_version": "1.0.0",
        "weights_used": {k.value: v for k, v in weights.items()},
        "base_confidence": base_confidence,
        "weighted_adjustment": weighted_contribution,
    }

    return ConfidenceScore(
        overall=round(overall, 1),
        factors=factors,
        component_confidences=component_confidences,
        metadata=metadata,
    )


def compute_confidence_from_quality_report(
    report_dict: dict[str, Any],
) -> ConfidenceScore:
    """Convenience function to compute confidence from a QualityReport.to_dict().

    This extracts all necessary information from the report dict and
    computes the confidence score.

    Args:
        report_dict: Output from QualityReport.to_dict()

    Returns:
        ConfidenceScore for the report
    """
    # Extract basic info
    score = report_dict.get("score", 0.0)
    slide_count = report_dict.get("slide_count", 0)
    issues = report_dict.get("issues", [])
    tier2 = report_dict.get("tier2", {}) or {}
    heuristic = report_dict.get("heuristic_scoring", {}) or {}

    # Determine Tier 2 coverage
    tier2_coverage = {}
    for comp in ["typography_hierarchy", "visual_type", "column_balance", "whitespace"]:
        comp_data = tier2.get(comp)
        if comp_data is not None:
            tier2_coverage[comp] = comp_data.get("error") is None
        else:
            tier2_coverage[comp] = False

    # Extract component scores
    component_scores = {}
    components = heuristic.get("components", {})
    for comp_name, comp_score in components.items():
        component_scores[comp_name] = comp_score

    return compute_confidence_score(
        score=score,
        slide_count=slide_count,
        issues=issues,
        tier2_coverage=tier2_coverage,
        component_scores=component_scores,
        tier2_results=tier2,
    )
