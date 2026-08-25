"""Visual validation utilities for PPTX generation.

Provides rendering (PPTX -> PDF -> PNG), composite grid creation,
text overflow detection, and font discovery. The rendering pipeline
converts PPTX to per-slide images for visual comparison and produces
composite thumbnail grids.

Requires: LibreOffice (soffice), pdf2image, Pillow
"""

import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFont
from pdf2image import convert_from_path

# Import font fallback utilities
_scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from font_fallback import (
    _find_font_file,
    get_available_font_with_path,
)


def find_font_path(font_name: str) -> tuple[str | None, bool]:
    """Find font file path on system with fallback chain support.

    Searches for the requested font, falling back through the chain
    (Aptos → Calibri → Arial → sans-serif) if not found.

    Args:
        font_name: Font family name to search for (e.g. 'Aptos', 'Helvetica').

    Returns:
        Tuple of (path, is_exact_match). Path is None if no font found
        (even after fallbacks). is_exact_match is True only when the
        original font_name was found (not a fallback).
    """
    # First, try to find the requested font directly
    path, is_exact = _find_font_file(font_name)
    if path:
        return (path, is_exact)

    # If not found, use the fallback chain
    fallback_name, fallback_path = get_available_font_with_path(font_name)

    if fallback_path:
        # Found a fallback - mark as not exact match since it's a fallback
        return (fallback_path, False)

    return (None, False)


def _measure_text_width(text: str, font: ImageFont.FreeTypeFont) -> float:
    """Measure text width using kerning-aware method.

    Uses font.getlength() for accurate measurement that accounts for
    kerning pairs (e.g., 'AV', 'To', 'We'). Falls back to getbbox for
    older Pillow versions.

    Args:
        text: The text to measure.
        font: A loaded PIL FreeTypeFont instance.

    Returns:
        Text width in the same units as font metrics (points/pixels).
    """
    if not text:
        return 0.0
    # Prefer getlength() for kerning-aware measurement (Pillow 8.0+)
    if hasattr(font, 'getlength'):
        return font.getlength(text)
    # Fallback to getbbox
    bbox = font.getbbox(text)
    if bbox:
        return bbox[2] - bbox[0]
    return 0.0


def _break_long_word(
    word: str, font: ImageFont.FreeTypeFont, max_width: float, hyphen_width: float
) -> list[str]:
    """Break a long word into multiple lines with hyphens.

    Args:
        word: The word to break.
        font: A loaded PIL FreeTypeFont instance.
        max_width: Maximum line width.
        hyphen_width: Pre-measured width of hyphen character.

    Returns:
        List of word fragments (with hyphens except for last fragment).
    """
    if not word:
        return ['']

    fragments: list[str] = []
    remaining = word
    max_width_with_hyphen = max_width - hyphen_width

    while remaining:
        if _measure_text_width(remaining, font) <= max_width:
            # Remaining text fits
            fragments.append(remaining)
            break

        # Find break point - binary search for longest prefix that fits
        low, high = 1, len(remaining)
        best_break = 1  # At minimum, take one character

        while low <= high:
            mid = (low + high) // 2
            prefix = remaining[:mid]
            prefix_width = _measure_text_width(prefix, font)

            if prefix_width <= max_width_with_hyphen:
                best_break = mid
                low = mid + 1
            else:
                high = mid - 1

        # Ensure we make progress (at least 1 char per line)
        if best_break == 0:
            best_break = 1

        fragment = remaining[:best_break] + '-'
        fragments.append(fragment)
        remaining = remaining[best_break:]

    return fragments if fragments else [word]


