"""
LayoutPlan schema for validating slide layout plan JSON structures.

This is the primary data contract between slide-outline-to-layout (producer)
and pptx-from-layout (consumer). Validation ensures data integrity at
skill boundaries with clear error messages.

Usage:
    from schemas.layout_plan import LayoutPlan

    # Validate from JSON file
    plan = LayoutPlan.model_validate_json(Path("layout-plan.json").read_text())

    # Access validated data
    for slide in plan.slides:
        print(f"Slide {slide.slide_number}: {slide.layout.name}")
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import BodyItem, StyledRun


class Meta(BaseModel):
    """Layout plan metadata.

    Contains type identification, version info, template reference,
    and any warnings or parsing issues encountered.
    """

    type: Literal["slide_layout_plan"] = "slide_layout_plan"
    version: str = "2.0"
    template: str = "inner-chapter"
    slide_count: int = Field(ge=0)
    warnings: list[str] = []
    notes: str = ""
    parsing_issues: list[str] = []


class TemplateSummary(BaseModel):
    """Template capabilities summary.

    Describes the constraints and capabilities of the target template.
    """

    max_body: int = Field(ge=0, default=10)
    max_picture: int = Field(ge=0, default=12)
    layout_count: int = Field(ge=1, le=100, default=60)


class LayoutInfo(BaseModel):
    """Slide layout assignment.

    Maps a slide to a specific layout in the template with
    matching metadata for debugging and traceability.
    """

    name: str
    index: int = Field(ge=0)
    match_type: str = "semantic"
    signature: str = ""
    placeholders: list[str] = []

    @field_validator("index")
    @classmethod
    def validate_index_range(cls, v: int) -> int:
        """Accept any non-negative layout index.

        Phase 3: Out-of-range indices handled at generation time via fallback
        resolution using actual template layout count.
        """
        return v


class ContentBody(BaseModel):
    """Standard content structure for slide content.

    Used for slides with title, headline, and body bullet points.
    """

    model_config = ConfigDict(extra="allow")

    title: str | None = None
    subtitle: str | None = None
    headline: str | None = None
    body: list[str] = []
    body_count: int = 0
    metadata: list[str] = []


# Valid content types supported by the generation pipeline
VALID_CONTENT_TYPES = {
    "branding",
    "title_slide",
    "content",
    "table",
    "timeline",
    "deliverables",
    "contact",
    "closing",
    "quote",
    "comparison",
    "framework",
    "framework_2col",
    "framework_3col",
    "framework_4col",
    "framework_5col",
    "framework_cards",
    "section_divider",
    "story_card",
    "comparison_tables",
    "table_with_image",
    # Grid layouts
    "grid_2x2",
    "grid_2x2_2body",
    "grid_2x2_2body_b",
    "grid_2x2_4body",
    "grid_2x4",
    "grid_3x2",
    "grid_3x2_3body",
    "grid_3x2_6body",
    "grid_3x2_text_top",
}


class SlideSpec(BaseModel):
    """Single slide specification.

    Contains all information needed to generate one slide:
    layout assignment, content, and type-specific data.
    """

    model_config = ConfigDict(extra="allow")  # Allow extra fields for flexibility

    slide_number: int = Field(ge=1)
    layout: LayoutInfo
    content: dict = {}  # Flexible content dict; type-specific validation deferred
    content_type: str = "content"
    extras: dict = {}
    visual_type: str | None = None

    # Optional type-specific fields (populated based on content_type)
    # Note: Column/card dicts may contain optional 'file_path' for image insertion
    columns: list[dict] | None = None
    cards: list[dict] | None = None
    timeline: list[dict] | None = None
    deliverables: list[dict] | None = None
    tables: list[dict] | None = None
    table_blocks: list[dict] | None = None

    # Image file paths for direct insertion (optional)
    # extras.image_files: list[str] - paths to images for multi-image slides
    # column.file_path: str - path to image for a specific column
    # card.file_path: str - path to image for a specific card
    # background: str - can be a file path for story_card slides

    # Styled content fields for rich text formatting
    headline_styled: list[StyledRun] | None = None
    headline_bold: bool = False
    body_styled: list[BodyItem] | None = None

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        """Accept any content_type value.

        Phase 3: Unknown types handled at generation time via fallback
        resolution.
        """
        return v


class LayoutPlan(BaseModel):
    """Complete layout plan for PPTX generation.

    This is the top-level model that validates an entire layout plan JSON.
    It contains metadata, optional template summary, and a list of slides.
    """

    model_config = ConfigDict(populate_by_name=True)

    meta: Meta = Field(alias="_meta")
    template_summary: TemplateSummary | None = None
    slides: list[SlideSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def check_slide_count(self) -> Self:
        """Warn if metadata slide_count doesn't match actual slide count.

        This is a warning, not an error, since metadata can drift.
        The actual slide list is the source of truth.
        """
        if self.meta.slide_count != len(self.slides):
            self.meta.warnings.append(
                f"Metadata slide_count ({self.meta.slide_count}) "
                f"doesn't match actual count ({len(self.slides)})"
            )
        return self
