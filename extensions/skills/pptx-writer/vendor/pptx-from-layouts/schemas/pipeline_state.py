"""
PipelineState schema for tracking orchestrated PPTX generation workflows.

This module provides the state model for pipeline execution -- tracking which
stages have completed, artifact paths, and per-slide confidence scores. It
enables state persistence, recovery from failures, and confidence-based
feedback loops.

Usage:
    from schemas.pipeline_state import PipelineState, PipelineStage

    # Create initial state
    state = PipelineState(
        pipeline_id="a1b2c3d4e5f6",
        created_at="2026-01-24T00:00:00Z",
        updated_at="2026-01-24T00:00:00Z",
        current_stage=PipelineStage.OUTLINE,
    )

    # Record stage completion
    state.stages.append(StageRecord(
        stage=PipelineStage.OUTLINE,
        completed_at="2026-01-24T00:01:00Z",
        input_path="notes.md",
        output_path="outline.json",
        content_hash="abc123...",
        success=True,
    ))

    # Persist to JSON
    state_json = state.model_dump_json(indent=2)
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PipelineStage(str, Enum):
    """Pipeline execution stages in order."""

    OUTLINE = "outline"
    LAYOUT_PLAN = "layout_plan"
    GENERATED = "generated"
    VALIDATED = "validated"


class StageRecord(BaseModel):
    """Record of one completed pipeline stage.

    Tracks inputs, outputs, and outcome for each stage execution.
    The content_hash enables change detection for incremental reruns.
    """

    stage: PipelineStage
    completed_at: str  # ISO 8601 timestamp
    input_path: str
    output_path: str
    content_hash: str  # SHA-256 of input for change detection
    success: bool
    warnings: list[str] = []
    errors: list[str] = []


class SlideConfidence(BaseModel):
    """Per-slide quality confidence assessment.

    Score is a weighted aggregate of dimension sub-scores.
    Slides scoring below the confidence threshold are flagged
    with human-readable issue descriptions for review.
    """

    slide_number: int
    score: float = Field(ge=0.0, le=1.0)
    flags: list[str] = []  # Human-readable issue descriptions
    dimensions: dict[str, float] = {}  # Sub-scores per dimension


class PipelineState(BaseModel):
    """Complete pipeline execution state.

    Root model representing the full state of a generation pipeline.
    Persisted as JSON between stages, enabling recovery, incremental
    reruns, and confidence-based feedback loops.
    """

    version: str = "1.0"
    pipeline_id: str  # UUID hex[:12]
    created_at: str  # ISO 8601 timestamp
    updated_at: str  # ISO 8601 timestamp
    current_stage: PipelineStage
    stages: list[StageRecord] = []

    # Artifact paths (populated as stages complete)
    outline_path: str | None = None
    layout_plan_path: str | None = None
    pptx_path: str | None = None
    validation_report_path: str | None = None

    # Slide tracking
    slide_count: int = 0
    slide_confidence: list[SlideConfidence] = []
    slide_order: list[int] = []  # Current ordering (layout_plan slide_numbers)

    # Recovery support
    last_successful_stage: PipelineStage | None = None
    recoverable: bool = True
