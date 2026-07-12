"""
Brand configuration schema for brand compliance validation.

This schema defines the complete brand configuration structure used by
brand_checker.py for validating presentations against brand guidelines.

The schema extends the basic BrandConfig from template_config.py with
additional fields needed for comprehensive brand validation:
- Allowed color palettes (beyond just primary/secondary/accent)
- Font family groupings (header, body, mono)
- Font size ranges for different text contexts
- Color tolerance settings

Usage:
    from schemas.brand_config import BrandConfigSchema, create_default_brand_config

    # Load from JSON
    config = BrandConfigSchema.model_validate_json(Path("brand.json").read_text())

    # Access brand details
    print(config.colors.primary)  # "0196FF"
    print(config.allowed_colors)  # ["0196FF", "000000", ...]

    # Use default Inner Chapter config
    ic_config = create_default_brand_config()
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ColorPalette(BaseModel):
    """Named color palette for a brand.

    Defines the core brand colors by semantic role.
    All colors are hex codes without the # prefix.
    """

    model_config = ConfigDict(extra="allow")

    primary: str = Field(
        default="0196FF",
        description="Primary brand color (hex, no #). Used for emphasis, links, highlights."
    )
    secondary: str = Field(
        default="000000",
        description="Secondary color (hex, no #). Typically black for body text."
    )
    accent: str = Field(
        default="595959",
        description="Accent/muted color (hex, no #). Used for subtitles, captions."
    )
    background_light: str = Field(
        default="FFFFFF",
        description="Light background color (hex, no #)."
    )
    background_dark: str = Field(
        default="2D2D2D",
        description="Dark background color (hex, no #)."
    )

    @field_validator("primary", "secondary", "accent", "background_light", "background_dark", mode="before")
    @classmethod
    def validate_hex_color(cls, v: str) -> str:
        """Ensure color is valid 6-character hex (no # prefix)."""
        if not isinstance(v, str):
            raise ValueError(f"Color must be a string, got: {type(v)}")
        # Strip # if provided
        v = v.lstrip("#")
        if len(v) != 6:
            raise ValueError(f"Color must be 6 hex characters, got: {v}")
        try:
            int(v, 16)
        except ValueError:
            raise ValueError(f"Invalid hex color: {v}")
        return v.upper()


class FontFamilies(BaseModel):
    """Font family groupings for different text contexts.

    Each field is a list of allowed fonts for that context,
    in order of preference.
    """

    model_config = ConfigDict(extra="allow")

    header: list[str] = Field(
        default_factory=lambda: ["Aptos", "Aptos Display"],
        description="Fonts allowed for titles and headers."
    )
    body: list[str] = Field(
        default_factory=lambda: ["Aptos", "Aptos Narrow"],
        description="Fonts allowed for body text and bullets."
    )
    mono: list[str] = Field(
        default_factory=lambda: ["Noto Mono"],
        description="Fonts allowed for monospace/code text."
    )


class FontSizeRange(BaseModel):
    """Min/max font size range in points."""

    min_pt: int = Field(ge=1, description="Minimum font size in points")
    max_pt: int = Field(ge=1, description="Maximum font size in points")

    @model_validator(mode="after")
    def validate_range(self) -> "FontSizeRange":
        """Ensure min <= max."""
        if self.min_pt > self.max_pt:
            raise ValueError(f"min_pt ({self.min_pt}) cannot exceed max_pt ({self.max_pt})")
        return self


class FontSizeRanges(BaseModel):
    """Font size ranges for different text contexts.

    Defines acceptable size ranges for validation.
    """

    model_config = ConfigDict(extra="allow")

    header_bar: FontSizeRange = Field(
        default_factory=lambda: FontSizeRange(min_pt=7, max_pt=9),
        description="Header bar/footer text size range."
    )
    title: FontSizeRange = Field(
        default_factory=lambda: FontSizeRange(min_pt=28, max_pt=44),
        description="Slide title size range."
    )
    subtitle: FontSizeRange = Field(
        default_factory=lambda: FontSizeRange(min_pt=18, max_pt=24),
        description="Subtitle/subheading size range."
    )
    body: FontSizeRange = Field(
        default_factory=lambda: FontSizeRange(min_pt=12, max_pt=20),
        description="Body text size range."
    )
    footnote: FontSizeRange = Field(
        default_factory=lambda: FontSizeRange(min_pt=8, max_pt=11),
        description="Footnote/caption size range."
    )


class LogoPlacement(BaseModel):
    """Logo placement specification for brand validation.

    Defines where a logo should appear and its size constraints.
    Positions are specified as percentages of slide dimensions (0-100).
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(
        description="Identifier for this logo placement (e.g., 'header', 'title_slide')."
    )
    required_on_slides: list[str] = Field(
        default_factory=list,
        description="Slide types or indices where this logo is required. "
        "Use 'all', 'first', 'last', or specific indices like '0', '1'."
    )
    position: str = Field(
        default="top-left",
        description="Expected position: 'top-left', 'top-right', 'bottom-left', "
        "'bottom-right', 'center', or 'header'."
    )
    min_width_pct: float = Field(
        default=5.0,
        ge=0,
        le=100,
        description="Minimum logo width as percentage of slide width."
    )
    max_width_pct: float = Field(
        default=25.0,
        ge=0,
        le=100,
        description="Maximum logo width as percentage of slide width."
    )
    min_height_pct: float = Field(
        default=2.0,
        ge=0,
        le=100,
        description="Minimum logo height as percentage of slide height."
    )
    max_height_pct: float = Field(
        default=15.0,
        ge=0,
        le=100,
        description="Maximum logo height as percentage of slide height."
    )
    position_tolerance_pct: float = Field(
        default=10.0,
        ge=0,
        le=50,
        description="Position tolerance as percentage of slide dimension."
    )

    @model_validator(mode="after")
    def validate_size_ranges(self) -> "LogoPlacement":
        """Ensure min <= max for width and height."""
        if self.min_width_pct > self.max_width_pct:
            raise ValueError(
                f"min_width_pct ({self.min_width_pct}) cannot exceed "
                f"max_width_pct ({self.max_width_pct})"
            )
        if self.min_height_pct > self.max_height_pct:
            raise ValueError(
                f"min_height_pct ({self.min_height_pct}) cannot exceed "
                f"max_height_pct ({self.max_height_pct})"
            )
        return self


class LogoConfig(BaseModel):
    """Logo configuration for brand validation.

    Defines expected logo placements and validation rules.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=True,
        description="Whether to perform logo validation."
    )
    placements: list[LogoPlacement] = Field(
        default_factory=list,
        description="List of expected logo placements to validate."
    )
    require_on_first_slide: bool = Field(
        default=True,
        description="Require logo on the first/title slide."
    )
    require_on_last_slide: bool = Field(
        default=False,
        description="Require logo on the last/closing slide."
    )


