"""
Performance schema for tracking timing data in the PPTX generation pipeline.

This module provides Pydantic models for performance metrics that can be
embedded in generation results and pipeline state for timing analysis.

Usage:
    from schemas.performance import PerformanceData, PhaseTimingModel

    # Attach to generation result
    result = GenerationResult(
        success=True,
        ...,
    )
    result_dict = result.model_dump()
    result_dict["performance"] = perf_data.model_dump()
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PhaseTimingModel(BaseModel):
    """Timing data for a single phase of processing.

    This is the Pydantic equivalent of the PhaseMetric dataclass,
    suitable for JSON serialization in generation results.
    """

    name: str
    duration_ms: float = Field(ge=0)
    start_time: str  # ISO 8601
    end_time: str  # ISO 8601
    slide_number: int | None = None
    content_type: str | None = None
    count: int = 1  # Number of times this phase was executed (for aggregated phases)
    metadata: dict[str, float | int | str | bool] = {}


class BottleneckInfo(BaseModel):
    """Information about identified performance bottlenecks."""

    phase_name: str
    duration_ms: float = Field(ge=0)
    percentage_of_total: float = Field(ge=0, le=100)
    description: str


class SlideTimingModel(BaseModel):
    """Per-slide timing breakdown."""

    slide_number: int
    duration_ms: float = Field(ge=0)
    content_type: str | None = None


class PerformanceData(BaseModel):
    """Complete performance data for a pipeline run.

    Attach this to GenerationResult or PipelineState to track
    performance metrics for a generation run.
    """

    component: str  # "ingest" or "generate_pptx"
    total_duration_ms: float = Field(ge=0)
    start_time: str  # ISO 8601
    end_time: str  # ISO 8601

    # Phase breakdown (aggregated by phase name)
    phases: list[PhaseTimingModel] = []

    # Bottleneck identification
    bottlenecks: list[BottleneckInfo] = []
    primary_bottleneck: str | None = None  # Name of slowest phase

    # Per-slide timing (for detailed analysis)
    slide_timings: list[SlideTimingModel] = []
    slowest_slide: int | None = None
    slowest_slide_duration_ms: float | None = None

    # Content type aggregation
    content_type_times: dict[str, float] = {}

    # Summary statistics
    avg_slide_time_ms: float | None = None
    median_slide_time_ms: float | None = None
    slides_processed: int = 0


class PipelinePerformance(BaseModel):
    """Performance data across the entire pipeline.

    Combines performance from outline parsing and PPTX generation.
    """

    pipeline_id: str
    total_duration_ms: float = Field(ge=0)
    ingest_performance: PerformanceData | None = None
    generate_performance: PerformanceData | None = None

    # Cross-phase bottleneck analysis
    bottlenecks: list[BottleneckInfo] = []
    slowest_stage: str | None = None  # "ingest" or "generate_pptx"

    @property
    def ingest_percentage(self) -> float:
        """Percentage of total time spent in ingest."""
        if self.total_duration_ms == 0 or self.ingest_performance is None:
            return 0.0
        return (self.ingest_performance.total_duration_ms / self.total_duration_ms) * 100

    @property
    def generate_percentage(self) -> float:
        """Percentage of total time spent in PPTX generation."""
        if self.total_duration_ms == 0 or self.generate_performance is None:
            return 0.0
        return (self.generate_performance.total_duration_ms / self.total_duration_ms) * 100
