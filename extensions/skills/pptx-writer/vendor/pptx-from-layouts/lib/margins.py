"""margins.py - Margin enforcement utilities for PPTX generation.

Provides runtime margin enforcement when positioning shapes programmatically.
Ensures generated content respects safe margins regardless of template configuration.

Based on IC Proposal Specification and 18pt margin standard.
"""

from pptx.util import Inches
from dataclasses import dataclass

# =============================================================================
# CONSTANTS
# =============================================================================

# Standard 16:9 slide dimensions in inches
SLIDE_WIDTH_INCHES = 13.333
SLIDE_HEIGHT_INCHES = 7.5

# Default margins in inches (18pt standard for left/right)
# These are the safe zones where content should stay within
DEFAULT_MARGINS = {
    "left": 0.25,       # 18pt = 0.25" left margin
    "top": 0.40,        # Below header bar
    "right": 0.25,      # 18pt = 0.25" right margin
    "bottom": 0.50,     # Content boundary
}

# Original IC spec margins (kept for reference/backwards compatibility)
IC_SPEC_MARGINS = {
    "left": 0.17,       # 155,575 EMU
    "top": 0.40,        # 368,300 EMU (below header bar)
    "right": 0.17,      # mirrored
    "bottom": 0.50,     # approximate
}

# EMU conversion constant
EMU_PER_INCH = 914400

# Minimum shape dimensions to avoid degenerate shapes
MIN_WIDTH_INCHES = 0.5
MIN_HEIGHT_INCHES = 0.5


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SafeArea:
    """Represents the safe content area within margins."""
    left: float     # Left edge in inches
    top: float      # Top edge in inches
    right: float    # Right edge in inches (absolute position)
    bottom: float   # Bottom edge in inches (absolute position)
    width: float    # Available width
    height: float   # Available height


@dataclass
class Position:
    """A position with dimensions, in inches."""
    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        """Right edge position."""
        return self.left + self.width

    @property
    def bottom(self) -> float:
        """Bottom edge position."""
        return self.top + self.height


# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def get_safe_area(
    margins: dict = None,
    slide_width: float = SLIDE_WIDTH_INCHES,
    slide_height: float = SLIDE_HEIGHT_INCHES
) -> SafeArea:
    """Calculate the safe content area given margins.

    Args:
        margins: Dict with left/top/right/bottom margin values in inches.
                 Uses DEFAULT_MARGINS if not provided.
        slide_width: Slide width in inches (default: 13.333")
        slide_height: Slide height in inches (default: 7.5")

    Returns:
        SafeArea with calculated boundaries.
    """
    m = margins or DEFAULT_MARGINS

    left = m.get("left", DEFAULT_MARGINS["left"])
    top = m.get("top", DEFAULT_MARGINS["top"])
    right_margin = m.get("right", DEFAULT_MARGINS["right"])
    bottom_margin = m.get("bottom", DEFAULT_MARGINS["bottom"])

    right = slide_width - right_margin
    bottom = slide_height - bottom_margin

    return SafeArea(
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        width=right - left,
        height=bottom - top,
    )


def enforce_margins(
    left: float,
    top: float,
    width: float,
    height: float,
    margins: dict = None,
    slide_width: float = SLIDE_WIDTH_INCHES,
    slide_height: float = SLIDE_HEIGHT_INCHES,
    allow_shrink: bool = True,
    min_width: float = MIN_WIDTH_INCHES,
    min_height: float = MIN_HEIGHT_INCHES,
) -> Position:
    """Enforce margin constraints on a shape position and size.

    Adjusts position and optionally shrinks dimensions to fit within safe area.

    Args:
        left: Left position in inches
        top: Top position in inches
        width: Width in inches
        height: Height in inches
        margins: Margin dict (uses DEFAULT_MARGINS if not provided)
        slide_width: Slide width in inches
        slide_height: Slide height in inches
        allow_shrink: If True, shrink width/height to fit. If False, only adjust position.
        min_width: Minimum allowed width after shrinking
        min_height: Minimum allowed height after shrinking

    Returns:
        Position with adjusted values respecting margins.
    """
    safe = get_safe_area(margins, slide_width, slide_height)

    new_left = left
    new_top = top
    new_width = width
    new_height = height

    # Enforce left margin
    if new_left < safe.left:
        if allow_shrink:
            # Reduce width by the amount we're moving right
            adjustment = safe.left - new_left
            new_width = max(min_width, new_width - adjustment)
        new_left = safe.left

    # Enforce top margin
    if new_top < safe.top:
        if allow_shrink:
            adjustment = safe.top - new_top
            new_height = max(min_height, new_height - adjustment)
        new_top = safe.top

    # Enforce right margin (check if right edge exceeds)
    right_edge = new_left + new_width
    if right_edge > safe.right:
        if allow_shrink:
            new_width = max(min_width, safe.right - new_left)
        else:
            # Shift left to fit
            new_left = max(safe.left, safe.right - new_width)

    # Enforce bottom margin
    bottom_edge = new_top + new_height
    if bottom_edge > safe.bottom:
        if allow_shrink:
            new_height = max(min_height, safe.bottom - new_top)
        else:
            # Shift up to fit
            new_top = max(safe.top, safe.bottom - new_height)

    return Position(
        left=new_left,
        top=new_top,
        width=new_width,
        height=new_height,
    )


