"""Font fallback chain utilities.

Provides a consistent font fallback mechanism across the PPTX generation pipeline.
The fallback chain ensures text rendering works even when preferred fonts are unavailable:

    Aptos → Calibri → Arial → sans-serif

This module handles:
- Font availability detection on the system
- Fallback chain traversal to find available fonts
- Font name resolution for both measurement and PPTX generation

Usage:
    from font_fallback import get_available_font, FONT_FALLBACK_CHAIN

    # Get first available font from fallback chain
    font_name = get_available_font("Aptos")  # Returns "Aptos" if available, else fallback

    # Get font for measurement (with path)
    font_name, font_path = get_available_font_with_path("Aptos")
"""

import os
import platform
import subprocess
from functools import lru_cache
from pathlib import Path

# Default fallback chain: Aptos → Calibri → Arial → sans-serif
# Aptos: Modern Microsoft font (Office 2024+)
# Calibri: Standard Microsoft font (Office 2007+)
# Arial: Universal cross-platform font
# sans-serif: Generic fallback (system will choose)
FONT_FALLBACK_CHAIN = ["Aptos", "Calibri", "Arial", "sans-serif"]

# Common sans-serif fonts to try when "sans-serif" is requested
SANS_SERIF_FONTS = [
    "Helvetica",       # macOS standard
    "DejaVu Sans",     # Linux standard
    "Liberation Sans", # Linux alternative
    "Nimbus Sans L",   # Linux alternative
    "FreeSans",        # Linux alternative
]


@lru_cache(maxsize=32)
def _find_font_file(font_name: str) -> tuple[str | None, bool]:
    """Find font file path on system (cached).

    Searches platform-specific font directories for a matching font file,
    then falls back to fc-match if available.

    Args:
        font_name: Font family name to search for (e.g. 'Aptos', 'Helvetica').

    Returns:
        Tuple of (path, is_exact_match). Path is None if font not found.
        is_exact_match is True only when the font_name appears in the filename.
    """
    system = platform.system()

    if system == "Darwin":
        search_dirs = [
            "/System/Library/Fonts",
            "/Library/Fonts",
            os.path.expanduser("~/Library/Fonts"),
        ]
    elif system == "Linux":
        search_dirs = [
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            os.path.expanduser("~/.local/share/fonts"),
            os.path.expanduser("~/.fonts"),
        ]
    elif system == "Windows":
        search_dirs = [
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft\\Windows\\Fonts"),
        ]
    else:
        search_dirs = []

    font_name_lower = font_name.lower()

    # Search font directories for matching files
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for dirpath, _dirnames, filenames in os.walk(search_dir):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in (".ttf", ".otf", ".ttc"):
                    continue
                if font_name_lower in filename.lower():
                    return (os.path.join(dirpath, filename), True)

    # Fallback: try fc-match (Linux/macOS with fontconfig)
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}", font_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            fc_path = result.stdout.strip()
            if os.path.isfile(fc_path):
                stem = Path(fc_path).stem.lower()
                is_exact = font_name_lower in stem
                return (fc_path, is_exact)
    except FileNotFoundError:
        # fc-match not installed
        pass
    except subprocess.TimeoutExpired:
        pass

    return (None, False)


@lru_cache(maxsize=32)
def is_font_available(font_name: str) -> bool:
    """Check if a font is available on the system.

    Args:
        font_name: Font family name to check.

    Returns:
        True if the font is available, False otherwise.
    """
    if font_name.lower() == "sans-serif":
        # Generic sans-serif is always "available" conceptually
        # The actual font will be resolved during rendering
        return True

    path, _ = _find_font_file(font_name)
    return path is not None


