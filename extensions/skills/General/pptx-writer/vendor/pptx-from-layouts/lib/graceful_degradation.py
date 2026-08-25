"""
Graceful degradation framework for the PPTX generation pipeline.

Provides a unified error handling system with severity levels (FATAL/ERROR/WARN)
and partial output support. This allows the pipeline to continue processing
even when encountering non-critical errors, producing partial output with
detailed issue reports.

Usage:
    from graceful_degradation import (
        Severity,
        DegradationIssue,
        DegradationContext,
        handle_gracefully,
    )

    # Create a context for tracking issues
    ctx = DegradationContext("generate_pptx")

    # Add issues as they occur
    ctx.add_issue(
        severity=Severity.WARN,
        category="image",
        message="Image file not found",
        location="slide[3].columns[0].file_path",
        suggestion="Check the file path or provide a valid image",
    )

    # Check if we can continue
    if ctx.can_continue():
        # Continue processing with partial output
        pass
    else:
        # Fatal error - must abort
        pass

    # Get structured result
    result = ctx.get_result()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class Severity(str, Enum):
    """Issue severity levels for graceful degradation.

    FATAL: Critical error that prevents any output. Pipeline must abort.
           Examples: Invalid layout plan schema, template file not found,
           missing required config file.

    ERROR: Significant error that affects specific content but allows
           partial output. The affected component will be degraded.
           Examples: Slide generation failed (creates fallback slide),
           image insertion failed (creates placeholder box),
           table parsing failed (renders as bullets instead).

    WARN:  Minor issue that doesn't affect output correctness but may
           result in suboptimal presentation.
           Examples: Text overflow detected (font was shrunk),
           aspect ratio mismatch (image was cropped),
           unknown typography marker (marker was stripped).
    """

    FATAL = "fatal"  # Must abort - no output possible
    ERROR = "error"  # Degrades gracefully - partial output
    WARN = "warn"  # Continues normally - cosmetic/quality issue


# Severity ordering for comparisons (higher number = more severe)
SEVERITY_ORDER = {
    Severity.WARN: 1,
    Severity.ERROR: 2,
    Severity.FATAL: 3,
}


@dataclass
class DegradationIssue:
    """A single issue encountered during processing.

    Captures full context about what went wrong, where it occurred,
    and optionally how to fix it.
    """

    severity: Severity
    category: str  # e.g., "image", "layout", "typography", "schema", "table"
    message: str
    location: str | None = None  # e.g., "slide[3].columns[0].file_path"
    slide_number: int | None = None  # For slide-specific issues
    suggestion: str | None = None  # Human-readable fix suggestion
    fallback_action: str | None = None  # What degraded action was taken
    exception: Exception | None = None  # Original exception if any
    context: dict[str, Any] | None = None  # Additional structured context

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "severity": self.severity.value,
            "category": self.category,
            "message": self.message,
        }
        if self.location:
            result["location"] = self.location
        if self.slide_number is not None:
            result["slide_number"] = self.slide_number
        if self.suggestion:
            result["suggestion"] = self.suggestion
        if self.fallback_action:
            result["fallback_action"] = self.fallback_action
        if self.context:
            result["context"] = self.context
        return result

    def format_human(self) -> str:
        """Format issue for human-readable output."""
        prefix = {
            Severity.FATAL: "FATAL",
            Severity.ERROR: "ERROR",
            Severity.WARN: "WARN",
        }[self.severity]

        parts = [f"[{prefix}] {self.category}: {self.message}"]

        if self.location:
            parts.append(f"  Location: {self.location}")
        if self.slide_number is not None:
            parts.append(f"  Slide: {self.slide_number}")
        if self.fallback_action:
            parts.append(f"  Fallback: {self.fallback_action}")
        if self.suggestion:
            parts.append(f"  Suggestion: {self.suggestion}")

        return "\n".join(parts)


@dataclass
class DegradationResult:
    """Result of a processing operation with graceful degradation.

    Tracks all issues encountered and provides summary statistics
    for determining overall success/failure.
    """

    component: str  # Which component produced this result
    issues: list[DegradationIssue] = field(default_factory=list)
    partial_output: bool = False  # True if output is incomplete/degraded
    aborted: bool = False  # True if processing was aborted due to FATAL

    @property
    def fatal_count(self) -> int:
        """Number of fatal issues."""
        return sum(1 for i in self.issues if i.severity == Severity.FATAL)

    @property
    def error_count(self) -> int:
        """Number of error issues (not fatal)."""
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warn_count(self) -> int:
        """Number of warning issues."""
        return sum(1 for i in self.issues if i.severity == Severity.WARN)

    @property
    def highest_severity(self) -> Severity | None:
        """Get the highest severity level encountered."""
        if not self.issues:
            return None
        return max(self.issues, key=lambda i: SEVERITY_ORDER[i.severity]).severity

    @property
    def success(self) -> bool:
        """True if no fatal errors and processing completed."""
        return self.fatal_count == 0 and not self.aborted

    def has_issues(self) -> bool:
        """Check if any issues were recorded."""
        return len(self.issues) > 0

    def issues_by_severity(self, severity: Severity) -> list[DegradationIssue]:
        """Get all issues of a specific severity."""
        return [i for i in self.issues if i.severity == severity]

    def issues_by_category(self, category: str) -> list[DegradationIssue]:
        """Get all issues in a specific category."""
        return [i for i in self.issues if i.category == category]

    def issues_by_slide(self, slide_number: int) -> list[DegradationIssue]:
        """Get all issues for a specific slide."""
        return [i for i in self.issues if i.slide_number == slide_number]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "component": self.component,
            "success": self.success,
            "partial_output": self.partial_output,
            "aborted": self.aborted,
            "counts": {
                "fatal": self.fatal_count,
                "error": self.error_count,
                "warn": self.warn_count,
                "total": len(self.issues),
            },
            "issues": [i.to_dict() for i in self.issues],
        }

    def format_summary(self) -> str:
        """Format a human-readable summary."""
        if not self.issues:
            return f"{self.component}: No issues"

        status = "ABORTED" if self.aborted else ("PARTIAL" if self.partial_output else "OK")
        counts = f"FATAL:{self.fatal_count} ERROR:{self.error_count} WARN:{self.warn_count}"
        return f"{self.component}: {status} ({counts})"

    def format_full_report(self) -> str:
        """Format a full human-readable report of all issues."""
        lines = [self.format_summary(), "=" * 60]

        if not self.issues:
            return "\n".join(lines)

        # Group by severity
        for severity in [Severity.FATAL, Severity.ERROR, Severity.WARN]:
            severity_issues = self.issues_by_severity(severity)
            if severity_issues:
                lines.append(f"\n{severity.value.upper()} ({len(severity_issues)}):")
                lines.append("-" * 40)
                for issue in severity_issues:
                    lines.append(issue.format_human())
                    lines.append("")

        return "\n".join(lines)


class DegradationContext:
    """Context manager for tracking issues during processing.

    Use this to accumulate issues throughout a processing operation,
    then check if processing can continue or must abort.

    Example:
        ctx = DegradationContext("generate_pptx")

        # Process slides
        for slide in slides:
            try:
                generate_slide(slide)
            except SlideError as e:
                ctx.add_issue(
                    severity=Severity.ERROR,
                    category="slide",
                    message=str(e),
                    slide_number=slide.slide_number,
                    fallback_action="Created placeholder slide",
                )

        # Get final result
        result = ctx.get_result()
    """

    def __init__(
        self,
        component: str,
        abort_on_fatal: bool = True,
        max_errors: int | None = None,
    ):
        """Initialize degradation context.

        Args:
            component: Name of the component being monitored
            abort_on_fatal: If True, can_continue() returns False after FATAL
            max_errors: Optional maximum number of ERROR-level issues before
                        treating further errors as FATAL
        """
        self.component = component
        self.abort_on_fatal = abort_on_fatal
        self.max_errors = max_errors
        self._issues: list[DegradationIssue] = []
        self._aborted = False
        self._partial = False

    def add_issue(
        self,
        severity: Severity,
        category: str,
        message: str,
        location: str | None = None,
        slide_number: int | None = None,
        suggestion: str | None = None,
        fallback_action: str | None = None,
        exception: Exception | None = None,
        context: dict[str, Any] | None = None,
    ) -> DegradationIssue:
        """Add an issue to the context.

        Returns the created issue for chaining or further inspection.
        """
        # Check if we should escalate ERROR to FATAL due to max_errors
        effective_severity = severity
        if (
            self.max_errors is not None
            and severity == Severity.ERROR
            and sum(1 for i in self._issues if i.severity == Severity.ERROR) >= self.max_errors
        ):
            effective_severity = Severity.FATAL

        issue = DegradationIssue(
            severity=effective_severity,
            category=category,
            message=message,
            location=location,
            slide_number=slide_number,
            suggestion=suggestion,
            fallback_action=fallback_action,
            exception=exception,
            context=context,
        )
        self._issues.append(issue)

        # Mark as partial if we have any errors
        if effective_severity in (Severity.ERROR, Severity.FATAL):
            self._partial = True

        # Check for abort condition
        if self.abort_on_fatal and effective_severity == Severity.FATAL:
            self._aborted = True

        return issue

    def add_warning(
        self,
        category: str,
        message: str,
        **kwargs: Any,
    ) -> DegradationIssue:
        """Convenience method to add a WARN-level issue."""
        return self.add_issue(Severity.WARN, category, message, **kwargs)

    def add_error(
        self,
        category: str,
        message: str,
        **kwargs: Any,
    ) -> DegradationIssue:
        """Convenience method to add an ERROR-level issue."""
        return self.add_issue(Severity.ERROR, category, message, **kwargs)

    def add_fatal(
        self,
        category: str,
        message: str,
        **kwargs: Any,
    ) -> DegradationIssue:
        """Convenience method to add a FATAL-level issue."""
        return self.add_issue(Severity.FATAL, category, message, **kwargs)

    def can_continue(self) -> bool:
        """Check if processing can continue.

        Returns False if:
        - A FATAL error occurred and abort_on_fatal is True
        - Processing was explicitly aborted
        """
        return not self._aborted

    def abort(self, reason: str | None = None):
        """Explicitly abort processing.

        Optionally add a FATAL issue with the given reason.
        """
        if reason:
            self.add_fatal("abort", reason)
        self._aborted = True

    def mark_partial(self):
        """Mark the output as partial/degraded."""
        self._partial = True

    def get_result(self) -> DegradationResult:
        """Get the final degradation result."""
        return DegradationResult(
            component=self.component,
            issues=list(self._issues),
            partial_output=self._partial,
            aborted=self._aborted,
        )

    @property
    def issues(self) -> list[DegradationIssue]:
        """Read-only access to issues list."""
        return list(self._issues)

    @property
    def fatal_count(self) -> int:
        """Number of fatal issues."""
        return sum(1 for i in self._issues if i.severity == Severity.FATAL)

    @property
    def error_count(self) -> int:
        """Number of error issues."""
        return sum(1 for i in self._issues if i.severity == Severity.ERROR)

    @property
    def warn_count(self) -> int:
        """Number of warning issues."""
        return sum(1 for i in self._issues if i.severity == Severity.WARN)


def handle_gracefully(
    ctx: DegradationContext,
    severity: Severity,
    category: str,
    fallback_value: T,
    fallback_action: str | None = None,
    location: str | None = None,
    slide_number: int | None = None,
    suggestion: str | None = None,
) -> Callable[[Callable[[], T]], T]:
    """Decorator/context for graceful error handling.

    Use as a context manager or decorator to wrap code that might fail,
    providing automatic fallback on exception.

    Args:
        ctx: DegradationContext to record issues in
        severity: Severity level if the wrapped code fails
        category: Issue category for classification
        fallback_value: Value to return if the wrapped code fails
        fallback_action: Description of what fallback was taken
        location: Optional location string for the issue
        slide_number: Optional slide number for the issue
        suggestion: Optional suggestion for fixing the issue

    Example as decorator:
        @handle_gracefully(ctx, Severity.ERROR, "image", None,
                          fallback_action="Used placeholder box")
        def insert_image():
            # Code that might fail
            return image_shape

    Example as context manager:
        with handle_gracefully(ctx, Severity.WARN, "font", "Aptos"):
            font_name = extract_font()
    """

    def decorator(func: Callable[[], T]) -> T:
        try:
            return func()
        except Exception as e:
            ctx.add_issue(
                severity=severity,
                category=category,
                message=str(e),
                location=location,
                slide_number=slide_number,
                suggestion=suggestion,
                fallback_action=fallback_action,
                exception=e,
            )
            return fallback_value

    return decorator


class GracefulHandler:
    """Handler for graceful error recovery with automatic fallback.

    Provides a cleaner API for try/except patterns with automatic
    issue recording and fallback.

    Example:
        handler = GracefulHandler(ctx)

        # Execute with fallback
        result = handler.try_or_fallback(
            lambda: risky_operation(),
            fallback="default_value",
            severity=Severity.ERROR,
            category="operation",
            message="Operation failed",
        )
    """

    def __init__(self, ctx: DegradationContext):
        """Initialize with a degradation context."""
        self.ctx = ctx

    def try_or_fallback(
        self,
        func: Callable[[], T],
        fallback: T,
        severity: Severity,
        category: str,
        message: str | None = None,
        location: str | None = None,
        slide_number: int | None = None,
        suggestion: str | None = None,
        fallback_action: str | None = None,
    ) -> T:
        """Execute a function with automatic fallback on exception.

        Args:
            func: Function to execute
            fallback: Value to return on failure
            severity: Severity level for the issue
            category: Issue category
            message: Custom message (uses exception message if None)
            location: Optional location string
            slide_number: Optional slide number
            suggestion: Optional fix suggestion
            fallback_action: Description of fallback taken

        Returns:
            Function result on success, fallback value on failure
        """
        try:
            return func()
        except Exception as e:
            self.ctx.add_issue(
                severity=severity,
                category=category,
                message=message or str(e),
                location=location,
                slide_number=slide_number,
                suggestion=suggestion,
                fallback_action=fallback_action,
                exception=e,
            )
            return fallback

    def try_or_skip(
        self,
        func: Callable[[], T],
        severity: Severity,
        category: str,
        message: str | None = None,
        location: str | None = None,
        slide_number: int | None = None,
        suggestion: str | None = None,
    ) -> T | None:
        """Execute a function, returning None on failure.

        Same as try_or_fallback with fallback=None.
        """
        return self.try_or_fallback(
            func=func,
            fallback=None,
            severity=severity,
            category=category,
            message=message,
            location=location,
            slide_number=slide_number,
            suggestion=suggestion,
            fallback_action="Skipped",
        )


def merge_results(*results: DegradationResult) -> DegradationResult:
    """Merge multiple degradation results into one.

    Useful for combining results from multiple processing stages.
    """
    if not results:
        return DegradationResult(component="merged")

    merged = DegradationResult(
        component="+".join(r.component for r in results),
        issues=[],
        partial_output=any(r.partial_output for r in results),
        aborted=any(r.aborted for r in results),
    )

    for result in results:
        merged.issues.extend(result.issues)

    return merged