def clamp_to_safe_area(
    value: float,
    edge: str,
    margins: dict = None,
    slide_width: float = SLIDE_WIDTH_INCHES,
    slide_height: float = SLIDE_HEIGHT_INCHES,
) -> float:
    """Clamp a single position value to the safe area.

    Args:
        value: Position value in inches
        edge: Which edge to clamp - "left", "top", "right", "bottom"
        margins: Margin dict
        slide_width: Slide width in inches
        slide_height: Slide height in inches

    Returns:
        Clamped value in inches.
    """
    safe = get_safe_area(margins, slide_width, slide_height)

    if edge == "left":
        return max(safe.left, value)
    elif edge == "top":
        return max(safe.top, value)
    elif edge == "right":
        return min(safe.right, value)
    elif edge == "bottom":
        return min(safe.bottom, value)
    else:
        raise ValueError(f"Invalid edge: {edge}. Must be left/top/right/bottom")


def safe_left(value: float, margins: dict = None) -> float:
    """Return value clamped to minimum left margin.

    Args:
        value: Desired left position in inches
        margins: Optional margin dict

    Returns:
        Safe left position (at least the left margin)
    """
    m = margins or DEFAULT_MARGINS
    return max(m.get("left", DEFAULT_MARGINS["left"]), value)


def safe_right_edge(left: float, width: float, margins: dict = None) -> float:
    """Calculate safe width that doesn't exceed right margin.

    Args:
        left: Left position in inches
        width: Desired width in inches
        margins: Optional margin dict

    Returns:
        Safe width that keeps right edge within margin
    """
    safe = get_safe_area(margins)
    max_width = safe.right - left
    return max(MIN_WIDTH_INCHES, min(width, max_width))


# =============================================================================
# PPTX HELPER FUNCTIONS
# =============================================================================

def enforce_margins_emu(
    left_emu: int,
    top_emu: int,
    width_emu: int,
    height_emu: int,
    margins: dict = None,
    allow_shrink: bool = True,
) -> tuple[int, int, int, int]:
    """Enforce margins with EMU input/output.

    Convenience wrapper for code that works in EMU units.

    Args:
        left_emu: Left position in EMU
        top_emu: Top position in EMU
        width_emu: Width in EMU
        height_emu: Height in EMU
        margins: Margin dict in inches
        allow_shrink: Allow dimension shrinking

    Returns:
        Tuple of (left, top, width, height) in EMU
    """
    # Convert EMU to inches
    left = left_emu / EMU_PER_INCH
    top = top_emu / EMU_PER_INCH
    width = width_emu / EMU_PER_INCH
    height = height_emu / EMU_PER_INCH

    # Enforce margins
    pos = enforce_margins(left, top, width, height, margins, allow_shrink=allow_shrink)

    # Convert back to EMU
    return (
        int(pos.left * EMU_PER_INCH),
        int(pos.top * EMU_PER_INCH),
        int(pos.width * EMU_PER_INCH),
        int(pos.height * EMU_PER_INCH),
    )


def safe_inches(
    left: float,
    top: float,
    width: float,
    height: float,
    margins: dict = None,
) -> tuple:
    """Return margin-safe position as Inches objects.

    Convenience function for direct use with pptx shape creation.

    Args:
        left: Left position in inches
        top: Top position in inches
        width: Width in inches
        height: Height in inches
        margins: Optional margin dict

    Returns:
        Tuple of (Inches(left), Inches(top), Inches(width), Inches(height))
    """
    pos = enforce_margins(left, top, width, height, margins)
    return (
        Inches(pos.left),
        Inches(pos.top),
        Inches(pos.width),
        Inches(pos.height),
    )


def calculate_content_width(margins: dict = None) -> float:
    """Calculate available content width within margins.

    Args:
        margins: Optional margin dict

    Returns:
        Available width in inches
    """
    safe = get_safe_area(margins)
    return safe.width


def calculate_content_height(margins: dict = None) -> float:
    """Calculate available content height within margins.

    Args:
        margins: Optional margin dict

    Returns:
        Available height in inches
    """
    safe = get_safe_area(margins)
    return safe.height


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def is_within_margins(
    left: float,
    top: float,
    width: float,
    height: float,
    margins: dict = None,
    tolerance: float = 0.01,
) -> bool:
    """Check if a shape is within safe margins.

    Args:
        left: Left position in inches
        top: Top position in inches
        width: Width in inches
        height: Height in inches
        margins: Margin dict
        tolerance: Tolerance in inches for boundary checks

    Returns:
        True if shape is fully within margins (with tolerance)
    """
    safe = get_safe_area(margins)

    return (
        left >= safe.left - tolerance and
        top >= safe.top - tolerance and
        left + width <= safe.right + tolerance and
        top + height <= safe.bottom + tolerance
    )


def get_margin_violations(
    left: float,
    top: float,
    width: float,
    height: float,
    margins: dict = None,
    tolerance: float = 0.01,
) -> list[str]:
    """Get list of margin violations for a shape.

    Args:
        left: Left position in inches
        top: Top position in inches
        width: Width in inches
        height: Height in inches
        margins: Margin dict
        tolerance: Tolerance for checks

    Returns:
        List of violation descriptions (empty if compliant)
    """
    safe = get_safe_area(margins)
    violations = []

    if left < safe.left - tolerance:
        violations.append(f"left edge ({left:.3f}\") < left margin ({safe.left:.3f}\")")

    if top < safe.top - tolerance:
        violations.append(f"top edge ({top:.3f}\") < top margin ({safe.top:.3f}\")")

    right = left + width
    if right > safe.right + tolerance:
        violations.append(f"right edge ({right:.3f}\") > right limit ({safe.right:.3f}\")")

    bottom = top + height
    if bottom > safe.bottom + tolerance:
        violations.append(f"bottom edge ({bottom:.3f}\") > bottom limit ({safe.bottom:.3f}\")")

    return violations