def get_available_font(preferred: str, fallback_chain: list[str] | None = None) -> str:
    """Get the first available font from the fallback chain.

    Starts with the preferred font and traverses the fallback chain until
    an available font is found. Falls back to "Arial" if nothing else works.

    Args:
        preferred: The preferred font name to try first.
        fallback_chain: Optional custom fallback chain. Defaults to FONT_FALLBACK_CHAIN.

    Returns:
        The name of the first available font from the chain.
    """
    if fallback_chain is None:
        fallback_chain = FONT_FALLBACK_CHAIN

    # Build the full chain starting with preferred font
    chain = [preferred] if preferred not in fallback_chain else []
    chain.extend(fallback_chain)

    for font_name in chain:
        if is_font_available(font_name):
            return font_name

    # Ultimate fallback - Arial should be available on most systems
    return "Arial"


def get_available_font_with_path(
    preferred: str, fallback_chain: list[str] | None = None
) -> tuple[str, str | None]:
    """Get the first available font with its file path.

    Similar to get_available_font but also returns the font file path,
    which is needed for font measurement operations.

    Args:
        preferred: The preferred font name to try first.
        fallback_chain: Optional custom fallback chain. Defaults to FONT_FALLBACK_CHAIN.

    Returns:
        Tuple of (font_name, font_path). font_path may be None for generic
        fonts like "sans-serif".
    """
    if fallback_chain is None:
        fallback_chain = FONT_FALLBACK_CHAIN

    # Build the full chain starting with preferred font
    chain = [preferred] if preferred not in fallback_chain else []
    chain.extend(fallback_chain)

    for font_name in chain:
        if font_name.lower() == "sans-serif":
            # For sans-serif, try to find an actual font file
            for sans_font in SANS_SERIF_FONTS:
                path, _ = _find_font_file(sans_font)
                if path:
                    return (sans_font, path)
            # If no sans-serif font found, continue to next in chain
            continue

        path, _ = _find_font_file(font_name)
        if path:
            return (font_name, path)

    # Ultimate fallback - try common fonts
    for fallback in ["Helvetica", "DejaVu Sans", "Arial"]:
        path, _ = _find_font_file(fallback)
        if path:
            return (fallback, path)

    return ("Arial", None)


def resolve_font_for_pptx(font_name: str) -> str:
    """Resolve a font name for PPTX generation.

    For PPTX files, we want to use the actual font name (not a file path)
    since PowerPoint will resolve the font on the target system. However,
    we should still apply the fallback chain for measurement consistency.

    Args:
        font_name: The requested font name.

    Returns:
        The font name to use in the PPTX file.
    """
    # For generic sans-serif, use Arial (widely available)
    if font_name.lower() == "sans-serif":
        return "Arial"

    return get_available_font(font_name)


def get_measurement_font(font_name: str) -> tuple[str, str | None]:
    """Get a font suitable for text measurement.

    Text measurement requires an actual font file. This function resolves
    the font name to a file path, applying fallbacks as needed.

    Args:
        font_name: The requested font name.

    Returns:
        Tuple of (font_name, font_path). font_path is the path to the
        font file to use for measurement, or None if no font file found.
    """
    return get_available_font_with_path(font_name)


def clear_font_cache() -> None:
    """Clear the font availability cache.

    Call this if fonts are installed/removed during runtime and you need
    to re-detect font availability.
    """
    _find_font_file.cache_clear()
    is_font_available.cache_clear()