def _wrap_text(
    text: str, font: ImageFont.FreeTypeFont, max_width: float
) -> list[str]:
    """Word-wrap text to fit within max_width using actual font metrics.

    Uses kerning-aware text measurement for accurate width calculation.
    Handles long words that exceed line width by breaking them with hyphens.

    Args:
        text: The text to wrap.
        font: A loaded PIL FreeTypeFont instance.
        max_width: Maximum line width in the same units as font metrics (points/pixels).

    Returns:
        List of wrapped lines. At minimum [''] for empty input.
    """
    if not text or not text.strip():
        return [""]

    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current_line = ""

    # Pre-measure hyphen width for word breaking
    hyphen_width = _measure_text_width('-', font)

    for word in words:
        word_width = _measure_text_width(word, font)

        if not current_line:
            # Starting a new line
            if word_width <= max_width:
                current_line = word
            else:
                # Word is too long - break it with hyphens
                broken = _break_long_word(word, font, max_width, hyphen_width)
                if len(broken) > 1:
                    # Add all complete lines except the last
                    lines.extend(broken[:-1])
                    # Last fragment becomes current line
                    current_line = broken[-1]
                else:
                    current_line = broken[0]
        else:
            test_line = current_line + " " + word
            if _measure_text_width(test_line, font) <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                if word_width <= max_width:
                    current_line = word
                else:
                    # Word is too long - break it
                    broken = _break_long_word(word, font, max_width, hyphen_width)
                    if len(broken) > 1:
                        lines.extend(broken[:-1])
                        current_line = broken[-1]
                    else:
                        current_line = broken[0]

    # Don't forget the last line
    if current_line:
        lines.append(current_line)

    return lines if lines else [""]


def check_text_overflow(
    text: str,
    font_name: str,
    font_size_pt: int,
    width_inches: float,
    height_inches: float,
    line_spacing: float = 1.2,
) -> dict:
    """Check if text will overflow placeholder bounds.

    Measures text dimensions against placeholder area using actual font metrics.
    Reports overflow status without modifying content.

    Args:
        text: The text content to measure.
        font_name: Font family name (e.g. 'Aptos', 'Helvetica').
        font_size_pt: Font size in points.
        width_inches: Placeholder width in inches.
        height_inches: Placeholder height in inches.
        line_spacing: Line spacing multiplier (default 1.2).

    Returns:
        Dict with overflow analysis:
        - overflows: bool or None (None if measurement impossible)
        - lines_needed: int (number of wrapped lines)
        - lines_available: int (lines that fit in height)
        - pct_used: float (percentage of vertical space used)
        - font_exact: bool (whether requested font was found exactly)
        - font_used: str (path to font file used)
        - error: str (only present if measurement failed)
    """
    font_path, is_exact = find_font_path(font_name)

    if font_path is None:
        return {
            "overflows": None,
            "error": "font_not_found",
            "font_exact": False,
            "font_used": None,
        }

    font = ImageFont.truetype(font_path, font_size_pt)

    # Convert placeholder dimensions to points (1 inch = 72 points)
    max_width_pt = width_inches * 72
    max_height_pt = height_inches * 72

    # Process each paragraph (split by newlines) and wrap each one
    all_lines: list[str] = []
    for paragraph in text.split('\n'):
        wrapped = _wrap_text(paragraph, font, max_width_pt)
        all_lines.extend(wrapped)

    # Calculate line height from font metrics
    ascent, descent = font.getmetrics()
    line_height = (ascent + descent) * line_spacing

    # Calculate total text height
    total_height = len(all_lines) * line_height

    lines_available = max(1, int(max_height_pt / line_height))
    pct_used = (
        round(total_height / max_height_pt * 100, 1)
        if max_height_pt > 0
        else 999.0
    )

    return {
        "overflows": total_height > max_height_pt,
        "lines_needed": len(all_lines),
        "lines_available": lines_available,
        "pct_used": pct_used,
        "font_exact": is_exact,
        "font_used": font_path,
    }


# --- Rendering Pipeline ---


def _find_soffice() -> str | None:
    """Locate LibreOffice binary on the system.

    Checks 'soffice' first (macOS/Linux), then 'libreoffice' (some Linux distros).

    Returns:
        Full path to the soffice binary, or None if not found.
    """
    path = shutil.which("soffice")
    if path:
        return path
    path = shutil.which("libreoffice")
    if path:
        return path
    return None


