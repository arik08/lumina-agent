"""
Template configuration schema for template-agnostic PPTX generation.

This schema defines the configuration structure that maps abstract layout
capabilities to concrete template indices, along with brand colors and fonts.

Usage:
    from schemas.template_config import TemplateConfig, BrandConfig

    # Load config from JSON
    config = TemplateConfig.model_validate_json(Path("my-config.json").read_text())

    # Access brand colors
    primary = config.brand.primary_color  # "0196FF"

    # Get layout for a content type
    layout = config.get_layout_for_content_type("framework_3col")
    # Returns: {"index": 35, "name": "column-3-centered-a"}
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BrandConfig(BaseModel):
    """Brand styling configuration.

    Defines the color palette and typography for a template.
    All colors are hex codes without the # prefix.
    """

    model_config = ConfigDict(extra="allow")

    primary_color: str = Field(
        default="0196FF",
        description="Primary brand color (hex, no #). Used for emphasis, links, highlights."
    )
    secondary_color: str = Field(
        default="000000",
        description="Secondary color (hex, no #). Typically black for body text."
    )
    accent_color: str = Field(
        default="595959",
        description="Accent/muted color (hex, no #). Used for subtitles, captions."
    )
    header_font: str = Field(
        default="Aptos",
        description="Font family for titles and headers."
    )
    body_font: str = Field(
        default="Aptos",
        description="Font family for body text and bullets."
    )

    @field_validator("primary_color", "secondary_color", "accent_color")
    @classmethod
    def validate_hex_color(cls, v: str) -> str:
        """Ensure color is valid 6-character hex (no # prefix)."""
        # Strip # if provided
        v = v.lstrip("#")
        if len(v) != 6:
            raise ValueError(f"Color must be 6 hex characters, got: {v}")
        try:
            int(v, 16)
        except ValueError:
            raise ValueError(f"Invalid hex color: {v}")
        return v.upper()


class LayoutCapability(BaseModel):
    """A single layout capability mapping.

    Maps an abstract capability (like "column_3") to a concrete
    layout index and name in the template.
    """

    model_config = ConfigDict(extra="allow")

    layout_index: int = Field(ge=0, description="Index of the layout in the template")
    layout_name: str = Field(description="Name of the layout for debugging/tracing")
    use_case: str | None = Field(
        default=None,
        description="Optional description of when to use this layout"
    )


class TemplateConfig(BaseModel):
    """Complete template configuration for PPTX generation.

    This configuration enables template-agnostic slide generation by mapping:
    - Brand colors and fonts
    - Abstract capabilities to concrete layout indices
    - Content types to capability keys

    The mapping flow is:
    content_type (e.g., "framework_3col")
        -> content_type_routing["framework_3col"] = "column_3"
        -> layout_mappings["column_3"] = LayoutCapability(index=35, name="...")
    """

    model_config = ConfigDict(extra="allow")

    template_name: str = Field(description="Human-readable template identifier")
    template_path: str | None = Field(
        default=None,
        description="Relative or absolute path to the .pptx template file"
    )

    brand: BrandConfig = Field(default_factory=BrandConfig)

    # Abstract capability -> layout index mapping
    layout_mappings: dict[str, LayoutCapability] = Field(
        default_factory=dict,
        description="Maps capability keys (e.g., 'column_3') to layout info"
    )

    # Content type -> capability key routing
    content_type_routing: dict[str, str] = Field(
        default_factory=dict,
        description="Maps content types (e.g., 'framework_3col') to capability keys"
    )

    # Branding slide configuration
    requires_branding_slide: bool = Field(
        default=True,
        description="Whether to insert a branding slide as slide 1"
    )
    branding_layout_index: int | None = Field(
        default=58,
        description="Layout index for the branding slide"
    )

    # Fallback for unknown content types
    fallback_layout_index: int = Field(
        default=45,
        description="Layout index to use when no mapping matches"
    )
    fallback_layout_name: str = Field(
        default="content-centered-a",
        description="Layout name for fallback (for logging/debugging)"
    )

    def get_layout_for_capability(self, capability: str) -> dict:
        """Get layout info for a capability key.

        Args:
            capability: Capability key like 'column_3', 'title_cover', etc.

        Returns:
            Dict with 'index' and 'name' keys, or fallback if not found.
        """
        if capability in self.layout_mappings:
            layout = self.layout_mappings[capability]
            return {
                "index": layout.layout_index,
                "name": layout.layout_name,
                "use": layout.use_case or "",
            }
        # Return fallback
        return {
            "index": self.fallback_layout_index,
            "name": self.fallback_layout_name,
            "use": "fallback",
        }

    def get_layout_for_content_type(self, content_type: str) -> dict:
        """Get layout info for a content type.

        Resolves content_type -> capability -> layout mapping.

        Args:
            content_type: Content type like 'framework_3col', 'table', etc.

        Returns:
            Dict with 'index' and 'name' keys.
        """
        # First resolve content_type to capability
        capability = self.content_type_routing.get(content_type)
        if capability:
            return self.get_layout_for_capability(capability)

        # Try content_type directly as capability
        if content_type in self.layout_mappings:
            return self.get_layout_for_capability(content_type)

        # Return fallback
        return {
            "index": self.fallback_layout_index,
            "name": self.fallback_layout_name,
            "use": "fallback",
        }

    def get_color_map(self) -> dict[str, str]:
        """Get color map for inline text styling.

        Returns a dict mapping color names to hex codes.
        """
        return {
            "blue": self.brand.primary_color,
            "black": self.brand.secondary_color,
            "gray": self.brand.accent_color,
        }

    def get_preset_styles(self) -> dict[str, dict]:
        """Get preset style definitions using brand colors.

        Returns dict mapping preset names to style dicts.
        """
        return {
            "signpost": {"color": self.brand.primary_color, "size": 14},
            "question": {"color": self.brand.primary_color, "italic": True},
        }


# =============================================================================
# DEFAULT CONFIGURATIONS
# =============================================================================

# Default content type routing (same for all templates)
DEFAULT_CONTENT_TYPE_ROUTING = {
    # Title/structure slides
    "title_slide": "title_cover",
    "section_divider": "title_centered",
    "closing": "title_centered",
    "thank_you": "title_centered",
    "quote": "title_centered",
    "contact": "contact",
    # Column layouts
    "framework_2col": "column_2",
    "framework_3col": "column_3",
    "framework_4col": "column_4",
    "framework_5col": "column_5",
    "framework_cards": "column_4",
    "comparison": "column_2",
    # Content layouts
    "content": "content_with_image",
    "deliverables": "content_with_image",
    "timeline": "content_with_image",
    "content_no_image": "content_centered",
    # Table layouts
    "table": "title_centered",
    "pricing": "title_centered",
    "comparison_tables": "title_centered",
    "table_with_image": "content_with_image",
    # Special layouts
    "story_card": "story_card",
    # Grid layouts
    "grid_3x2_3body": "grid_3x2_3body",
    "grid_3x2_6body": "grid_3x2_6body",
    "grid_2x2_2body": "grid_2x2_2body",
    "grid_2x2_2body_b": "grid_2x2_2body_b",
    "content_image_top_4body": "content_image_top_4body",
}


def create_inner_chapter_config() -> TemplateConfig:
    """Create the default Inner Chapter template configuration.

    This captures the exact behavior of the hardcoded IC_LAYOUTS dict.
    """
    return TemplateConfig(
        template_name="inner-chapter",
        template_path="template/inner-chapter.pptx",
        brand=BrandConfig(
            primary_color="0196FF",
            secondary_color="000000",
            accent_color="595959",
            header_font="Aptos",
            body_font="Aptos",
        ),
        layout_mappings={
            # Title/structure
            "master_base": LayoutCapability(
                layout_index=58,
                layout_name="master-base",
                use_case="Branding slide (always Slide 1)",
            ),
            "title_cover": LayoutCapability(
                layout_index=0,
                layout_name="title-cover",
                use_case="Cover page with client, date, logos",
            ),
            "title_centered": LayoutCapability(
                layout_index=2,
                layout_name="title-centered",
                use_case="Section dividers, closing statements",
            ),
            # Content layouts
            "content_with_image": LayoutCapability(
                layout_index=3,
                layout_name="content-image-right-a",
                use_case="Bullets with image placeholder",
            ),
            "content_centered": LayoutCapability(
                layout_index=45,
                layout_name="content-centered-a",
                use_case="Centered content without image",
            ),
            "story_card": LayoutCapability(
                layout_index=8,
                layout_name="content-image-right-text-left",
                use_case="Story card with image right, text left",
            ),
            # Column layouts
            "column_2": LayoutCapability(
                layout_index=6,
                layout_name="column-2-centered",
                use_case="2-column comparisons",
            ),
            "column_3": LayoutCapability(
                layout_index=35,
                layout_name="column-3-centered-a",
                use_case="3-column comparisons",
            ),
            "column_4": LayoutCapability(
                layout_index=31,
                layout_name="column-4-centered",
                use_case="4-column framework/flow diagrams",
            ),
            "column_5": LayoutCapability(
                layout_index=27,
                layout_name="column-5-centered",
                use_case="5-column cards/comparisons",
            ),
            # Contact
            "contact": LayoutCapability(
                layout_index=52,
                layout_name="contact-black",
                use_case="Contact information (dark)",
            ),
            "contact_white": LayoutCapability(
                layout_index=51,
                layout_name="contact-white",
                use_case="Contact information (light)",
            ),
            # Grid layouts
            "grid_3x2_3body": LayoutCapability(
                layout_index=36,
                layout_name="grid-3x2-image-top-3-body",
                use_case="3 columns with images top, 3 body areas",
            ),
            "grid_3x2_6body": LayoutCapability(
                layout_index=37,
                layout_name="grid-3x2-image-top-6-body-a",
                use_case="3 columns with images top, 6 body areas",
            ),
            "grid_2x2_2body": LayoutCapability(
                layout_index=42,
                layout_name="grid-2x2-image-top-2-body-a",
                use_case="2 columns with images top, 2 body areas",
            ),
            "grid_2x2_2body_b": LayoutCapability(
                layout_index=44,
                layout_name="grid-2x2-image-top-2-body-b",
                use_case="2 columns with images top, 2 body areas (variant B)",
            ),
            "content_image_top_4body": LayoutCapability(
                layout_index=32,
                layout_name="content-image-top-4-body",
                use_case="4 columns with images top",
            ),
            # Fallback
            "fallback": LayoutCapability(
                layout_index=45,
                layout_name="content-centered-a",
                use_case="Fallback for unknown content types",
            ),
        },
        content_type_routing=DEFAULT_CONTENT_TYPE_ROUTING,
        requires_branding_slide=True,
        branding_layout_index=58,
        fallback_layout_index=45,
        fallback_layout_name="content-centered-a",
    )
