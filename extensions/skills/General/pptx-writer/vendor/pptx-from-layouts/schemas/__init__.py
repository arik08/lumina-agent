"""
Pydantic schema module for PowerPoint generation pipeline.

This module provides type-safe validation at skill boundaries:
- LayoutPlan: Validates layout plan JSON from slide-outline-to-layout
- GenerationResult: Validates output from pptx-from-layout
- Supporting models for slides, layouts, content types

Usage:
    from schemas import LayoutPlan, GenerationResult, SlideSpec

    # Validate layout plan from JSON file
    plan = LayoutPlan.model_validate_json(Path("layout-plan.json").read_text())

    # Access validated data with full type hints
    for slide in plan.slides:
        print(f"Slide {slide.slide_number}: {slide.layout.name}")
"""

from .common import BodyItem, StyledRun
from .generation_result import GenerationResult, SlideError, SlideResult, SlideStatus
from .layout_plan import (
    ContentBody,
    LayoutInfo,
    LayoutPlan,
    Meta,
    SlideSpec,
    TemplateSummary,
)
from .pipeline_state import PipelineStage, PipelineState, SlideConfidence, StageRecord
from .template_config import (
    BrandConfig,
    LayoutCapability,
    TemplateConfig,
    DEFAULT_CONTENT_TYPE_ROUTING,
    create_inner_chapter_config,
)
from .brand_config import (
    BrandConfigSchema,
    ColorPalette,
    FontFamilies,
    FontSizeRange,
    FontSizeRanges,
    create_default_brand_config,
)

__all__ = [
    # Common types
    "StyledRun",
    "BodyItem",
    # Layout plan models
    "LayoutPlan",
    "SlideSpec",
    "LayoutInfo",
    "Meta",
    "TemplateSummary",
    "ContentBody",
    # Generation result models
    "GenerationResult",
    "SlideResult",
    "SlideError",
    "SlideStatus",
    # Pipeline state models
    "PipelineState",
    "PipelineStage",
    "StageRecord",
    "SlideConfidence",
    # Template config models
    "TemplateConfig",
    "BrandConfig",
    "LayoutCapability",
    "DEFAULT_CONTENT_TYPE_ROUTING",
    "create_inner_chapter_config",
    # Brand config schema models
    "BrandConfigSchema",
    "ColorPalette",
    "FontFamilies",
    "FontSizeRange",
    "FontSizeRanges",
    "create_default_brand_config",
]
