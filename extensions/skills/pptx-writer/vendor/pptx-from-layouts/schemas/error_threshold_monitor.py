"""
Error threshold monitoring schema with trend analysis.

This module defines data structures for tracking error rates over time,
computing trends, and alerting when thresholds are exceeded.

Key concepts:
- ErrorSnapshot: Point-in-time error counts from a validation run
- ErrorTrend: Computed trend (increasing, decreasing, stable) with statistics
- ThresholdConfig: Configurable thresholds for alerting
- ErrorMonitorState: Persistent state for tracking error history

Usage:
    from schemas.error_threshold_monitor import (
        ErrorSnapshot,
        ErrorTrend,
        ThresholdConfig,
        ErrorMonitorState,
        TrendDirection,
    )

    # Create snapshots from validation runs
    snapshot = ErrorSnapshot(
        timestamp=datetime.now(),
        source_file="presentation.pptx",
        error_count=5,
        warning_count=10,
        info_count=3,
    )

    # Track in monitor state
    state = ErrorMonitorState.load(Path(".error_monitor.json"))
    state.add_snapshot(snapshot)
    trend = state.compute_trend()
    alerts = state.check_thresholds()
    state.save(Path(".error_monitor.json"))
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class TrendDirection(str, Enum):
    """Direction of error rate trend over time."""

    INCREASING = "increasing"    # Errors are trending upward
    DECREASING = "decreasing"    # Errors are trending downward
    STABLE = "stable"            # Errors are relatively constant
    INSUFFICIENT_DATA = "insufficient_data"  # Not enough data points


class AlertSeverity(str, Enum):
    """Severity level for threshold alerts."""

    CRITICAL = "critical"   # Requires immediate attention
    WARNING = "warning"     # Should be addressed soon
    INFO = "info"           # Informational notice


class ErrorSnapshot(BaseModel):
    """Point-in-time snapshot of error counts from a validation run.

    Captures the error state at a specific moment for trend analysis.
    """

    # Allow extra fields during parsing (for computed fields) but ignore them
    model_config = ConfigDict(extra="ignore")

    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When this snapshot was taken"
    )
    source_file: str = Field(
        description="Path or identifier of the validated file"
    )
    error_count: int = Field(
        ge=0,
        description="Number of ERROR-level issues"
    )
    warning_count: int = Field(
        ge=0,
        description="Number of WARNING-level issues"
    )
    info_count: int = Field(
        ge=0,
        description="Number of INFO-level issues"
    )
    quality_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Overall quality score (0-100)"
    )
    slide_count: int = Field(
        default=0,
        ge=0,
        description="Number of slides in the presentation"
    )
    categories: dict[str, int] = Field(
        default_factory=dict,
        description="Error counts by category (e.g., 'placeholder_text': 2)"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context about this validation run"
    )

    @computed_field
    @property
    def total_issues(self) -> int:
        """Total number of issues across all severities."""
        return self.error_count + self.warning_count + self.info_count

    @computed_field
    @property
    def error_rate(self) -> float:
        """Error rate as errors per slide (0 if no slides)."""
        if self.slide_count == 0:
            return 0.0
        return self.error_count / self.slide_count

    @computed_field
    @property
    def weighted_issue_score(self) -> float:
        """Weighted issue score: errors=10, warnings=3, info=1."""
        return self.error_count * 10 + self.warning_count * 3 + self.info_count


class TrendStatistics(BaseModel):
    """Statistical analysis of error trend over time."""

    model_config = ConfigDict(extra="forbid")

    sample_count: int = Field(
        ge=0,
        description="Number of data points analyzed"
    )
    time_span_hours: float = Field(
        ge=0.0,
        description="Time span covered by the data (in hours)"
    )
    mean_errors: float = Field(
        description="Mean error count across samples"
    )
    mean_warnings: float = Field(
        description="Mean warning count across samples"
    )
    std_dev_errors: float = Field(
        ge=0.0,
        description="Standard deviation of error counts"
    )
    min_errors: int = Field(
        ge=0,
        description="Minimum error count observed"
    )
    max_errors: int = Field(
        ge=0,
        description="Maximum error count observed"
    )
    slope: float = Field(
        description="Linear regression slope (errors per hour)"
    )
    r_squared: float = Field(
        ge=0.0,
        le=1.0,
        description="R-squared value for linear fit (0-1)"
    )


class ErrorTrend(BaseModel):
    """Computed trend from error history with statistical analysis.

    Provides trend direction, statistics, and confidence metrics.
    """

    model_config = ConfigDict(extra="forbid")

    direction: TrendDirection = Field(
        description="Overall trend direction"
    )
    statistics: TrendStatistics | None = Field(
        default=None,
        description="Statistical analysis (None if insufficient data)"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in trend assessment (0-1)"
    )
    description: str = Field(
        description="Human-readable trend description"
    )
    recent_change_pct: float = Field(
        default=0.0,
        description="Percentage change in recent period vs earlier"
    )


class ThresholdConfig(BaseModel):
    """Configurable thresholds for error monitoring alerts.

    Defines when alerts should be triggered based on error counts,
    rates, and trends.
    """

    model_config = ConfigDict(extra="forbid")

    # Absolute thresholds
    max_errors_critical: int = Field(
        default=10,
        ge=0,
        description="Error count triggering CRITICAL alert"
    )
    max_errors_warning: int = Field(
        default=5,
        ge=0,
        description="Error count triggering WARNING alert"
    )
    max_warnings_critical: int = Field(
        default=20,
        ge=0,
        description="Warning count triggering CRITICAL alert"
    )
    max_warnings_warning: int = Field(
        default=10,
        ge=0,
        description="Warning count triggering WARNING alert"
    )

    # Rate-based thresholds (per slide)
    max_error_rate_critical: float = Field(
        default=0.5,
        ge=0.0,
        description="Errors per slide triggering CRITICAL alert"
    )
    max_error_rate_warning: float = Field(
        default=0.2,
        ge=0.0,
        description="Errors per slide triggering WARNING alert"
    )

    # Trend-based thresholds
    trend_increase_pct_warning: float = Field(
        default=25.0,
        ge=0.0,
        description="Percentage increase triggering WARNING"
    )
    trend_increase_pct_critical: float = Field(
        default=50.0,
        ge=0.0,
        description="Percentage increase triggering CRITICAL"
    )

    # Quality score thresholds
    min_quality_score_warning: float = Field(
        default=70.0,
        ge=0.0,
        le=100.0,
        description="Quality score below this triggers WARNING"
    )
    min_quality_score_critical: float = Field(
        default=50.0,
        ge=0.0,
        le=100.0,
        description="Quality score below this triggers CRITICAL"
    )

    # Monitoring settings
    trend_window_hours: float = Field(
        default=24.0,
        gt=0.0,
        description="Time window for trend analysis (hours)"
    )
    min_samples_for_trend: int = Field(
        default=3,
        ge=2,
        description="Minimum samples required for trend analysis"
    )
    max_history_entries: int = Field(
        default=100,
        ge=10,
        description="Maximum number of snapshots to retain"
    )


class ThresholdAlert(BaseModel):
    """Alert generated when a threshold is exceeded."""

    model_config = ConfigDict(extra="forbid")

    severity: AlertSeverity = Field(
        description="Alert severity level"
    )
    alert_type: str = Field(
        description="Type of threshold exceeded (e.g., 'error_count', 'trend_increase')"
    )
    message: str = Field(
        description="Human-readable alert message"
    )
    current_value: float = Field(
        description="Current value that triggered the alert"
    )
    threshold_value: float = Field(
        description="Threshold value that was exceeded"
    )
    recommendation: str = Field(
        description="Suggested action to address the alert"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When this alert was generated"
    )


class ErrorMonitorState(BaseModel):
    """Persistent state for error threshold monitoring.

    Tracks error history over time, computes trends, and generates
    alerts when thresholds are exceeded. Supports persistence to disk.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = Field(
        default="1.0.0",
        description="Schema version for compatibility"
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="When this monitor was created"
    )
    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="When this monitor was last updated"
    )

    config: ThresholdConfig = Field(
        default_factory=ThresholdConfig,
        description="Threshold configuration"
    )
    snapshots: list[ErrorSnapshot] = Field(
        default_factory=list,
        description="Historical error snapshots"
    )
    last_trend: ErrorTrend | None = Field(
        default=None,
        description="Most recently computed trend"
    )
    alerts_history: list[ThresholdAlert] = Field(
        default_factory=list,
        description="History of generated alerts"
    )

    def add_snapshot(self, snapshot: ErrorSnapshot) -> None:
        """Add a new snapshot and prune old entries if needed.

        Args:
            snapshot: The error snapshot to add
        """
        self.snapshots.append(snapshot)
        self.updated_at = datetime.now()

        # Prune old entries
        if len(self.snapshots) > self.config.max_history_entries:
            # Keep most recent entries
            self.snapshots = self.snapshots[-self.config.max_history_entries:]

    def get_recent_snapshots(self, hours: float | None = None) -> list[ErrorSnapshot]:
        """Get snapshots within the specified time window.

        Args:
            hours: Time window in hours (uses config default if None)

        Returns:
            List of snapshots within the time window
        """
        if hours is None:
            hours = self.config.trend_window_hours

        cutoff = datetime.now() - timedelta(hours=hours)
        return [s for s in self.snapshots if s.timestamp >= cutoff]

    def compute_trend(self) -> ErrorTrend:
        """Compute error trend from recent history.

        Uses linear regression on error counts over time to determine
        trend direction and statistics.

        Returns:
            ErrorTrend with direction, statistics, and confidence
        """
        recent = self.get_recent_snapshots()

        if len(recent) < self.config.min_samples_for_trend:
            trend = ErrorTrend(
                direction=TrendDirection.INSUFFICIENT_DATA,
                confidence=0.0,
                description=f"Need at least {self.config.min_samples_for_trend} samples "
                           f"(have {len(recent)})",
            )
            self.last_trend = trend
            return trend

        # Calculate time span
        timestamps = [s.timestamp for s in recent]
        time_span = (max(timestamps) - min(timestamps)).total_seconds() / 3600  # hours

        # Extract error counts and convert times to hours from first sample
        base_time = min(timestamps)
        x_values = [(s.timestamp - base_time).total_seconds() / 3600 for s in recent]
        y_errors = [s.error_count for s in recent]
        y_warnings = [s.warning_count for s in recent]

        # Calculate statistics
        n = len(recent)
        mean_errors = sum(y_errors) / n
        mean_warnings = sum(y_warnings) / n

        # Standard deviation
        if n > 1:
            variance = sum((y - mean_errors) ** 2 for y in y_errors) / (n - 1)
            std_dev = math.sqrt(variance)
        else:
            std_dev = 0.0

        # Linear regression for slope
        slope, r_squared = self._linear_regression(x_values, y_errors)

        statistics = TrendStatistics(
            sample_count=n,
            time_span_hours=time_span,
            mean_errors=round(mean_errors, 2),
            mean_warnings=round(mean_warnings, 2),
            std_dev_errors=round(std_dev, 2),
            min_errors=min(y_errors),
            max_errors=max(y_errors),
            slope=round(slope, 4),
            r_squared=round(r_squared, 4),
        )

        # Determine trend direction
        # Consider significant if slope magnitude > 0.1 errors/hour with R² > 0.3
        if r_squared < 0.3 or abs(slope) < 0.1:
            direction = TrendDirection.STABLE
            confidence = max(0.3, r_squared)
        elif slope > 0:
            direction = TrendDirection.INCREASING
            confidence = min(0.9, r_squared)
        else:
            direction = TrendDirection.DECREASING
            confidence = min(0.9, r_squared)

        # Calculate recent change percentage
        if len(recent) >= 2:
            # Compare first half to second half
            mid = len(recent) // 2
            first_half_mean = sum(s.error_count for s in recent[:mid]) / mid if mid > 0 else 0
            second_half_mean = sum(s.error_count for s in recent[mid:]) / (n - mid) if n > mid else 0

            if first_half_mean > 0:
                recent_change_pct = ((second_half_mean - first_half_mean) / first_half_mean) * 100
            elif second_half_mean > 0:
                recent_change_pct = 100.0  # Went from 0 to some errors
            else:
                recent_change_pct = 0.0
        else:
            recent_change_pct = 0.0

        # Build description
        if direction == TrendDirection.STABLE:
            description = f"Error rate is stable (mean: {mean_errors:.1f}, std: {std_dev:.1f})"
        elif direction == TrendDirection.INCREASING:
            description = f"Errors are increasing ({slope:+.2f}/hour, {recent_change_pct:+.1f}% change)"
        else:
            description = f"Errors are decreasing ({slope:+.2f}/hour, {recent_change_pct:+.1f}% change)"

        trend = ErrorTrend(
            direction=direction,
            statistics=statistics,
            confidence=round(confidence, 2),
            description=description,
            recent_change_pct=round(recent_change_pct, 1),
        )
        self.last_trend = trend
        return trend

    def _linear_regression(self, x: list[float], y: list[int]) -> tuple[float, float]:
        """Perform simple linear regression.

        Args:
            x: Independent variable values (time)
            y: Dependent variable values (errors)

        Returns:
            Tuple of (slope, r_squared)
        """
        n = len(x)
        if n < 2:
            return 0.0, 0.0

        # Calculate means
        mean_x = sum(x) / n
        mean_y = sum(y) / n

        # Calculate slope and intercept
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denominator = sum((xi - mean_x) ** 2 for xi in x)

        if denominator == 0:
            return 0.0, 0.0

        slope = numerator / denominator

        # Calculate R-squared
        y_pred = [mean_y + slope * (xi - mean_x) for xi in x]
        ss_res = sum((yi - yp) ** 2 for yi, yp in zip(y, y_pred))
        ss_tot = sum((yi - mean_y) ** 2 for yi in y)

        if ss_tot == 0:
            r_squared = 1.0 if ss_res == 0 else 0.0
        else:
            r_squared = max(0.0, 1.0 - (ss_res / ss_tot))

        return slope, r_squared

    def check_thresholds(self, snapshot: ErrorSnapshot | None = None) -> list[ThresholdAlert]:
        """Check if any thresholds are exceeded and generate alerts.

        Args:
            snapshot: Specific snapshot to check (uses latest if None)

        Returns:
            List of threshold alerts (empty if all thresholds pass)
        """
        if snapshot is None:
            if not self.snapshots:
                return []
            snapshot = self.snapshots[-1]

        alerts: list[ThresholdAlert] = []

        # Check error count thresholds
        if snapshot.error_count >= self.config.max_errors_critical:
            alerts.append(ThresholdAlert(
                severity=AlertSeverity.CRITICAL,
                alert_type="error_count",
                message=f"CRITICAL: {snapshot.error_count} errors exceeds critical threshold",
                current_value=snapshot.error_count,
                threshold_value=self.config.max_errors_critical,
                recommendation="Immediately review and fix all ERROR-level issues before delivery",
            ))
        elif snapshot.error_count >= self.config.max_errors_warning:
            alerts.append(ThresholdAlert(
                severity=AlertSeverity.WARNING,
                alert_type="error_count",
                message=f"WARNING: {snapshot.error_count} errors exceeds warning threshold",
                current_value=snapshot.error_count,
                threshold_value=self.config.max_errors_warning,
                recommendation="Review and address ERROR-level issues",
            ))

        # Check warning count thresholds
        if snapshot.warning_count >= self.config.max_warnings_critical:
            alerts.append(ThresholdAlert(
                severity=AlertSeverity.CRITICAL,
                alert_type="warning_count",
                message=f"CRITICAL: {snapshot.warning_count} warnings exceeds critical threshold",
                current_value=snapshot.warning_count,
                threshold_value=self.config.max_warnings_critical,
                recommendation="Review all WARNING-level issues - many may indicate systematic problems",
            ))
        elif snapshot.warning_count >= self.config.max_warnings_warning:
            alerts.append(ThresholdAlert(
                severity=AlertSeverity.WARNING,
                alert_type="warning_count",
                message=f"WARNING: {snapshot.warning_count} warnings exceeds threshold",
                current_value=snapshot.warning_count,
                threshold_value=self.config.max_warnings_warning,
                recommendation="Review WARNING-level issues for potential improvements",
            ))

        # Check error rate thresholds
        if snapshot.error_rate >= self.config.max_error_rate_critical:
            alerts.append(ThresholdAlert(
                severity=AlertSeverity.CRITICAL,
                alert_type="error_rate",
                message=f"CRITICAL: Error rate {snapshot.error_rate:.2f}/slide exceeds critical threshold",
                current_value=snapshot.error_rate,
                threshold_value=self.config.max_error_rate_critical,
                recommendation="Presentation has systematic issues - review generation process",
            ))
        elif snapshot.error_rate >= self.config.max_error_rate_warning:
            alerts.append(ThresholdAlert(
                severity=AlertSeverity.WARNING,
                alert_type="error_rate",
                message=f"WARNING: Error rate {snapshot.error_rate:.2f}/slide exceeds threshold",
                current_value=snapshot.error_rate,
                threshold_value=self.config.max_error_rate_warning,
                recommendation="Consider reviewing content or generation approach",
            ))

        # Check quality score thresholds
        if snapshot.quality_score > 0:  # Only check if score was captured
            if snapshot.quality_score < self.config.min_quality_score_critical:
                alerts.append(ThresholdAlert(
                    severity=AlertSeverity.CRITICAL,
                    alert_type="quality_score",
                    message=f"CRITICAL: Quality score {snapshot.quality_score:.1f} below critical threshold",
                    current_value=snapshot.quality_score,
                    threshold_value=self.config.min_quality_score_critical,
                    recommendation="Presentation quality is critically low - major revision needed",
                ))
            elif snapshot.quality_score < self.config.min_quality_score_warning:
                alerts.append(ThresholdAlert(
                    severity=AlertSeverity.WARNING,
                    alert_type="quality_score",
                    message=f"WARNING: Quality score {snapshot.quality_score:.1f} below threshold",
                    current_value=snapshot.quality_score,
                    threshold_value=self.config.min_quality_score_warning,
                    recommendation="Consider improvements to raise quality score",
                ))

        # Check trend-based thresholds
        if self.last_trend and self.last_trend.direction == TrendDirection.INCREASING:
            change_pct = abs(self.last_trend.recent_change_pct)
            if change_pct >= self.config.trend_increase_pct_critical:
                alerts.append(ThresholdAlert(
                    severity=AlertSeverity.CRITICAL,
                    alert_type="trend_increase",
                    message=f"CRITICAL: Errors increased by {change_pct:.1f}%",
                    current_value=change_pct,
                    threshold_value=self.config.trend_increase_pct_critical,
                    recommendation="Error rate is rapidly increasing - investigate root cause immediately",
                ))
            elif change_pct >= self.config.trend_increase_pct_warning:
                alerts.append(ThresholdAlert(
                    severity=AlertSeverity.WARNING,
                    alert_type="trend_increase",
                    message=f"WARNING: Errors increased by {change_pct:.1f}%",
                    current_value=change_pct,
                    threshold_value=self.config.trend_increase_pct_warning,
                    recommendation="Error rate is trending upward - monitor closely",
                ))

        # Store alerts in history
        self.alerts_history.extend(alerts)
        # Keep only recent alerts (last 50)
        if len(self.alerts_history) > 50:
            self.alerts_history = self.alerts_history[-50:]

        return alerts

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the current monitoring state.

        Returns:
            Dictionary with current status, statistics, and trend info
        """
        recent = self.get_recent_snapshots()

        if not recent:
            return {
                "status": "no_data",
                "message": "No error snapshots recorded",
                "snapshot_count": 0,
            }

        latest = recent[-1]
        trend = self.compute_trend()
        alerts = self.check_thresholds(latest)

        # Determine overall status
        critical_alerts = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        warning_alerts = [a for a in alerts if a.severity == AlertSeverity.WARNING]

        if critical_alerts:
            status = "critical"
        elif warning_alerts:
            status = "warning"
        else:
            status = "healthy"

        return {
            "status": status,
            "latest_snapshot": {
                "timestamp": latest.timestamp.isoformat(),
                "source_file": latest.source_file,
                "errors": latest.error_count,
                "warnings": latest.warning_count,
                "info": latest.info_count,
                "quality_score": latest.quality_score,
            },
            "trend": {
                "direction": trend.direction.value,
                "confidence": trend.confidence,
                "description": trend.description,
                "recent_change_pct": trend.recent_change_pct,
            },
            "statistics": trend.statistics.model_dump() if trend.statistics else None,
            "alerts": [
                {
                    "severity": a.severity.value,
                    "type": a.alert_type,
                    "message": a.message,
                }
                for a in alerts
            ],
            "snapshot_count": len(self.snapshots),
            "recent_snapshot_count": len(recent),
        }

    def save(self, path: Path | str) -> None:
        """Save monitor state to a JSON file.

        Args:
            path: File path to save to
        """
        path = Path(path)
        path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: Path | str) -> "ErrorMonitorState":
        """Load monitor state from a JSON file.

        Args:
            path: File path to load from

        Returns:
            Loaded monitor state (or new empty state if file doesn't exist)
        """
        path = Path(path)
        if not path.exists():
            return cls()
        return cls.model_validate_json(path.read_text())


def create_snapshot_from_quality_report(
    report_dict: dict[str, Any],
    source_file: str = "",
) -> ErrorSnapshot:
    """Create an ErrorSnapshot from a QualityReport.to_dict() output.

    Convenience function to integrate with the existing quality check system.

    Args:
        report_dict: Output from QualityReport.to_dict()
        source_file: Override source file name (uses report's file_path if empty)

    Returns:
        ErrorSnapshot populated from the quality report
    """
    summary = report_dict.get("summary", {})

    # Extract category counts from issues
    categories: dict[str, int] = {}
    for issue in report_dict.get("issues", []):
        category = issue.get("category", "unknown")
        categories[category] = categories.get(category, 0) + 1

    return ErrorSnapshot(
        source_file=source_file or report_dict.get("file_path", "unknown"),
        error_count=summary.get("errors", 0),
        warning_count=summary.get("warnings", 0),
        info_count=summary.get("info", 0),
        quality_score=report_dict.get("score", 0.0),
        slide_count=report_dict.get("slide_count", 0),
        categories=categories,
        metadata={
            "passed": report_dict.get("passed", False),
            "layout_coverage": report_dict.get("layout_coverage", {}).get("coverage_pct", 0),
        },
    )