def render_pptx_to_images(pptx_path: str, width: int = 1920) -> list[Image.Image]:
    """Convert a PPTX file to per-slide PNG images via PDF intermediate.

    Pipeline: PPTX -> PDF (LibreOffice headless) -> PNG (pdf2image/poppler)

    Uses an isolated LibreOffice user profile to prevent lock file conflicts
    when multiple processes render concurrently.

    Args:
        pptx_path: Path to the PPTX file to render.
        width: Target width in pixels for each slide image. Height is
               calculated to preserve aspect ratio. Defaults to 1920.

    Returns:
        List of PIL Image objects, one per slide.

    Raises:
        RuntimeError: If LibreOffice is not installed or conversion fails.
        FileNotFoundError: If pptx_path does not exist.
    """
    pptx_path = Path(pptx_path).resolve()
    if not pptx_path.exists():
        raise FileNotFoundError(f"PPTX file not found: {pptx_path}")

    soffice = _find_soffice()
    if soffice is None:
        raise RuntimeError(
            "LibreOffice (soffice) not found. "
            "Install: brew install --cask libreoffice"
        )

    # Create temp working directory alongside the PPTX
    pdf_dir = pptx_path.parent / ".visual-tmp"
    pdf_dir.mkdir(exist_ok=True)

    # Use isolated user profile to prevent lock file conflicts
    pid = os.getpid()
    profile_dir = f"/tmp/lo-profile-{pid}"
    user_install = f"file://{profile_dir}"

    try:
        # Convert PPTX to PDF via LibreOffice headless
        cmd = [
            soffice,
            "--headless",
            f"-env:UserInstallation={user_install}",
            "--convert-to", "pdf",
            "--outdir", str(pdf_dir),
            str(pptx_path),
        ]

        result = subprocess.run(
            cmd,
            timeout=120,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"LibreOffice PDF conversion failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )

        # Locate the output PDF
        pdf_path = pdf_dir / (pptx_path.stem + ".pdf")
        if not pdf_path.exists():
            raise RuntimeError(
                f"PDF not created at expected path: {pdf_path}. "
                f"LibreOffice stdout: {result.stdout.strip()}"
            )

        # Convert PDF pages to images at target width
        images = convert_from_path(str(pdf_path), size=(width, None))

        return images

    finally:
        # Cleanup: remove temp PDF directory
        if pdf_dir.exists():
            shutil.rmtree(pdf_dir, ignore_errors=True)

        # Cleanup: remove LibreOffice profile directory
        profile_path = Path(profile_dir)
        if profile_path.exists():
            shutil.rmtree(profile_path, ignore_errors=True)


def create_composite_grid(
    images: list[Image.Image],
    output_path: str,
    cols: int = 4,
    padding: int = 10,
) -> None:
    """Create a composite grid JPEG from a list of slide images.

    Arranges slide thumbnails in a grid layout with padding and saves
    as a JPEG. Useful for quick visual review of all slides at once.

    Args:
        images: List of PIL Image objects to arrange in grid.
        output_path: File path for the output JPEG.
        cols: Number of columns in the grid. Defaults to 4.
        padding: Pixel padding between thumbnails and edges. Defaults to 10.
    """
    if not images:
        return

    # Calculate thumbnail dimensions
    thumb_w = (1920 - (cols + 1) * padding) // cols
    # Preserve aspect ratio from first image
    orig_w, orig_h = images[0].size
    thumb_h = int(thumb_w * (orig_h / orig_w))

    # Calculate grid dimensions
    n = len(images)
    rows = math.ceil(n / cols)
    grid_w = cols * thumb_w + (cols + 1) * padding
    grid_h = rows * thumb_h + (rows + 1) * padding

    # Create white canvas
    composite = Image.new("RGB", (grid_w, grid_h), (255, 255, 255))

    # Paste resized thumbnails at grid positions
    for idx, img in enumerate(images):
        row = idx // cols
        col = idx % cols
        x = padding + col * (thumb_w + padding)
        y = padding + row * (thumb_h + padding)

        thumb = img.resize((thumb_w, thumb_h), Image.LANCZOS)
        composite.paste(thumb, (x, y))

    # Ensure output directory exists
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save as JPEG quality=85
    composite.save(str(output_path), "JPEG", quality=85)


# --- Visual Diff ---


def compute_visual_diff(
    img_a: Image.Image, img_b: Image.Image, threshold: int = 20
) -> dict:
    """Compare two slide images pixel-by-pixel with anti-aliasing tolerance.

    Uses per-pixel max-channel absolute difference to identify significant
    visual changes between two rendered slides. The threshold parameter
    filters out anti-aliasing noise (sub-pixel rendering differences).

    Args:
        img_a: First image (e.g. template baseline).
        img_b: Second image (e.g. populated slide).
        threshold: Per-pixel intensity difference below which changes are
                   considered noise (default 20 handles anti-aliasing).

    Returns:
        Dict with:
        - score: float (percentage of pixels significantly different)
        - mean_diff: float (average pixel intensity difference)
        - exceeds_threshold: bool (True if score > 5.0%)
        - error: str (only present on size mismatch)
    """
    arr_a = np.array(img_a.convert("RGB"), dtype=np.float32)
    arr_b = np.array(img_b.convert("RGB"), dtype=np.float32)

    if arr_a.shape != arr_b.shape:
        return {
            "score": 100.0,
            "mean_diff": 255.0,
            "exceeds_threshold": True,
            "error": "size_mismatch",
        }

    # Per-pixel max-channel absolute difference
    pixel_diff = np.abs(arr_a - arr_b).max(axis=2)

    # Identify significant pixels (above anti-aliasing noise threshold)
    significant = pixel_diff > threshold

    score = round(float(significant.sum()) / significant.size * 100, 2)
    mean_diff = round(float(pixel_diff.mean()), 2)
    exceeds_threshold = score > 5.0

    return {
        "score": score,
        "mean_diff": mean_diff,
        "exceeds_threshold": exceeds_threshold,
    }


def validate_visual(
    pptx_path: str,
    template_path: str,
    layout_plan: dict,
    output_dir: str,
) -> dict:
    """Orchestrate visual validation: render, composite, diff against template.

    Renders the populated PPTX to per-slide images, creates a composite
    thumbnail grid, renders the template baseline, and computes visual
    diffs between each populated slide and its corresponding template layout.

    This function never raises — rendering or diff failures are reported
    in the return dict but never block PPTX output.

    Args:
        pptx_path: Path to the generated PPTX file.
        template_path: Path to the template PPTX (for baseline rendering).
        layout_plan: The layout plan dict (has 'slides' with layout indices).
        output_dir: Directory where composite JPEG will be saved.

    Returns:
        Dict with:
        - composite_path: str (path to saved thumbnail grid JPEG)
        - slide_count: int (number of slides rendered)
        - diffs: list[dict] (per-slide diff results)
        - warnings: list[str] (only slides exceeding 5% threshold)
        - error: str (only present if rendering failed entirely)
    """
    try:
        # Render populated PPTX to images
        populated_images = render_pptx_to_images(pptx_path)

        # Create composite grid alongside the PPTX
        pptx_stem = Path(pptx_path).stem
        composite_path = Path(output_dir) / f"{pptx_stem}.jpg"
        create_composite_grid(populated_images, str(composite_path))

        # Render template baseline for comparison
        template_images = render_pptx_to_images(template_path)

        # Map each slide to its template baseline by layout index
        slides_data = layout_plan.get("slides", [])
        diffs = []
        warnings = []

        for i, slide_info in enumerate(slides_data):
            if i >= len(populated_images):
                break

            layout_index = slide_info.get("layout", {}).get("index", 0)

            # Get baseline image for this layout index
            if layout_index < len(template_images):
                baseline_img = template_images[layout_index]
            else:
                # Layout index out of range — skip diff for this slide
                diffs.append({
                    "slide": i + 1,
                    "score": 0.0,
                    "exceeds_threshold": False,
                    "note": "baseline_unavailable",
                })
                continue

            diff = compute_visual_diff(baseline_img, populated_images[i])
            diffs.append({
                "slide": i + 1,
                "score": diff["score"],
                "exceeds_threshold": diff["exceeds_threshold"],
            })

            if diff["exceeds_threshold"]:
                warnings.append(
                    f"Slide {i + 1}: visual diff score {diff['score']}% "
                    f"(threshold 5%) \u2014 possible layout issue"
                )

        return {
            "composite_path": str(composite_path),
            "slide_count": len(populated_images),
            "diffs": diffs,
            "warnings": warnings,
        }

    except Exception as e:
        # Never block PPTX output — report error and return gracefully
        return {
            "error": str(e),
            "composite_path": None,
            "slide_count": 0,
            "diffs": [],
            "warnings": [],
        }
