"""
GenerationResult schema for validating PPTX generation output.

This is the data contract for pptx-from-layout output, providing
structured reporting of generation success/failure per slide.

Usage:
    from schemas.generation_result import GenerationResult, SlideStatus

    # Create result after generation
    result = GenerationResult(
        success=True,
        output_path="/path/to/output.pptx",
        slides_total=16,
        slides_succeeded=16,
        slides_failed=0,
        slides_skipped=0,
    )

    # Access validation
    validated = GenerationResult.model_validate(result_dict)
"""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, Field, model_validator


class SlideStatus(str, Enum):
    """Status of a single slide generation."""

    SUCCESS = "success"  # Slide generated correctly
    PARTIAL = "partial"  # Slide generated with warnings
    FAILED = "failed"  # Fallback slide created
    SKIPPED = "skipped"  # Slide not attempted


class SlideError(BaseModel):
    """Error details for a specific slide.

    Provides structured error information with location tracking
    for debugging generation failures.
    """

    slide_number: int
    error_type: str
    message: str
    location: str | None = None  # e.g., "content.body[2]" or "layout.index"
    suggestion: str | None = None  # Optional fix suggestion


class SlideResult(BaseModel):
    """Result for a single slide generation.

    Tracks the outcome of generating one slide including
    status, warnings, and any errors encountered.
    """

    slide_number: int
    status: SlideStatus
    layout_name: str
    layout_index: int
    content_type: str
    warnings: list[str] = []
    errors: list[SlideError] = []


class GenerationResult(BaseModel):
    """Complete generation result for a PPTX file.

    Top-level result model that aggregates all slide results
    and provides summary counts for success/failure tracking.
    """

    success: bool
    output_path: str | None = None
    slides_total: int = Field(ge=0)
    slides_succeeded: int = Field(ge=0)
    slides_failed: int = Field(ge=0)
    slides_skipped: int = Field(ge=0)
    results: list[SlideResult] = []
    warnings: list[str] = []
    errors: list[SlideError] = []
    thumbnail_path: str | None = None  # Path to composite thumbnail JPEG
    visual_warnings: list[str] = []  # Warnings from visual validation (overflow, diff)

    @model_validator(mode="after")
    def check_counts(self) -> Self:
        """Validate that slide counts add up correctly."""
        total = self.slides_succeeded + self.slides_failed + self.slides_skipped
        if total != self.slides_total:
            raise ValueError(
                f"Slide counts don't add up: "
                f"{self.slides_succeeded} (succeeded) + "
                f"{self.slides_failed} (failed) + "
                f"{self.slides_skipped} (skipped) = {total}, "
                f"but slides_total is {self.slides_total}"
            )
        return self