class BrandConfigSchema(BaseModel):
    """Complete brand configuration schema for validation.

    This schema captures all brand guidelines needed to validate
    a presentation for brand compliance:
    - Brand identity (name)
    - Color palette with semantic roles
    - Allowed colors (full list including secondary/theme colors)
    - Font families by context
    - Allowed fonts (full list)
    - Font size ranges

    The brand_checker.py uses this schema to validate presentations
    and flag brand violations.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(
        default="Inner Chapter",
        description="Brand name for reports and identification."
    )

    colors: ColorPalette = Field(
        default_factory=ColorPalette,
        description="Named color palette with semantic roles."
    )

    allowed_colors: list[str] = Field(
        default_factory=lambda: [
            "0196FF",  # Primary blue
            "000000",  # Black
            "FFFFFF",  # White
            "595959",  # Gray
            "2D2D2D",  # Dark background
            "5E5E5E",  # Secondary dark (theme)
            "DDDDDD",  # Light gray (borders)
        ],
        description="Complete list of allowed colors (hex, no #)."
    )

    fonts: FontFamilies = Field(
        default_factory=FontFamilies,
        description="Font family groupings by context."
    )

    allowed_fonts: list[str] = Field(
        default_factory=lambda: [
            "Aptos",
            "Aptos Display",
            "Aptos Narrow",
            "Noto Mono",
            "System Font Regular",  # For bullets
        ],
        description="Complete list of allowed font names."
    )

    font_size_ranges: FontSizeRanges = Field(
        default_factory=FontSizeRanges,
        description="Font size ranges by text context."
    )

    logo: LogoConfig = Field(
        default_factory=LogoConfig,
        description="Logo placement configuration for brand validation."
    )

    @field_validator("allowed_colors", mode="before")
    @classmethod
    def normalize_allowed_colors(cls, v: list[str]) -> list[str]:
        """Normalize all colors to uppercase without #."""
        if not isinstance(v, list):
            return v
        normalized = []
        for color in v:
            if isinstance(color, str):
                normalized.append(color.lstrip("#").upper())
            else:
                normalized.append(color)
        return normalized

    @model_validator(mode="after")
    def ensure_palette_colors_in_allowed(self) -> "BrandConfigSchema":
        """Ensure all palette colors are in allowed_colors list."""
        palette_colors = [
            self.colors.primary,
            self.colors.secondary,
            self.colors.accent,
            self.colors.background_light,
            self.colors.background_dark,
        ]
        for color in palette_colors:
            if color not in self.allowed_colors:
                self.allowed_colors.append(color)
        return self

    @model_validator(mode="after")
    def ensure_font_families_in_allowed(self) -> "BrandConfigSchema":
        """Ensure all font family fonts are in allowed_fonts list."""
        all_fonts = (
            self.fonts.header +
            self.fonts.body +
            self.fonts.mono
        )
        for font in all_fonts:
            if font not in self.allowed_fonts:
                self.allowed_fonts.append(font)
        return self

    def to_checker_format(self) -> dict:
        """Convert to the dict format expected by BrandComplianceChecker.

        This maintains backward compatibility with the existing
        brand_checker.py DEFAULT_BRAND_CONFIG format.

        Returns:
            Dict in the format expected by brand_checker.py
        """
        return {
            "name": self.name,
            "colors": {
                "primary": self.colors.primary,
                "secondary": self.colors.secondary,
                "accent": self.colors.accent,
                "background_light": self.colors.background_light,
                "background_dark": self.colors.background_dark,
            },
            "allowed_colors": list(self.allowed_colors),
            "fonts": {
                "header": list(self.fonts.header),
                "body": list(self.fonts.body),
                "mono": list(self.fonts.mono),
            },
            "allowed_fonts": list(self.allowed_fonts),
            "font_size_ranges": {
                "header_bar": (self.font_size_ranges.header_bar.min_pt, self.font_size_ranges.header_bar.max_pt),
                "title": (self.font_size_ranges.title.min_pt, self.font_size_ranges.title.max_pt),
                "subtitle": (self.font_size_ranges.subtitle.min_pt, self.font_size_ranges.subtitle.max_pt),
                "body": (self.font_size_ranges.body.min_pt, self.font_size_ranges.body.max_pt),
                "footnote": (self.font_size_ranges.footnote.min_pt, self.font_size_ranges.footnote.max_pt),
            },
            "logo": {
                "enabled": self.logo.enabled,
                "require_on_first_slide": self.logo.require_on_first_slide,
                "require_on_last_slide": self.logo.require_on_last_slide,
                "placements": [
                    {
                        "name": p.name,
                        "required_on_slides": list(p.required_on_slides),
                        "position": p.position,
                        "min_width_pct": p.min_width_pct,
                        "max_width_pct": p.max_width_pct,
                        "min_height_pct": p.min_height_pct,
                        "max_height_pct": p.max_height_pct,
                        "position_tolerance_pct": p.position_tolerance_pct,
                    }
                    for p in self.logo.placements
                ],
            },
        }

    @classmethod
    def from_checker_format(cls, data: dict) -> "BrandConfigSchema":
        """Create from the dict format used by BrandComplianceChecker.

        This allows loading existing brand config dicts.

        Args:
            data: Dict in DEFAULT_BRAND_CONFIG format

        Returns:
            BrandConfigSchema instance
        """
        colors_data = data.get("colors", {})
        fonts_data = data.get("fonts", {})
        size_ranges = data.get("font_size_ranges", {})
        logo_data = data.get("logo", {})

        # Convert tuple ranges to FontSizeRange objects
        font_size_ranges = {}
        for key, value in size_ranges.items():
            if isinstance(value, (tuple, list)) and len(value) == 2:
                font_size_ranges[key] = FontSizeRange(min_pt=value[0], max_pt=value[1])

        # Convert logo placements
        logo_placements = []
        for p in logo_data.get("placements", []):
            logo_placements.append(LogoPlacement(
                name=p.get("name", "logo"),
                required_on_slides=p.get("required_on_slides", []),
                position=p.get("position", "top-left"),
                min_width_pct=p.get("min_width_pct", 5.0),
                max_width_pct=p.get("max_width_pct", 25.0),
                min_height_pct=p.get("min_height_pct", 2.0),
                max_height_pct=p.get("max_height_pct", 15.0),
                position_tolerance_pct=p.get("position_tolerance_pct", 10.0),
            ))

        logo_config = LogoConfig(
            enabled=logo_data.get("enabled", True),
            placements=logo_placements,
            require_on_first_slide=logo_data.get("require_on_first_slide", True),
            require_on_last_slide=logo_data.get("require_on_last_slide", False),
        )

        return cls(
            name=data.get("name", "Unknown"),
            colors=ColorPalette(
                primary=colors_data.get("primary", "0196FF"),
                secondary=colors_data.get("secondary", "000000"),
                accent=colors_data.get("accent", "595959"),
                background_light=colors_data.get("background_light", "FFFFFF"),
                background_dark=colors_data.get("background_dark", "2D2D2D"),
            ),
            allowed_colors=data.get("allowed_colors", []),
            fonts=FontFamilies(
                header=fonts_data.get("header", ["Aptos"]),
                body=fonts_data.get("body", ["Aptos"]),
                mono=fonts_data.get("mono", ["Noto Mono"]),
            ),
            allowed_fonts=data.get("allowed_fonts", []),
            font_size_ranges=FontSizeRanges(**font_size_ranges) if font_size_ranges else FontSizeRanges(),
            logo=logo_config,
        )


