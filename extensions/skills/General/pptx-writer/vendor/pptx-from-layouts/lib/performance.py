"""
Performance instrumentation for the PPTX generation pipeline.

Provides timing utilities, bottleneck identification, and performance
reporting for both outline parsing and PPTX generation phases.

Usage:
    from performance import PerfTimer, PerfContext, PhaseMetric

    # Simple timer usage
    with PerfTimer("parse_outline") as timer:
        result = parse_outline(text)
    print(f"Parsing took {timer.duration_ms:.1f}ms")

    # Full context tracking
    ctx = PerfContext("generate_pptx")
    with ctx.phase("load_template"):
        prs = Presentation(template_path)
    with ctx.phase("generate_slides"):
        for slide in slides:
            with ctx.phase("slide", slide_number=i, content_type=slide.content_type):
                generate_slide(slide)

    # Get report
    report = ctx.get_report()
    print(report.format_summary())
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator


@dataclass
class PhaseMetric:
    """Timing metric for a single phase of processing.

    Captures start/end times and optional context like slide number
    or content type for detailed breakdown analysis.
    """

    name: str
    duration_ms: float
    start_time: str  # ISO 8601
    end_time: str  # ISO 8601
    slide_number: int | None = None
    content_type: str | None = None
    sub_phases: list[PhaseMetric] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "name": self.name,
            "duration_ms": round(self.duration_ms, 2),
            "start_time": self.start_time,
            "end_time": self.end_time,
        }
        if self.slide_number is not None:
            result["slide_number"] = self.slide_number
        if self.content_type is not None:
            result["content_type"] = self.content_type
        if self.sub_phases:
            result["sub_phases"] = [p.to_dict() for p in self.sub_phases]
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class PerformanceReport:
    """Complete performance report for a pipeline run.

    Aggregates all phase metrics and identifies bottlenecks.
    """

    component: str
    total_duration_ms: float
    start_time: str
    end_time: str
    phases: list[PhaseMetric] = field(default_factory=list)
    bottleneck: PhaseMetric | None = None
    per_slide_times: dict[int, float] = field(default_factory=dict)
    per_content_type_times: dict[str, float] = field(default_factory=dict)
    slowest_slides: list[tuple[int, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "component": self.component,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "phases": [p.to_dict() for p in self.phases],
        }
        if self.bottleneck:
            result["bottleneck"] = self.bottleneck.to_dict()
        if self.per_slide_times:
            result["per_slide_times"] = {
                str(k): round(v, 2) for k, v in self.per_slide_times.items()
            }
        if self.per_content_type_times:
            result["per_content_type_times"] = {
                k: round(v, 2) for k, v in self.per_content_type_times.items()
            }
        if self.slowest_slides:
            result["slowest_slides"] = [
                {"slide_number": s, "duration_ms": round(t, 2)}
                for s, t in self.slowest_slides
            ]
        return result

    def format_summary(self) -> str:
        """Format a human-readable summary."""
        lines = [
            f"Performance Report: {self.component}",
            "=" * 60,
            f"Total Duration: {self.total_duration_ms:.1f}ms",
            "",
            "Phase Breakdown:",
            "-" * 40,
        ]

        # Calculate percentage of total for each top-level phase
        for phase in self.phases:
            pct = (phase.duration_ms / self.total_duration_ms * 100) if self.total_duration_ms > 0 else 0
            bar_len = int(pct / 2)  # Scale to max 50 chars
            bar = "█" * bar_len
            lines.append(f"  {phase.name:30s} {phase.duration_ms:8.1f}ms ({pct:5.1f}%) {bar}")

        if self.bottleneck:
            lines.extend([
                "",
                "Bottleneck:",
                "-" * 40,
                f"  {self.bottleneck.name}: {self.bottleneck.duration_ms:.1f}ms",
            ])

        if self.slowest_slides:
            lines.extend([
                "",
                "Slowest Slides:",
                "-" * 40,
            ])
            for slide_num, duration in self.slowest_slides[:5]:
                lines.append(f"  Slide {slide_num}: {duration:.1f}ms")

        if self.per_content_type_times:
            lines.extend([
                "",
                "Time by Content Type:",
                "-" * 40,
            ])
            # Sort by total time descending
            sorted_types = sorted(
                self.per_content_type_times.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            for content_type, total_time in sorted_types:
                lines.append(f"  {content_type:30s} {total_time:8.1f}ms")

        return "\n".join(lines)


class PerfTimer:
    """Simple timer for measuring execution duration.

    Can be used as a context manager or manually started/stopped.

    Example:
        with PerfTimer("my_operation") as timer:
            do_something()
        print(f"Took {timer.duration_ms}ms")

        # Or manually:
        timer = PerfTimer("my_operation")
        timer.start()
        do_something()
        timer.stop()
    """

    def __init__(self, name: str):
        self.name = name
        self._start_time: float | None = None
        self._end_time: float | None = None
        self._start_iso: str | None = None
        self._end_iso: str | None = None

    def start(self) -> PerfTimer:
        """Start the timer."""
        self._start_time = time.perf_counter()
        self._start_iso = datetime.now(timezone.utc).isoformat()
        return self

    def stop(self) -> PerfTimer:
        """Stop the timer."""
        self._end_time = time.perf_counter()
        self._end_iso = datetime.now(timezone.utc).isoformat()
        return self

    @property
    def duration_ms(self) -> float:
        """Get duration in milliseconds."""
        if self._start_time is None:
            return 0.0
        end = self._end_time if self._end_time is not None else time.perf_counter()
        return (end - self._start_time) * 1000

    @property
    def start_time(self) -> str:
        """Get start time as ISO 8601."""
        return self._start_iso or ""

    @property
    def end_time(self) -> str:
        """Get end time as ISO 8601."""
        return self._end_iso or ""

    def __enter__(self) -> PerfTimer:
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()

    def to_metric(
        self,
        slide_number: int | None = None,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PhaseMetric:
        """Convert timer to a PhaseMetric."""
        return PhaseMetric(
            name=self.name,
            duration_ms=self.duration_ms,
            start_time=self.start_time,
            end_time=self.end_time,
            slide_number=slide_number,
            content_type=content_type,
            metadata=metadata or {},
        )


class PerfContext:
    """Context for tracking performance across multiple phases.

    Provides hierarchical timing with automatic bottleneck detection
    and per-slide/per-content-type aggregation.

    Example:
        ctx = PerfContext("generate_pptx")

        with ctx.phase("load_template"):
            prs = Presentation(template_path)

        with ctx.phase("generate_slides"):
            for i, slide in enumerate(slides):
                with ctx.phase("slide", slide_number=i, content_type=slide.type):
                    generate_slide(slide)

        report = ctx.get_report()
    """

    def __init__(self, component: str):
        self.component = component
        self._phases: list[PhaseMetric] = []
        self._phase_stack: list[tuple[PerfTimer, dict[str, Any]]] = []
        self._start_time: float | None = None
        self._end_time: float | None = None
        self._start_iso: str | None = None
        self._end_iso: str | None = None
        self._per_slide_times: dict[int, float] = {}
        self._per_content_type_times: dict[str, float] = {}

    def start(self) -> PerfContext:
        """Start the overall context timer."""
        self._start_time = time.perf_counter()
        self._start_iso = datetime.now(timezone.utc).isoformat()
        return self

    def stop(self) -> PerfContext:
        """Stop the overall context timer."""
        self._end_time = time.perf_counter()
        self._end_iso = datetime.now(timezone.utc).isoformat()
        return self

    @property
    def total_duration_ms(self) -> float:
        """Get total duration in milliseconds."""
        if self._start_time is None:
            return 0.0
        end = self._end_time if self._end_time is not None else time.perf_counter()
        return (end - self._start_time) * 1000

    @contextmanager
    def phase(
        self,
        name: str,
        slide_number: int | None = None,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[PerfTimer, None, None]:
        """Context manager for timing a phase.

        Args:
            name: Name of the phase
            slide_number: Optional slide number for per-slide tracking
            content_type: Optional content type for type-based aggregation
            metadata: Optional additional metadata

        Yields:
            PerfTimer instance for the phase
        """
        timer = PerfTimer(name)
        context = {
            "slide_number": slide_number,
            "content_type": content_type,
            "metadata": metadata or {},
        }
        self._phase_stack.append((timer, context))

        timer.start()
        try:
            yield timer
        finally:
            timer.stop()
            self._phase_stack.pop()

            metric = PhaseMetric(
                name=name,
                duration_ms=timer.duration_ms,
                start_time=timer.start_time,
                end_time=timer.end_time,
                slide_number=slide_number,
                content_type=content_type,
                metadata=metadata or {},
            )

            # Add to parent phase or top-level
            if self._phase_stack:
                parent_timer, parent_context = self._phase_stack[-1]
                # We need to track sub-phases differently
                # For now, add to top-level phases
                self._phases.append(metric)
            else:
                self._phases.append(metric)

            # Track per-slide times
            if slide_number is not None:
                self._per_slide_times[slide_number] = (
                    self._per_slide_times.get(slide_number, 0) + timer.duration_ms
                )

            # Track per-content-type times
            if content_type is not None:
                self._per_content_type_times[content_type] = (
                    self._per_content_type_times.get(content_type, 0) + timer.duration_ms
                )

    def record_phase(
        self,
        name: str,
        duration_ms: float,
        slide_number: int | None = None,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PhaseMetric:
        """Manually record a phase metric.

        Use this when you can't use the context manager.
        """
        now = datetime.now(timezone.utc).isoformat()
        metric = PhaseMetric(
            name=name,
            duration_ms=duration_ms,
            start_time=now,
            end_time=now,
            slide_number=slide_number,
            content_type=content_type,
            metadata=metadata or {},
        )
        self._phases.append(metric)

        if slide_number is not None:
            self._per_slide_times[slide_number] = (
                self._per_slide_times.get(slide_number, 0) + duration_ms
            )

        if content_type is not None:
            self._per_content_type_times[content_type] = (
                self._per_content_type_times.get(content_type, 0) + duration_ms
            )

        return metric

    def get_report(self) -> PerformanceReport:
        """Generate a complete performance report."""
        # Stop if not already stopped
        if self._end_time is None:
            self.stop()

        # Find bottleneck (longest top-level phase)
        bottleneck = None
        if self._phases:
            # Group phases by name and sum durations for aggregate bottleneck
            phase_totals: dict[str, float] = {}
            for phase in self._phases:
                phase_totals[phase.name] = phase_totals.get(phase.name, 0) + phase.duration_ms

            # Find the phase with highest total time
            if phase_totals:
                bottleneck_name = max(phase_totals, key=lambda k: phase_totals[k])
                # Get a representative metric for the bottleneck
                for phase in self._phases:
                    if phase.name == bottleneck_name:
                        bottleneck = PhaseMetric(
                            name=bottleneck_name,
                            duration_ms=phase_totals[bottleneck_name],
                            start_time=phase.start_time,
                            end_time=phase.end_time,
                            metadata={"total_time_for_phase_type": phase_totals[bottleneck_name]},
                        )
                        break

        # Find slowest slides
        slowest_slides = sorted(
            self._per_slide_times.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:10]

        # Aggregate phases by name for cleaner reporting
        aggregated_phases: dict[str, PhaseMetric] = {}
        for phase in self._phases:
            if phase.name in aggregated_phases:
                existing = aggregated_phases[phase.name]
                aggregated_phases[phase.name] = PhaseMetric(
                    name=phase.name,
                    duration_ms=existing.duration_ms + phase.duration_ms,
                    start_time=existing.start_time,
                    end_time=phase.end_time,
                    metadata={
                        "count": existing.metadata.get("count", 1) + 1,
                        "avg_ms": (existing.duration_ms + phase.duration_ms) / (existing.metadata.get("count", 1) + 1),
                    },
                )
            else:
                aggregated_phases[phase.name] = PhaseMetric(
                    name=phase.name,
                    duration_ms=phase.duration_ms,
                    start_time=phase.start_time,
                    end_time=phase.end_time,
                    slide_number=phase.slide_number,
                    content_type=phase.content_type,
                    metadata={"count": 1, **phase.metadata},
                )

        return PerformanceReport(
            component=self.component,
            total_duration_ms=self.total_duration_ms,
            start_time=self._start_iso or "",
            end_time=self._end_iso or "",
            phases=list(aggregated_phases.values()),
            bottleneck=bottleneck,
            per_slide_times=dict(self._per_slide_times),
            per_content_type_times=dict(self._per_content_type_times),
            slowest_slides=slowest_slides,
        )

    def __enter__(self) -> PerfContext:
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


def format_duration(ms: float) -> str:
    """Format duration for human display.

    Args:
        ms: Duration in milliseconds

    Returns:
        Human-readable string like "1.2s" or "450ms"
    """
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms:.0f}ms"


def identify_bottlenecks(
    report: PerformanceReport,
    threshold_pct: float = 30.0,
) -> list[str]:
    """Identify potential bottlenecks in a performance report.

    Args:
        report: Performance report to analyze
        threshold_pct: Minimum percentage of total time to be considered a bottleneck

    Returns:
        List of human-readable bottleneck descriptions
    """
    bottlenecks: list[str] = []
    total = report.total_duration_ms

    if total == 0:
        return bottlenecks

    # Check phases that take more than threshold% of total time
    for phase in report.phases:
        pct = (phase.duration_ms / total) * 100
        if pct >= threshold_pct:
            bottlenecks.append(
                f"'{phase.name}' takes {pct:.1f}% of total time ({format_duration(phase.duration_ms)})"
            )

    # Check for slow content types
    if report.per_content_type_times:
        for content_type, time_ms in sorted(
            report.per_content_type_times.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:3]:
            pct = (time_ms / total) * 100
            if pct >= threshold_pct / 2:  # Lower threshold for content types
                bottlenecks.append(
                    f"Content type '{content_type}' takes {pct:.1f}% of time ({format_duration(time_ms)})"
                )

    # Check for outlier slides (more than 3x average)
    if report.per_slide_times:
        avg_slide_time = sum(report.per_slide_times.values()) / len(report.per_slide_times)
        for slide_num, time_ms in report.slowest_slides[:3]:
            if time_ms > avg_slide_time * 3:
                bottlenecks.append(
                    f"Slide {slide_num} is {time_ms / avg_slide_time:.1f}x slower than average ({format_duration(time_ms)} vs {format_duration(avg_slide_time)} avg)"
                )

    return bottlenecks
