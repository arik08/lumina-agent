"""
Checklist schema for human review checklists.

This schema defines the structure for review checklists generated from
validation results. It supports:
- Structured JSON serialization
- API response formatting
- Progress tracking
- Confidence-based filtering

Usage:
    from schemas.checklist import (
        ReviewChecklistSchema,
        ChecklistItemSchema,
        SeveritySectionSchema,
    )

    # Create from validation report
    checklist = ReviewChecklistSchema.from_validation_report(report_dict)

    # Serialize to JSON
    json_output = checklist.model_dump_json(indent=2)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class Severity(str, Enum):
    """Issue severity levels."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ReviewPriority(str, Enum):
    """Priority level for review items."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ChecklistItemSchema(BaseModel):
    """A single item in the review checklist."""

    model_config = ConfigDict(extra="forbid")

    slide_number: int = Field(
        ge=0,
        description="Slide number (0 for global issues)"
    )
    category: str = Field(
        description="Issue category (e.g., 'empty_slide', 'placeholder_text')"
    )
    severity: Severity = Field(
        description="Issue severity level"
    )
    message: str = Field(
        description="Human-readable description of the issue"
    )
    suggestion: str = Field(
        default="",
        description="Suggested action to resolve the issue"
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context about the issue"
    )
    checked: bool = Field(
        default=False,
        description="Whether this item has been reviewed"
    )

    @computed_field
    @property
    def priority(self) -> ReviewPriority:
        """Map severity to review priority."""
        mapping = {
            Severity.ERROR: ReviewPriority.CRITICAL,
            Severity.WARNING: ReviewPriority.HIGH,
            Severity.INFO: ReviewPriority.MEDIUM,
        }
        return mapping.get(self.severity, ReviewPriority.LOW)

    @computed_field
    @property
    def slide_reference(self) -> str:
        """Human-readable slide reference."""
        return f"Slide {self.slide_number}" if self.slide_number > 0 else "Global"


class CategoryGroupSchema(BaseModel):
    """Group of checklist items by category."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(
        description="Category identifier"
    )
    display_name: str = Field(
        description="Human-readable category name"
    )
    items: list[ChecklistItemSchema] = Field(
        default_factory=list,
        description="Items in this category"
    )

    @computed_field
    @property
    def item_count(self) -> int:
        """Total items in this category."""
        return len(self.items)

    @computed_field
    @property
    def checked_count(self) -> int:
        """Number of checked items."""
        return sum(1 for item in self.items if item.checked)

    @classmethod
    def get_display_name(cls, category: str) -> str:
        """Get human-readable name for a category."""
        names = {
            "empty_slide": "Empty Slides",
            "minimal_content": "Minimal Content",
            "missing_title": "Missing Titles",
            "placeholder_text": "Placeholder Text",
            "text_overflow": "Text Overflow",
            "small_font": "Small Fonts",
            "inconsistent_titles": "Inconsistent Titles",
            "inconsistent_numbering": "Slide Numbering",
            "typography": "Typography Issues",
            "visual_type": "Visual Type Issues",
            "column_balance": "Column Balance",
            "whitespace": "Whitespace Issues",
        }
        return names.get(category, category.replace("_", " ").title())