def create_default_brand_config() -> BrandConfigSchema:
    """Create the default Inner Chapter brand configuration.

    Returns the same configuration as DEFAULT_BRAND_CONFIG in brand_checker.py
    but as a validated Pydantic model.

    Returns:
        BrandConfigSchema with Inner Chapter brand settings
    """
    return BrandConfigSchema(
        name="Inner Chapter",
        colors=ColorPalette(
            primary="0196FF",
            secondary="000000",
            accent="595959",
            background_light="FFFFFF",
            background_dark="2D2D2D",
        ),
        allowed_colors=[
            "0196FF",  # Primary blue
            "000000",  # Black
            "FFFFFF",  # White
            "595959",  # Gray
            "2D2D2D",  # Dark background
            "5E5E5E",  # Secondary dark (theme)
            "DDDDDD",  # Light gray (borders)
        ],
        fonts=FontFamilies(
            header=["Aptos", "Aptos Display"],
            body=["Aptos", "Aptos Narrow"],
            mono=["Noto Mono"],
        ),
        allowed_fonts=[
            "Aptos",
            "Aptos Display",
            "Aptos Narrow",
            "Noto Mono",
            "System Font Regular",
        ],
        font_size_ranges=FontSizeRanges(
            header_bar=FontSizeRange(min_pt=7, max_pt=9),
            title=FontSizeRange(min_pt=28, max_pt=44),
            subtitle=FontSizeRange(min_pt=18, max_pt=24),
            body=FontSizeRange(min_pt=12, max_pt=20),
            footnote=FontSizeRange(min_pt=8, max_pt=11),
        ),
        logo=LogoConfig(
            enabled=True,
            require_on_first_slide=True,
            require_on_last_slide=False,
            placements=[
                LogoPlacement(
                    name="title_slide_logo",
                    required_on_slides=["0"],  # First slide (master branding)
                    position="center",
                    min_width_pct=10.0,
                    max_width_pct=50.0,
                    min_height_pct=5.0,
                    max_height_pct=30.0,
                    position_tolerance_pct=20.0,
                ),
            ],
        ),
    )


# Convenient type alias for backward compatibility
BrandConfiguration = BrandConfigSchema
