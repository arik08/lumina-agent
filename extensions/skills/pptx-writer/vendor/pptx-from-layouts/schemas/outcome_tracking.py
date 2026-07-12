"""
Outcome tracking schema for confidence score calibration.

This module defines the data structures for tracking delivery outcomes
and comparing them against predicted confidence scores. The tracked data
enables weight calibration based on actual delivery results.

Key concepts:
- DeliveryOutcome: Actual quality assessment after delivery/review
- PredictionRecord: Captured confidence prediction with later outcome
- OutcomeDataset: Collection of records for calibration analysis
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OutcomeVerdict(str, Enum):
    """Delivery outcome verdict categories.

    These represent the actual quality assessment after human review
    or client delivery, used to compare against predicted confidence.
    """

    EXCELLENT = "excellent"      # No issues, client praised quality
    ACCEPTABLE = "acceptable"    # Minor issues, acceptable for delivery
    NEEDS_REVISION = "needs_revision"  # Required fixes before delivery
    FAILED = "failed"            # Major issues, significant rework needed


class OutcomeSource(str, Enum):
    """Source of the outcome assessment."""

    HUMAN_REVIEW = "human_review"        # Manual quality review
    CLIENT_FEEDBACK = "client_feedback"  # Direct client response
    AUTOMATED_QA = "automated_qa"        # Automated quality testing
    SELF_ASSESSMENT = "self_assessment"  # Creator's own assessment


class DimensionOutcome(BaseModel):
    """Outcome data for a single scoring dimension.

    Tracks whether the predicted dimension score matched reality.
    """

    model_config = ConfigDict(extra="forbid")

    dimension_name: str = Field(
        description="Name of the dimension (e.g., 'layout_fit', 'content_overflow')"
    )
    predicted_score: float = Field(
        ge=0.0, le=1.0,
        description="The predicted dimension score (0-1)"
    )
    was_accurate: bool = Field(
        description="Whether the prediction matched the actual outcome"
    )
    actual_issue: bool = Field(
        description="Whether this dimension had issues in actual delivery"
    )
    notes: str = Field(
        default="",
        description="Optional notes explaining the discrepancy"
    )


class SlideOutcome(BaseModel):
    """Outcome data for a single slide."""

    model_config = ConfigDict(extra="forbid")

    slide_number: int = Field(ge=1, description="1-indexed slide number")
    predicted_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Predicted confidence score for this slide"
    )
    actual_verdict: OutcomeVerdict = Field(
        description="Actual quality verdict for this slide"
    )
    dimension_outcomes: list[DimensionOutcome] = Field(
        default_factory=list,
        description="Per-dimension outcome data"
    )
    had_fallback_issue: bool = Field(
        default=False,
        description="Whether layout fallback was a real problem"
    )
    had_overflow_issue: bool = Field(
        default=False,
        description="Whether text overflow was a real problem"
    )
    had_shrink_issue: bool = Field(
        default=False,
        description="Whether content shrinking was a real problem"
    )
    notes: str = Field(
        default="",
        description="Optional notes about this slide's outcome"
    )


class DeliveryOutcome(BaseModel):
    """Complete outcome record for a presentation delivery.

    Captures the actual quality results after delivery/review,
    enabling comparison with predicted confidence scores.
    """

    model_config = ConfigDict(extra="forbid")

    # Identification
    outcome_id: str = Field(
        description="Unique identifier for this outcome record"
    )
    presentation_id: str = Field(
        description="Identifier linking to the original presentation"
    )
    file_name: str = Field(
        description="Original file name of the presentation"
    )

    # Timing
    generation_timestamp: datetime = Field(
        description="When the presentation was generated"
    )
    outcome_timestamp: datetime = Field(
        description="When the outcome was recorded"
    )

    # Predicted values (captured at generation time)
    predicted_overall_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Overall predicted confidence score"
    )
    predicted_flags_count: int = Field(
        ge=0,
        description="Number of slides flagged at generation time"
    )
    predicted_dimensions: dict[str, float] = Field(
        default_factory=dict,
        description="Average dimension scores at generation time"
    )

    # Actual outcome
    overall_verdict: OutcomeVerdict = Field(
        description="Overall quality verdict for the presentation"
    )
    outcome_source: OutcomeSource = Field(
        description="How the outcome was determined"
    )
    slide_outcomes: list[SlideOutcome] = Field(
        default_factory=list,
        description="Per-slide outcome data"
    )

    # Issue tracking
    issues_found: int = Field(
        ge=0,
        description="Total number of issues found in review"
    )
    issues_predicted: int = Field(
        ge=0,
        description="Number of issues predicted by confidence scoring"
    )
    false_positives: int = Field(
        ge=0,
        description="Flagged issues that weren't actual problems"
    )
    false_negatives: int = Field(
        ge=0,
        description="Actual issues that weren't flagged"
    )

    # Metadata
    reviewer: str = Field(
        default="",
        description="Name/ID of the person who reviewed"
    )
    notes: str = Field(
        default="",
        description="General notes about the delivery outcome"
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for categorizing this outcome"
    )


class PredictionAccuracy(BaseModel):
    """Accuracy metrics for a dimension's predictions."""

    model_config = ConfigDict(extra="forbid")

    dimension_name: str
    total_predictions: int
    true_positives: int    # Predicted issue, was issue
    true_negatives: int    # Predicted no issue, was no issue
    false_positives: int   # Predicted issue, wasn't issue
    false_negatives: int   # Predicted no issue, was issue

    @property
    def accuracy(self) -> float:
        """Calculate overall accuracy."""
        total = self.true_positives + self.true_negatives + self.false_positives + self.false_negatives
        if total == 0:
            return 0.0
        return (self.true_positives + self.true_negatives) / total

    @property
    def precision(self) -> float:
        """Calculate precision (positive predictive value)."""
        positives = self.true_positives + self.false_positives
        if positives == 0:
            return 0.0
        return self.true_positives / positives

    @property
    def recall(self) -> float:
        """Calculate recall (sensitivity)."""
        actual_positives = self.true_positives + self.false_negatives
        if actual_positives == 0:
            return 0.0
        return self.true_positives / actual_positives

    @property
    def f1_score(self) -> float:
        """Calculate F1 score."""
        p, r = self.precision, self.recall
        if p + r == 0:
            return 0.0
        return 2 * (p * r) / (p + r)