def check_font_availability(
    fonts: list[str] | None = None,
    *,
    log_fallbacks: bool = True,
    logger=None,
) -> dict:
    """Check font availability before generation and log fallback usage.

    Performs a preflight check of font availability, returning detailed
    information about which fonts are available and which will use fallbacks.
    Optionally logs warnings when fallback fonts will be used.

    Args:
        fonts: List of font names to check. If None, checks the default
               fallback chain (Aptos, Calibri, Arial).
        log_fallbacks: If True, log warnings when fallbacks are used.
        logger: Optional logger instance. If None, uses print to stderr.

    Returns:
        Dict with structure:
        {
            'available': ['FontA', 'FontB'],  # Fonts available on system
            'fallbacks': {  # Fonts that will use fallbacks
                'RequestedFont': {
                    'resolved_to': 'ActualFont',
                    'path': '/path/to/font.ttf' or None
                }
            },
            'unavailable': ['FontX'],  # Fonts with no resolution (rare)
            'summary': 'All fonts available' or 'N font(s) using fallbacks'
        }
    """
    import sys

    if fonts is None:
        fonts = [f for f in FONT_FALLBACK_CHAIN if f != "sans-serif"]

    # Deduplicate while preserving order
    seen = set()
    unique_fonts = []
    for f in fonts:
        if f not in seen:
            seen.add(f)
            unique_fonts.append(f)

    available = []
    fallbacks = {}
    unavailable = []

    for font_name in unique_fonts:
        if is_font_available(font_name):
            available.append(font_name)
        else:
            # Font not directly available, find what it resolves to
            resolved_name, resolved_path = get_available_font_with_path(font_name)

            if resolved_name != font_name:
                fallbacks[font_name] = {
                    'resolved_to': resolved_name,
                    'path': resolved_path,
                }
            elif resolved_path is None:
                # No font file found at all (very rare)
                unavailable.append(font_name)
            else:
                # Font resolved to itself with path (shouldn't happen normally)
                available.append(font_name)

    # Build summary
    if not fallbacks and not unavailable:
        summary = "All fonts available"
    elif fallbacks and not unavailable:
        summary = f"{len(fallbacks)} font(s) using fallbacks"
    elif unavailable:
        summary = f"{len(unavailable)} font(s) unavailable, {len(fallbacks)} using fallbacks"
    else:
        summary = f"{len(unavailable)} font(s) unavailable"

    # Log fallback usage if requested
    if log_fallbacks and (fallbacks or unavailable):
        def _log(msg: str):
            if logger:
                logger.warning(msg)
            else:
                print(msg, file=sys.stderr)

        for font_name, info in fallbacks.items():
            _log(f"Font '{font_name}' not found, using fallback: {info['resolved_to']}")

        for font_name in unavailable:
            _log(f"Font '{font_name}' not found and no fallback available")

    return {
        'available': available,
        'fallbacks': fallbacks,
        'unavailable': unavailable,
        'summary': summary,
    }


if __name__ == "__main__":
    """Self-tests for font_fallback module."""
    print("Font Fallback Chain Self-Tests")
    print("=" * 50)

    # Test 1: Check fallback chain fonts
    print("\n1. Testing fallback chain fonts:")
    for font in FONT_FALLBACK_CHAIN:
        available = is_font_available(font)
        path, exact = _find_font_file(font) if font != "sans-serif" else (None, False)
        status = "✓" if available else "✗"
        path_info = f" ({path})" if path else ""
        print(f"   {status} {font}: {'available' if available else 'not found'}{path_info}")

    # Test 2: get_available_font
    print("\n2. Testing get_available_font():")
    result = get_available_font("Aptos")
    print(f"   Preferred 'Aptos' → {result}")

    result = get_available_font("NonExistentFont123")
    print(f"   Preferred 'NonExistentFont123' → {result}")

    # Test 3: get_available_font_with_path
    print("\n3. Testing get_available_font_with_path():")
    name, path = get_available_font_with_path("Aptos")
    print(f"   'Aptos' → {name} ({path})")

    name, path = get_available_font_with_path("sans-serif")
    print(f"   'sans-serif' → {name} ({path})")

    # Test 4: resolve_font_for_pptx
    print("\n4. Testing resolve_font_for_pptx():")
    print(f"   'Aptos' → {resolve_font_for_pptx('Aptos')}")
    print(f"   'sans-serif' → {resolve_font_for_pptx('sans-serif')}")

    # Test 5: get_measurement_font
    print("\n5. Testing get_measurement_font():")
    name, path = get_measurement_font("Aptos")
    print(f"   'Aptos' → {name} (path: {path is not None})")

    print("\n" + "=" * 50)
    print("Tests complete.")
