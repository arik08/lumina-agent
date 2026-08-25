#!/usr/bin/env python3
"""
Content recovery module for malformed outline parsing.

Provides detailed error tracking with line numbers, context snippets,
and actionable fix suggestions. Integrates with the graceful degradation
framework for unified error handling across the pipeline.

Usage:
    from content_recovery import ContentRecovery, ContentIssue

    recovery = ContentRecovery()

    # Track issues as they occur during parsing
    recovery.add_issue(
        line_num=42,
        column=15,
        category='table',
        message="Missing table separator row",
        context_lines=["| Col A | Col B |", "| data  | data  |"],
        suggested_fix="Add separator row: |-------|-------|"
    )

    # Attempt recovery with fallback
    result = recovery.attempt_recovery(
        issue_id=recovery.issues[-1].id,
        recovery_fn=lambda: parse_as_bullets(content),
        fallback_action="Parsed as bullet list instead of table"
    )

    # Generate report
    print(recovery.format_report())
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar
from uuid import uuid4

T = TypeVar("T")


class IssueSeverity(str, Enum):
    """Severity levels for content issues."""
    FATAL = "fatal"     # Cannot continue parsing
    ERROR = "error"     # Component skipped, partial output
    WARNING = "warning" # Suboptimal but continues normally
    INFO = "info"       # Informational note


class IssueCategory(str, Enum):
    """Categories of content issues for grouping and filtering."""
    STRUCTURE = "structure"       # Slide structure (headers, dividers)
    VISUAL_TYPE = "visual_type"   # Visual type declarations
    TYPOGRAPHY = "typography"     # Typography markers
    TABLE = "table"               # Table formatting
    COLUMN = "column"             # Column definitions
    TIMELINE = "timeline"         # Timeline entries
    IMAGE = "image"               # Image placeholders
    DELIVERABLE = "deliverable"   # Deliverable items
    CONTENT = "content"           # Generic content issues


@dataclass
class ContentIssue:
    """Represents a content parsing issue with full context for recovery.

    Captures where the issue occurred, what went wrong, surrounding context,
    and a suggested fix that can be applied.
    """
    id: str
    line_num: int
    column: int | None
    category: IssueCategory | str
    message: str
    severity: IssueSeverity

    # Context for understanding the issue
    line_content: str = ""
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)

    # For slide-specific issues
    slide_num: int | None = None

    # Recovery guidance
    suggested_fix: str = ""
    fix_example: str = ""

    # Recovery tracking
    recovered: bool = False
    recovery_action: str = ""

    # Additional metadata
    raw_content: str = ""  # Original malformed content
    exception: Exception | None = None

    def __post_init__(self):
        # Normalize category to string
        if isinstance(self.category, IssueCategory):
            self.category = self.category.value

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "line_num": self.line_num,
            "category": self.category,
            "message": self.message,
            "severity": self.severity.value if isinstance(self.severity, IssueSeverity) else self.severity,
        }
        if self.column is not None:
            result["column"] = self.column
        if self.line_content:
            result["line_content"] = self.line_content
        if self.context_before:
            result["context_before"] = self.context_before
        if self.context_after:
            result["context_after"] = self.context_after
        if self.slide_num is not None:
            result["slide_num"] = self.slide_num
        if self.suggested_fix:
            result["suggested_fix"] = self.suggested_fix
        if self.fix_example:
            result["fix_example"] = self.fix_example
        if self.recovered:
            result["recovered"] = self.recovered
            result["recovery_action"] = self.recovery_action
        return result

    def format_location(self) -> str:
        """Format the location string."""
        loc = f"Line {self.line_num}"
        if self.column is not None:
            loc += f", Col {self.column}"
        if self.slide_num is not None:
            loc += f" (Slide {self.slide_num})"
        return loc

    def format_human(self, include_context: bool = True) -> str:
        """Format issue for human-readable output."""
        severity_prefix = {
            IssueSeverity.FATAL: "FATAL",
            IssueSeverity.ERROR: "ERROR",
            IssueSeverity.WARNING: "WARN",
            IssueSeverity.INFO: "INFO",
            "fatal": "FATAL",
            "error": "ERROR",
            "warning": "WARN",
            "info": "INFO",
        }.get(self.severity, "ISSUE")

        lines = [f"[{severity_prefix}] {self.format_location()}: {self.message}"]

        if include_context:
            # Show context lines before
            for i, ctx_line in enumerate(self.context_before[-3:], start=-(len(self.context_before[-3:]))):
                lines.append(f"  {self.line_num + i:>4} | {ctx_line}")

            # Show the problematic line with pointer
            if self.line_content:
                lines.append(f"  {self.line_num:>4} | {self.line_content}")
                if self.column is not None:
                    pointer = " " * (7 + self.column) + "^"
                    lines.append(pointer)

            # Show context lines after
            for i, ctx_line in enumerate(self.context_after[:2], start=1):
                lines.append(f"  {self.line_num + i:>4} | {ctx_line}")

        # Show suggested fix
        if self.suggested_fix:
            lines.append(f"  Suggested fix: {self.suggested_fix}")

        if self.fix_example:
            lines.append("  Example:")
            for ex_line in self.fix_example.split('\n'):
                lines.append(f"    {ex_line}")

        if self.recovered:
            lines.append(f"  Recovery: {self.recovery_action}")

        return "\n".join(lines)


@dataclass
class RecoveryAttempt:
    """Tracks a recovery attempt for a content issue."""
    issue_id: str
    success: bool
    action: str
    result: Any = None
    exception: Exception | None = None


class ContentRecovery:
    """Tracks content issues and recovery attempts during parsing.

    Provides a centralized way to record parsing issues with full context
    and attempt recovery with fallback strategies.
    """

    def __init__(self, source_name: str = "outline"):
        """Initialize content recovery tracker.

        Args:
            source_name: Name of the source being parsed (for reports)
        """
        self.source_name = source_name
        self.issues: list[ContentIssue] = []
        self.recovery_attempts: list[RecoveryAttempt] = []
        self._lines: list[str] = []  # Source lines for context extraction

    def set_source_lines(self, content: str):
        """Set the source content for context extraction.

        Args:
            content: Full source content (will be split into lines)
        """
        self._lines = content.split('\n')

    def _get_context(self, line_num: int, before: int = 2, after: int = 2) -> tuple[str, list[str], list[str]]:
        """Get the line content and surrounding context.

        Args:
            line_num: 1-indexed line number
            before: Number of lines before to include
            after: Number of lines after to include

        Returns:
            Tuple of (line_content, context_before, context_after)
        """
        if not self._lines or line_num < 1:
            return "", [], []

        idx = line_num - 1  # Convert to 0-indexed
        if idx >= len(self._lines):
            return "", [], []

        line_content = self._lines[idx]
        context_before = self._lines[max(0, idx - before):idx]
        context_after = self._lines[idx + 1:idx + 1 + after]

        return line_content, context_before, context_after

    def add_issue(
        self,
        line_num: int,
        category: IssueCategory | str,
        message: str,
        severity: IssueSeverity = IssueSeverity.ERROR,
        column: int | None = None,
        slide_num: int | None = None,
        suggested_fix: str = "",
        fix_example: str = "",
        raw_content: str = "",
        exception: Exception | None = None,
        context_lines: int = 2,
    ) -> ContentIssue:
        """Add a content issue with automatic context extraction.

        Args:
            line_num: 1-indexed line number where issue occurred
            category: Issue category for grouping
            message: Human-readable description of the issue
            severity: Issue severity level
            column: Optional column number (1-indexed)
            slide_num: Optional slide number
            suggested_fix: Text describing how to fix the issue
            fix_example: Example of correct syntax
            raw_content: Raw malformed content
            exception: Original exception if any
            context_lines: Number of context lines to extract

        Returns:
            The created ContentIssue
        """
        line_content, context_before, context_after = self._get_context(
            line_num, before=context_lines, after=context_lines
        )

        issue = ContentIssue(
            id=str(uuid4())[:8],
            line_num=line_num,
            column=column,
            category=category if isinstance(category, str) else category.value,
            message=message,
            severity=severity,
            line_content=line_content,
            context_before=context_before,
            context_after=context_after,
            slide_num=slide_num,
            suggested_fix=suggested_fix,
            fix_example=fix_example,
            raw_content=raw_content,
            exception=exception,
        )

        self.issues.append(issue)
        return issue

    def attempt_recovery(
        self,
        issue: ContentIssue,
        recovery_fn: Callable[[], T],
        fallback_action: str,
    ) -> tuple[bool, T | None]:
        """Attempt to recover from an issue using a recovery function.

        Args:
            issue: The issue to recover from
            recovery_fn: Function that attempts recovery (returns result on success)
            fallback_action: Description of the recovery action

        Returns:
            Tuple of (success, result) - result is None on failure
        """
        try:
            result = recovery_fn()
            issue.recovered = True
            issue.recovery_action = fallback_action
            self.recovery_attempts.append(RecoveryAttempt(
                issue_id=issue.id,
                success=True,
                action=fallback_action,
                result=result,
            ))
            return True, result
        except Exception as e:
            self.recovery_attempts.append(RecoveryAttempt(
                issue_id=issue.id,
                success=False,
                action=fallback_action,
                exception=e,
            ))
            return False, None

    def get_issues_by_severity(self, severity: IssueSeverity) -> list[ContentIssue]:
        """Get all issues of a specific severity."""
        return [i for i in self.issues if i.severity == severity]

    def get_issues_by_category(self, category: IssueCategory | str) -> list[ContentIssue]:
        """Get all issues in a specific category."""
        cat = category if isinstance(category, str) else category.value
        return [i for i in self.issues if i.category == cat]

    def get_issues_for_slide(self, slide_num: int) -> list[ContentIssue]:
        """Get all issues for a specific slide."""
        return [i for i in self.issues if i.slide_num == slide_num]

    def get_unrecovered_issues(self) -> list[ContentIssue]:
        """Get issues that were not successfully recovered."""
        return [i for i in self.issues if not i.recovered]

    @property
    def fatal_count(self) -> int:
        """Number of fatal issues."""
        return len(self.get_issues_by_severity(IssueSeverity.FATAL))

    @property
    def error_count(self) -> int:
        """Number of error issues."""
        return len(self.get_issues_by_severity(IssueSeverity.ERROR))

    @property
    def warning_count(self) -> int:
        """Number of warning issues."""
        return len(self.get_issues_by_severity(IssueSeverity.WARNING))

    @property
    def recovered_count(self) -> int:
        """Number of successfully recovered issues."""
        return sum(1 for i in self.issues if i.recovered)

    @property
    def has_fatal(self) -> bool:
        """Check if any fatal issues exist."""
        return self.fatal_count > 0

    @property
    def can_continue(self) -> bool:
        """Check if parsing can continue (no fatal issues)."""
        return not self.has_fatal

    def format_report(self, verbose: bool = True) -> str:
        """Generate a formatted report of all issues.

        Args:
            verbose: Include full context in output

        Returns:
            Formatted string report
        """
        if not self.issues:
            return f"Content Recovery Report: {self.source_name}\nNo issues found."

        lines = [
            f"Content Recovery Report: {self.source_name}",
            "=" * 60,
            f"Total Issues: {len(self.issues)} "
            f"(Fatal: {self.fatal_count}, Error: {self.error_count}, Warning: {self.warning_count})",
            f"Recovered: {self.recovered_count}/{len(self.issues)}",
            "",
        ]

        # Group by severity
        for severity in [IssueSeverity.FATAL, IssueSeverity.ERROR, IssueSeverity.WARNING, IssueSeverity.INFO]:
            severity_issues = self.get_issues_by_severity(severity)
            if severity_issues:
                lines.append(f"\n{severity.value.upper()} ({len(severity_issues)}):")
                lines.append("-" * 40)
                for issue in severity_issues:
                    lines.append(issue.format_human(include_context=verbose))
                    lines.append("")

        return "\n".join(lines)

    def format_summary(self) -> str:
        """Generate a brief summary of issues."""
        if not self.issues:
            return "No issues"

        parts = []
        if self.fatal_count:
            parts.append(f"FATAL:{self.fatal_count}")
        if self.error_count:
            parts.append(f"ERROR:{self.error_count}")
        if self.warning_count:
            parts.append(f"WARN:{self.warning_count}")

        status = " ".join(parts)
        if self.recovered_count:
            status += f" (recovered:{self.recovered_count})"

        return status

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_name": self.source_name,
            "summary": {
                "total": len(self.issues),
                "fatal": self.fatal_count,
                "error": self.error_count,
                "warning": self.warning_count,
                "recovered": self.recovered_count,
            },
            "issues": [i.to_dict() for i in self.issues],
        }


# =============================================================================
# FIX SUGGESTION GENERATORS
# =============================================================================

def suggest_table_fix(content: str, error_type: str) -> tuple[str, str]:
    """Generate fix suggestion for table-related errors.

    Args:
        content: The malformed table content
        error_type: Type of table error

    Returns:
        Tuple of (suggestion_text, example_text)
    """
    if "separator" in error_type.lower() or "header" in error_type.lower():
        return (
            "Add a separator row after the header using dashes and pipes",
            "| Header 1 | Header 2 |\n|----------|----------|\n| Value 1  | Value 2  |"
        )
    if "column" in error_type.lower() or "mismatch" in error_type.lower():
        return (
            "Ensure all rows have the same number of columns as the header",
            "| Col A | Col B | Col C |\n|-------|-------|-------|\n| a     | b     | c     |"
        )
    if "escaped" in error_type.lower() or "pipe" in error_type.lower():
        return (
            "Use \\| to include a literal pipe character in cell content",
            "| Name | Formula |\n|------|---------------|\n| OR   | A \\| B        |"
        )
    return (
        "Check table format: header row, separator row (|---|---|), then data rows",
        "| Column A | Column B |\n|----------|----------|\n| data     | data     |"
    )


def suggest_visual_type_fix(content: str, error_type: str) -> tuple[str, str]:
    """Generate fix suggestion for visual type errors.

    Args:
        content: The content around the visual type
        error_type: Type of visual error

    Returns:
        Tuple of (suggestion_text, example_text)
    """
    if "unknown" in error_type.lower() or "invalid" in error_type.lower():
        return (
            "Use a valid visual type: bullets, process-N-phase, comparison-N, cards-N, table, timeline, quote-hero, hero-statement",
            "**Visual: process-3-phase**\nor\n**Visual: comparison-2**"
        )
    if "missing" in error_type.lower():
        return (
            "Add a visual type declaration after the slide title",
            "# Slide 1: Our Process\n**Visual: process-3-phase**"
        )
    if "column" in error_type.lower() or "mismatch" in error_type.lower():
        return (
            "Column count must match the visual type number",
            "**Visual: process-3-phase**\n[Column 1: First]\n- Point\n[Column 2: Second]\n- Point\n[Column 3: Third]\n- Point"
        )
    return (
        "Specify visual type after slide title using **Visual: type** format",
        "**Visual: bullets**"
    )


def suggest_typography_fix(content: str, error_type: str, marker: str = "") -> tuple[str, str]:
    """Generate fix suggestion for typography marker errors.

    Args:
        content: The content with marker issues
        error_type: Type of typography error
        marker: The specific marker involved

    Returns:
        Tuple of (suggestion_text, example_text)
    """
    if "unclosed" in error_type.lower():
        return (
            f"Close the {{{marker}}} marker with {{/{marker}}}",
            "{bold}Important text{/bold}"
        )
    if "unmatched" in error_type.lower():
        return (
            f"Remove the orphaned {{/{marker}}} or add matching opening marker",
            "{blue}Blue text{/blue}"
        )
    if "color" in error_type.lower():
        return (
            "Color values must be 6-digit hex codes",
            "{color:#FF6600}Orange text{/color}"
        )
    if "size" in error_type.lower():
        return (
            "Size values must be positive numbers (in points)",
            "{size:18}Larger text{/size}"
        )
    if "nested" in error_type.lower() or "order" in error_type.lower():
        return (
            "Close markers in reverse order of opening (LIFO)",
            "{bold}{blue}Bold blue text{/blue}{/bold}"
        )
    return (
        "Check marker syntax: {marker}text{/marker}",
        "{bold}Bold{/bold}, {blue}Blue{/blue}, {size:18}Big{/size}"
    )


def suggest_column_fix(content: str, error_type: str) -> tuple[str, str]:
    """Generate fix suggestion for column definition errors.

    Args:
        content: The content with column issues
        error_type: Type of column error

    Returns:
        Tuple of (suggestion_text, example_text)
    """
    if "missing" in error_type.lower() or "empty" in error_type.lower():
        return (
            "Define columns using [Column N: Header] followed by bullet points",
            "[Column 1: First Phase]\n- Step one\n- Step two\n\n[Column 2: Second Phase]\n- Step three"
        )
    if "mismatch" in error_type.lower() or "count" in error_type.lower():
        return (
            "Number of [Column] sections must match the visual type",
            "For process-3-phase, define exactly 3 columns:\n[Column 1: Start]\n[Column 2: Middle]\n[Column 3: End]"
        )
    if "header" in error_type.lower():
        return (
            "Column headers should be concise (2-4 words)",
            "[Column 1: Discovery Phase]"
        )
    return (
        "Define columns with [Column N: Header] format",
        "[Column 1: Header]\n- Content"
    )


def suggest_timeline_fix(content: str, error_type: str) -> tuple[str, str]:
    """Generate fix suggestion for timeline errors.

    Args:
        content: The content with timeline issues
        error_type: Type of timeline error

    Returns:
        Tuple of (suggestion_text, example_text)
    """
    if "date" in error_type.lower() or "format" in error_type.lower():
        return (
            "Timeline entries need bold date/period followed by description",
            "- **Q1 2026:** Launch beta version\n- **Q2 2026:** Full release"
        )
    if "missing" in error_type.lower() or "empty" in error_type.lower():
        return (
            "Add timeline entries with dates and descriptions",
            "- **Week 1:** Discovery and research\n- **Week 2-3:** Development\n- **Week 4:** Testing and deployment"
        )
    return (
        "Use bold for dates: **Date:** Description",
        "- **Phase 1 (Jan-Mar):** Initial development"
    )


def suggest_structure_fix(content: str, error_type: str) -> tuple[str, str]:
    """Generate fix suggestion for slide structure errors.

    Args:
        content: The content with structure issues
        error_type: Type of structure error

    Returns:
        Tuple of (suggestion_text, example_text)
    """
    if "no slides" in error_type.lower():
        return (
            "Start each slide with a header or use --- dividers",
            "# Slide 1: Introduction\n\n**Visual: bullets**\n- First point\n\n---\n\n# Slide 2: Details"
        )
    if "empty" in error_type.lower():
        return (
            "Add content to the slide (bullets, columns, table, etc.)",
            "# Slide 1: Title\n\n**Visual: bullets**\n- Content point 1\n- Content point 2"
        )
    if "title" in error_type.lower():
        return (
            "Add a title using # or ## heading",
            "# Slide 1: Main Title\n### Optional Subtitle"
        )
    return (
        "Use # Slide N: Title format for slide headers",
        "# Slide 1: Introduction"
    )


def get_fix_suggestion(
    category: IssueCategory | str,
    error_type: str,
    content: str = "",
    marker: str = ""
) -> tuple[str, str]:
    """Get appropriate fix suggestion based on issue category.

    Args:
        category: Issue category
        error_type: Specific error type
        content: Relevant content
        marker: Marker name for typography errors

    Returns:
        Tuple of (suggestion_text, fix_example)
    """
    cat = category if isinstance(category, str) else category.value

    if cat == "table":
        return suggest_table_fix(content, error_type)
    elif cat == "visual_type":
        return suggest_visual_type_fix(content, error_type)
    elif cat == "typography":
        return suggest_typography_fix(content, error_type, marker)
    elif cat == "column":
        return suggest_column_fix(content, error_type)
    elif cat == "timeline":
        return suggest_timeline_fix(content, error_type)
    elif cat == "structure":
        return suggest_structure_fix(content, error_type)
    else:
        return (
            "Review the content format and structure",
            ""
        )


# =============================================================================
# LINE NUMBER EXTRACTION HELPERS
# =============================================================================

def find_line_number(content: str, pattern: str | re.Pattern, start_line: int = 1) -> int | None:
    """Find the line number where a pattern first matches.

    Args:
        content: Multi-line content to search
        pattern: String (treated as regex) or compiled regex pattern to find.
                 For literal string matching, use find_line_number_for_text instead.
        start_line: Line number offset (1-indexed)

    Returns:
        Line number (1-indexed) or None if not found
    """
    if isinstance(pattern, str):
        pattern = re.compile(pattern)

    lines = content.split('\n')
    for i, line in enumerate(lines):
        if pattern.search(line):
            return start_line + i
    return None


def find_line_number_for_text(content: str, text: str, start_line: int = 1) -> int | None:
    """Find the line number containing specific text.

    Args:
        content: Multi-line content to search
        text: Text to find
        start_line: Line number offset (1-indexed)

    Returns:
        Line number (1-indexed) or None if not found
    """
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if text in line:
            return start_line + i
    return None


def find_column_in_line(line: str, pattern: str | re.Pattern) -> int | None:
    """Find the column position where a pattern matches in a line.

    Args:
        line: Single line of text
        pattern: String or regex pattern to find

    Returns:
        Column number (1-indexed) or None if not found
    """
    if isinstance(pattern, str):
        idx = line.find(pattern)
        return idx + 1 if idx >= 0 else None
    else:
        match = pattern.search(line)
        return match.start() + 1 if match else None