class OutcomeDataset(BaseModel):
    """Collection of delivery outcomes for calibration analysis.

    This is the main data structure for storing and loading
    outcome records used in weight calibration.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = Field(
        default="1.0.0",
        description="Schema version for compatibility"
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="When this dataset was created"
    )
    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="When this dataset was last updated"
    )

    outcomes: list[DeliveryOutcome] = Field(
        default_factory=list,
        description="Collection of delivery outcomes"
    )

    # Calibration metadata
    last_calibration: datetime | None = Field(
        default=None,
        description="When weights were last calibrated from this data"
    )
    current_weights: dict[str, float] = Field(
        default_factory=dict,
        description="Current calibrated weights"
    )
    calibration_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="History of weight calibrations"
    )

    def add_outcome(self, outcome: DeliveryOutcome) -> None:
        """Add a new outcome to the dataset."""
        self.outcomes.append(outcome)
        self.updated_at = datetime.now()

    def get_accuracy_by_dimension(self) -> dict[str, PredictionAccuracy]:
        """Calculate prediction accuracy for each dimension."""
        dimension_stats: dict[str, dict[str, int]] = {}

        for outcome in self.outcomes:
            for slide_outcome in outcome.slide_outcomes:
                for dim_outcome in slide_outcome.dimension_outcomes:
                    name = dim_outcome.dimension_name
                    if name not in dimension_stats:
                        dimension_stats[name] = {
                            "tp": 0, "tn": 0, "fp": 0, "fn": 0, "total": 0
                        }

                    stats = dimension_stats[name]
                    stats["total"] += 1

                    # Predicted issue = score < 1.0 (indicating some concern)
                    predicted_issue = dim_outcome.predicted_score < 1.0
                    actual_issue = dim_outcome.actual_issue

                    if predicted_issue and actual_issue:
                        stats["tp"] += 1
                    elif not predicted_issue and not actual_issue:
                        stats["tn"] += 1
                    elif predicted_issue and not actual_issue:
                        stats["fp"] += 1
                    else:  # not predicted_issue and actual_issue
                        stats["fn"] += 1

        return {
            name: PredictionAccuracy(
                dimension_name=name,
                total_predictions=stats["total"],
                true_positives=stats["tp"],
                true_negatives=stats["tn"],
                false_positives=stats["fp"],
                false_negatives=stats["fn"],
            )
            for name, stats in dimension_stats.items()
        }

    def get_overall_accuracy(self) -> dict[str, float]:
        """Calculate overall prediction accuracy metrics."""
        total_outcomes = len(self.outcomes)
        if total_outcomes == 0:
            return {
                "accuracy": 0.0,
                "precision": 0.0,
                "recall": 0.0,
                "f1_score": 0.0,
            }

        tp = fn = fp = tn = 0

        for outcome in self.outcomes:
            # Consider a prediction "positive" (issue) if confidence < 0.8
            predicted_issue = outcome.predicted_overall_confidence < 0.8
            # Actual issue if verdict is needs_revision or failed
            actual_issue = outcome.overall_verdict in (
                OutcomeVerdict.NEEDS_REVISION,
                OutcomeVerdict.FAILED
            )

            if predicted_issue and actual_issue:
                tp += 1
            elif not predicted_issue and not actual_issue:
                tn += 1
            elif predicted_issue and not actual_issue:
                fp += 1
            else:
                fn += 1

        total = tp + tn + fp + fn
        accuracy = (tp + tn) / total if total > 0 else 0.0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        return {
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "total_outcomes": total_outcomes,
            "true_positives": tp,
            "true_negatives": tn,
            "false_positives": fp,
            "false_negatives": fn,
        }

    def save(self, path: Path | str) -> None:
        """Save dataset to a JSON file."""
        path = Path(path)
        path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: Path | str) -> "OutcomeDataset":
        """Load dataset from a JSON file."""
        path = Path(path)
        if not path.exists():
            return cls()
        return cls.model_validate_json(path.read_text())