class SeveritySectionSchema(BaseModel):
    """Section of checklist grouped by severity."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity = Field(
        description="Severity level for this section"
    )
    display_name: str = Field(
        description="Human-readable section name"
    )
    categories: list[CategoryGroupSchema] = Field(
        default_factory=list,
        description="Category groups within this severity"
    )

    @computed_field
    @property
    def total_items(self) -> int:
        """Total items across all categories."""
        return sum(cat.item_count for cat in self.categories)

    @computed_field
    @property
    def checked_items(self) -> int:
        """Total checked items across all categories."""
        return sum(cat.checked_count for cat in self.categories)

    @classmethod
    def get_display_name(cls, severity: Severity) -> str:
        """Get human-readable name for a severity level."""
        displays = {
            Severity.ERROR: "Errors (Must Fix)",
            Severity.WARNING: "Warnings (Should Fix)",
            Severity.INFO: "Info (Nice to Fix)",
        }
        return displays.get(severity, severity.value.title())


class ConfidenceInfoSchema(BaseModel):
    """Confidence information for the checklist."""

    model_config = ConfigDict(extra="forbid")

    level: str = Field(
        description="Confidence level (high, medium, low, very_low)"
    )
    percentage: float = Field(
        ge=0.0,
        le=100.0,
        description="Confidence percentage"
    )
    guidance: str = Field(
        description="Human-readable guidance based on confidence"
    )

    @classmethod
    def from_confidence_data(
        cls,
        level: str | None,
        percentage: float | None,
    ) -> "ConfidenceInfoSchema | None":
        """Create from raw confidence data."""
        if level is None or percentage is None:
            return None

        guidance_map = {
            "high": "Validation results are highly reliable. Focus on flagged issues.",
            "medium": "Results are reasonably reliable but may have gaps. Review flagged items carefully.",
            "low": "Limited validation data - interpret with caution. Manual review recommended.",
            "very_low": "Insufficient data for reliable assessment. Re-run with more validators.",
        }

        return cls(
            level=level,
            percentage=percentage,
            guidance=guidance_map.get(level, "Review all items carefully."),
        )


class ReviewChecklistSchema(BaseModel):
    """Complete review checklist schema."""

    model_config = ConfigDict(extra="forbid")

    # Metadata
    file_path: str = Field(
        description="Path to the analyzed presentation"
    )
    file_name: str = Field(
        description="File name only (no path)"
    )
    slide_count: int = Field(
        ge=0,
        description="Number of slides in presentation"
    )
    score: float = Field(
        ge=0.0,
        le=100.0,
        description="Quality score (0-100)"
    )
    passed: bool = Field(
        description="Whether the presentation passed validation"
    )
    generated_at: str = Field(
        description="Timestamp when checklist was generated"
    )

    # Issue summary
    summary: dict[str, int] = Field(
        description="Issue counts by severity (errors, warnings, info)"
    )

    # Checklist content
    sections: list[SeveritySectionSchema] = Field(
        default_factory=list,
        description="Checklist sections organized by severity"
    )

    # Recommendations
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable recommendations"
    )

    # Confidence (optional)
    confidence: ConfidenceInfoSchema | None = Field(
        default=None,
        description="Confidence information if available"
    )

    @computed_field
    @property
    def total_items(self) -> int:
        """Total checklist items."""
        return sum(section.total_items for section in self.sections)

    @computed_field
    @property
    def checked_items(self) -> int:
        """Total checked items."""
        return sum(section.checked_items for section in self.sections)

    @computed_field
    @property
    def progress_percentage(self) -> float:
        """Completion percentage."""
        if self.total_items == 0:
            return 100.0
        return (self.checked_items / self.total_items) * 100

    @computed_field
    @property
    def status_display(self) -> str:
        """Human-readable status."""
        return "PASS" if self.passed else "FAIL"

    @classmethod
    def from_validation_report(
        cls,
        report_data: dict[str, Any],
    ) -> "ReviewChecklistSchema":
        """Create checklist from validation report dictionary.

        Args:
            report_data: Output from quality_check.py --json

        Returns:
            Populated ReviewChecklistSchema instance
        """
        from pathlib import Path

        # Extract basic fields
        file_path = report_data.get("file_path", "unknown")
        file_name = Path(file_path).name if file_path else "unknown"

        # Parse issues into structure
        sections_dict: dict[Severity, dict[str, list[ChecklistItemSchema]]] = {
            Severity.ERROR: {},
            Severity.WARNING: {},
            Severity.INFO: {},
        }

        # Process main issues
        for issue_data in report_data.get("issues", []):
            try:
                severity = Severity(issue_data.get("severity", "info"))
            except ValueError:
                severity = Severity.INFO

            category = issue_data.get("category", "unknown")

            item = ChecklistItemSchema(
                slide_number=issue_data.get("slide_number", 0),
                category=category,
                severity=severity,
                message=issue_data.get("message", ""),
                suggestion=issue_data.get("suggestion", ""),
                details=issue_data.get("details", {}),
            )

            if category not in sections_dict[severity]:
                sections_dict[severity][category] = []
            sections_dict[severity][category].append(item)

        # Process Tier 2 results
        tier2 = report_data.get("tier2", {}) or {}
        _process_tier2_issues(sections_dict, tier2)

        # Build section objects
        sections = []
        for severity in [Severity.ERROR, Severity.WARNING, Severity.INFO]:
            if sections_dict[severity]:
                categories = [
                    CategoryGroupSchema(
                        category=cat,
                        display_name=CategoryGroupSchema.get_display_name(cat),
                        items=items,
                    )
                    for cat, items in sections_dict[severity].items()
                ]
                # Sort by item count descending
                categories.sort(key=lambda c: c.item_count, reverse=True)

                sections.append(SeveritySectionSchema(
                    severity=severity,
                    display_name=SeveritySectionSchema.get_display_name(severity),
                    categories=categories,
                ))

        # Extract confidence
        confidence_data = report_data.get("confidence", {}) or {}
        confidence = ConfidenceInfoSchema.from_confidence_data(
            level=confidence_data.get("level"),
            percentage=confidence_data.get("overall"),
        )

        return cls(
            file_path=file_path,
            file_name=file_name,
            slide_count=report_data.get("slide_count", 0),
            score=report_data.get("score", 0.0),
            passed=report_data.get("passed", False),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            summary=report_data.get("summary", {"errors": 0, "warnings": 0, "info": 0}),
            sections=sections,
            recommendations=report_data.get("recommendations", []),
            confidence=confidence,
        )


def _process_tier2_issues(
    sections_dict: dict[Severity, dict[str, list[ChecklistItemSchema]]],
    tier2: dict[str, Any],
) -> None:
    """Process Tier 2 validator issues into sections dict."""
    tier2_categories = [
        ("typography_hierarchy", "typography"),
        ("visual_type", "visual_type"),
        ("column_balance", "column_balance"),
        ("whitespace", "whitespace"),
    ]

    for tier2_key, category in tier2_categories:
        data = tier2.get(tier2_key, {}) or {}
        issues = data.get("issues", [])

        for issue in issues:
            severity_str = issue.get("severity", "info")
            try:
                severity = Severity(severity_str.lower())
            except ValueError:
                severity = Severity.INFO

            item = ChecklistItemSchema(
                slide_number=issue.get("slide_number", 0),
                category=category,
                severity=severity,
                message=issue.get("message", f"{category.replace('_', ' ').title()} issue"),
                suggestion=issue.get("suggestion", ""),
                details=issue.get("details", {}),
            )

            if category not in sections_dict[severity]:
                sections_dict[severity][category] = []
            sections_dict[severity][category].append(item)
