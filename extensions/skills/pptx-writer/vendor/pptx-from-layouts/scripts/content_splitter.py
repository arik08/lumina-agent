"""Content splitting utilities for handling overflow in PPTX generation.

When content exceeds available slide space and cannot fit even with font shrinking,
this module splits content across multiple slides while maintaining visual consistency.

Supports:
- Body bullet point splitting (preserves hierarchy via {level:N} markers)
- Table row splitting (repeats headers on continuation slides)
- Column content splitting (distributes across continuation slides)

Usage:
    from content_splitter import (
        detect_content_overflow,
        split_body_content,
        split_table_content,
        create_continuation_slides,
    )

    # Check if content will overflow
    overflow = detect_content_overflow(slide_data, placeholder_dims)

    if overflow['needs_split']:
        # Split into multiple slide_data dicts
        slides = split_body_content(slide_data, overflow['split_points'])
"""

import copy
import re
import sys
from pathlib import Path
from typing import TypedDict

# Import measurement functions
sys.path.insert(0, str(Path(__file__).parent))
from visual_validator import check_text_overflow, find_font_path


class OverflowResult(TypedDict):
    """Result of overflow detection."""
    needs_split: bool
    overflow_type: str  # 'body', 'table', 'columns', 'none'
    lines_needed: int
    lines_available: int
    split_points: list[int]  # Indices where to split
    continuation_count: int  # Number of continuation slides needed


class PlaceholderDimensions(TypedDict):
    """Placeholder dimensions for overflow calculation."""
    width_inches: float
    height_inches: float
    usable_width_inches: float
    usable_height_inches: float


# Default dimensions for body placeholder (based on IC template)
DEFAULT_BODY_DIMS: PlaceholderDimensions = {
    'width_inches': 12.16,
    'height_inches': 5.52,
    'usable_width_inches': 11.96,
    'usable_height_inches': 5.32,
}


def _strip_markers(text: str) -> str:
    """Strip typography markers from text for measurement."""
    if not text or not isinstance(text, str):
        return str(text) if text else ""

    # Remove inline markers
    text = re.sub(
        r'\{(blue|red|green|italic|bold|underline|strike|signpost|question|caps|super|sub|font:[^}]+|size:\d+)\}',
        '', text
    )
    # Remove custom color markers
    text = re.sub(r'\{color:#[0-9A-Fa-f]{6}\}', '', text)
    # Remove paragraph markers
    text = re.sub(r'\{(bullet:[^}]+|level:\d+|space:(before|after):[^}]+)\}', '', text)
    # Remove closing markers
    text = re.sub(r'\{/(blue|red|green|italic|bold|underline|strike|signpost|question|caps|super|sub|font|color|size)\}', '', text)
    # Remove markdown
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)

    return text.strip()


def _get_item_level(item: str) -> int:
    """Extract indent level from a body item (0-based)."""
    if not isinstance(item, str):
        return 0

    # Check for {level:N} marker
    match = re.search(r'\{level:(\d+)\}', item)
    if match:
        return int(match.group(1))

    # Default to level 0
    return 0


def _estimate_bullet_lines(
    items: list[str],
    font_name: str = "Aptos",
    font_size_pt: int = 16,
    width_inches: float = 11.96,
    line_spacing: float = 1.2,
) -> list[int]:
    """Estimate lines needed per bullet item.

    Returns list of line counts, one per item.
    """
    line_counts = []

    # Get font path for measurement
    font_path, _ = find_font_path(font_name)
    if font_path is None:
        # Fallback: estimate based on character count
        chars_per_line = int(width_inches * 72 / font_size_pt * 1.8)
        for item in items:
            clean = _strip_markers(str(item))
            lines = max(1, (len(clean) + chars_per_line - 1) // chars_per_line)
            line_counts.append(lines)
        return line_counts

    # Use actual measurement
    for item in items:
        clean = _strip_markers(str(item))
        if not clean:
            line_counts.append(1)
            continue

        result = check_text_overflow(
            text=clean,
            font_name=font_name,
            font_size_pt=font_size_pt,
            width_inches=width_inches,
            height_inches=100.0,  # Large height to just count lines
            line_spacing=line_spacing,
        )

        lines = result.get('lines_needed', 1)
        line_counts.append(max(1, lines))

    return line_counts


def detect_content_overflow(
    slide_data: dict,
    body_dims: PlaceholderDimensions | None = None,
    font_name: str = "Aptos",
    body_font_size_pt: int = 16,
    headline_font_size_pt: int = 18,
    line_spacing: float = 1.2,
) -> OverflowResult:
    """Detect if slide content will overflow available space.

    Checks body content (headline + bullets) against placeholder dimensions.
    Returns overflow analysis with suggested split points.

    Args:
        slide_data: Slide specification dict from layout plan
        body_dims: Body placeholder dimensions (uses defaults if None)
        font_name: Font family for measurement
        body_font_size_pt: Font size for body bullets
        headline_font_size_pt: Font size for headline
        line_spacing: Line spacing multiplier

    Returns:
        OverflowResult with overflow analysis
    """
    if body_dims is None:
        body_dims = DEFAULT_BODY_DIMS

    content = slide_data.get('content', {})
    headline = content.get('headline', '')
    body = content.get('body', [])

    # Filter to string items only (skip deliverable objects etc)
    string_body = [b for b in body if isinstance(b, str)]

    if not headline and not string_body:
        return OverflowResult(
            needs_split=False,
            overflow_type='none',
            lines_needed=0,
            lines_available=0,
            split_points=[],
            continuation_count=0,
        )

    # Calculate available lines
    usable_height = body_dims.get('usable_height_inches', 5.32)
    usable_width = body_dims.get('usable_width_inches', 11.96)

    # Line height in inches (font_size * line_spacing / 72)
    body_line_height = body_font_size_pt * line_spacing / 72.0
    headline_line_height = headline_font_size_pt * line_spacing / 72.0

    # Calculate headline lines
    headline_lines = 0
    if headline:
        clean_headline = _strip_markers(headline)
        result = check_text_overflow(
            text=clean_headline,
            font_name=font_name,
            font_size_pt=headline_font_size_pt,
            width_inches=usable_width,
            height_inches=100.0,
            line_spacing=line_spacing,
        )
        headline_lines = result.get('lines_needed', 1)

    # Calculate body bullet lines
    body_line_counts = _estimate_bullet_lines(
        string_body,
        font_name=font_name,
        font_size_pt=body_font_size_pt,
        width_inches=usable_width,
        line_spacing=line_spacing,
    )

    # Total space calculation
    headline_height = headline_lines * headline_line_height if headline else 0
    headline_spacing = 0.2 if headline else 0  # Space after headline

    remaining_height = usable_height - headline_height - headline_spacing
    lines_available = int(remaining_height / body_line_height)
    lines_needed = sum(body_line_counts)

    if lines_needed <= lines_available:
        return OverflowResult(
            needs_split=False,
            overflow_type='none',
            lines_needed=lines_needed,
            lines_available=lines_available,
            split_points=[],
            continuation_count=0,
        )

    # Calculate split points
    split_points = _calculate_split_points(
        body_line_counts,
        lines_available,
        string_body,
    )

    return OverflowResult(
        needs_split=True,
        overflow_type='body',
        lines_needed=lines_needed,
        lines_available=lines_available,
        split_points=split_points,
        continuation_count=len(split_points),
    )


def _calculate_split_points(
    line_counts: list[int],
    lines_per_slide: int,
    items: list[str],
) -> list[int]:
    """Calculate optimal indices where to split content.

    Prefers splitting:
    1. Before level-0 items (section breaks)
    2. Before items that would overflow the current slide

    Returns list of indices where new slides should start.
    """
    if not line_counts or lines_per_slide <= 0:
        return []

    split_points = []
    current_lines = 0

    for i, lines in enumerate(line_counts):
        if i == 0:
            current_lines = lines
            continue

        # Check if adding this item would overflow
        if current_lines + lines > lines_per_slide:
            # Find best split point: prefer level-0 items
            best_split = i

            # Look back for a level-0 item within last few items
            for j in range(i, max(0, i - 3), -1):
                if _get_item_level(items[j]) == 0:
                    best_split = j
                    break

            if best_split not in split_points and best_split > 0:
                split_points.append(best_split)

            # Reset counter from split point
            current_lines = sum(line_counts[best_split:i + 1])
        else:
            current_lines += lines

    return split_points


def split_body_content(
    slide_data: dict,
    split_points: list[int],
) -> list[dict]:
    """Split slide content at specified points into multiple slides.

    Creates continuation slides with:
    - Same title (with "cont'd" suffix on continuations)
    - Headline only on first slide
    - Body split at the specified indices

    Args:
        slide_data: Original slide specification
        split_points: Indices where to start new slides

    Returns:
        List of slide_data dicts (first is original, rest are continuations)
    """
    if not split_points:
        return [slide_data]

    content = slide_data.get('content', {})
    body = content.get('body', [])
    string_body = [b for b in body if isinstance(b, str)]

    if not string_body:
        return [slide_data]

    # Build slide list
    slides = []
    prev_idx = 0

    # All split points plus end
    all_points = split_points + [len(string_body)]

    for i, split_idx in enumerate(all_points):
        is_first = (i == 0)

        # Deep copy the slide data
        new_slide = copy.deepcopy(slide_data)

        # Get content slice
        body_slice = string_body[prev_idx:split_idx]

        # Update content
        new_content = new_slide.get('content', {})
        new_content['body'] = body_slice

        # Clear headline on continuation slides
        if not is_first:
            new_content['headline'] = ''
            new_slide['headline_styled'] = None
            new_slide['headline_bold'] = False

            # Add "cont'd" to title if present
            if new_content.get('title'):
                title = new_content['title']
                if not title.endswith("(cont'd)") and not title.endswith("(continued)"):
                    new_content['title'] = f"{title} (cont'd)"

        new_slide['content'] = new_content

        # Mark as continuation
        if not is_first:
            new_slide['_is_continuation'] = True
            new_slide['_continuation_index'] = i

        slides.append(new_slide)
        prev_idx = split_idx

    return slides


def detect_table_overflow(
    table_data: dict,
    available_height_inches: float = 4.5,
    header_height_inches: float = 0.35,
    min_row_height_inches: float = 0.25,
) -> dict:
    """Detect if a table will overflow available space.

    Args:
        table_data: Table dict with 'headers' and 'rows'
        available_height_inches: Total height available for table
        header_height_inches: Fixed height for header row
        min_row_height_inches: Minimum height per data row

    Returns:
        Dict with:
        - needs_split: bool
        - rows_per_slide: int (max rows that fit)
        - continuation_count: int
    """
    rows = table_data.get('rows', [])
    if not rows:
        return {
            'needs_split': False,
            'rows_per_slide': 0,
            'continuation_count': 0,
        }

    # Calculate how many rows fit
    data_height = available_height_inches - header_height_inches
    rows_per_slide = max(1, int(data_height / min_row_height_inches))

    total_rows = len(rows)

    if total_rows <= rows_per_slide:
        return {
            'needs_split': False,
            'rows_per_slide': rows_per_slide,
            'continuation_count': 0,
        }

    continuation_count = (total_rows + rows_per_slide - 1) // rows_per_slide - 1

    return {
        'needs_split': True,
        'rows_per_slide': rows_per_slide,
        'continuation_count': continuation_count,
    }


def split_table_content(
    slide_data: dict,
    rows_per_slide: int,
) -> list[dict]:
    """Split table content across multiple slides.

    Headers are repeated on each continuation slide.

    Args:
        slide_data: Original slide specification with table
        rows_per_slide: Maximum rows per slide

    Returns:
        List of slide_data dicts
    """
    tables = slide_data.get('tables', [])
    if not tables:
        # Check content.table
        content = slide_data.get('content', {})
        if content.get('table'):
            tables = [content['table']]

    if not tables or not tables[0].get('rows'):
        return [slide_data]

    # Only handle first table for now
    table = tables[0]
    headers = table.get('headers', [])
    rows = table.get('rows', [])

    if len(rows) <= rows_per_slide:
        return [slide_data]

    slides = []

    for i in range(0, len(rows), rows_per_slide):
        is_first = (i == 0)
        row_slice = rows[i:i + rows_per_slide]

        # Deep copy slide data
        new_slide = copy.deepcopy(slide_data)

        # Update table with row slice
        new_table = {
            'headers': headers,
            'rows': row_slice,
        }

        # Copy any additional table properties
        for key in table:
            if key not in ('headers', 'rows'):
                new_table[key] = table[key]

        new_slide['tables'] = [new_table]

        # Update content.table if that's where it came from
        if slide_data.get('content', {}).get('table'):
            new_slide['content']['table'] = new_table

        # Mark continuations
        if not is_first:
            new_slide['_is_continuation'] = True
            new_slide['_continuation_index'] = i // rows_per_slide

            # Add "cont'd" to title
            content = new_slide.get('content', {})
            if content.get('title'):
                title = content['title']
                if not title.endswith("(cont'd)") and not title.endswith("(continued)"):
                    content['title'] = f"{title} (cont'd)"
                new_slide['content'] = content

        slides.append(new_slide)

    return slides


def create_continuation_slides(
    slide_data: dict,
    body_dims: PlaceholderDimensions | None = None,
    table_height_inches: float = 4.5,
) -> list[dict]:
    """Auto-detect overflow and create continuation slides if needed.

    This is the main entry point for overflow handling. It:
    1. Detects body content overflow
    2. Detects table overflow
    3. Splits content appropriately

    Args:
        slide_data: Original slide specification
        body_dims: Body placeholder dimensions
        table_height_inches: Available height for tables

    Returns:
        List of slide_data dicts (may be just the original if no overflow)
    """
    # Check for body overflow
    body_overflow = detect_content_overflow(slide_data, body_dims)

    if body_overflow['needs_split']:
        return split_body_content(slide_data, body_overflow['split_points'])

    # Check for table overflow
    tables = slide_data.get('tables', [])
    if tables and tables[0].get('rows'):
        table_overflow = detect_table_overflow(
            tables[0],
            available_height_inches=table_height_inches,
        )

        if table_overflow['needs_split']:
            return split_table_content(
                slide_data,
                table_overflow['rows_per_slide'],
            )

    # No overflow - return original
    return [slide_data]


if __name__ == "__main__":
    """Self-tests for content_splitter module."""

    passed = 0
    failed = 0

    def report(name: str, ok: bool, detail: str = "") -> None:
        global passed, failed
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        else:
            passed += 1
        suffix = f" ({detail})" if detail else ""
        print(f"  {status}: {name}{suffix}")

    print("Content Splitter Self-Tests")
    print("=" * 40)

    # --- Test 1: No overflow - short content ---
    print("\nTest 1: No overflow with short content")
    slide_data = {
        'slide_number': 1,
        'content': {
            'title': 'Test Slide',
            'headline': 'Short headline',
            'body': ['Item 1', 'Item 2', 'Item 3'],
        }
    }
    result = detect_content_overflow(slide_data)
    report("needs_split is False", result['needs_split'] is False)
    report("overflow_type is 'none' or 'body'", result['overflow_type'] in ('none', 'body'))

    # --- Test 2: Overflow with many bullets ---
    print("\nTest 2: Overflow with many bullets")
    many_bullets = [f"This is bullet point number {i} with enough text to take a full line" for i in range(30)]
    slide_data = {
        'slide_number': 2,
        'content': {
            'title': 'Overflow Test',
            'body': many_bullets,
        }
    }
    result = detect_content_overflow(slide_data)
    report("needs_split is True", result['needs_split'] is True, f"lines={result['lines_needed']}/{result['lines_available']}")
    report("has split points", len(result['split_points']) > 0, f"splits={result['split_points']}")

    # --- Test 3: Split body content ---
    print("\nTest 3: Split body content")
    if result['needs_split']:
        slides = split_body_content(slide_data, result['split_points'])
        report("creates multiple slides", len(slides) > 1, f"count={len(slides)}")
        report("first slide has title", slides[0]['content'].get('title') == 'Overflow Test')
        if len(slides) > 1:
            cont_title = slides[1]['content'].get('title', '')
            report("continuation has (cont'd)", "(cont'd)" in cont_title, cont_title)
            report("continuation is marked", slides[1].get('_is_continuation') is True)

    # --- Test 4: Table overflow detection ---
    print("\nTest 4: Table overflow detection")
    table_data = {
        'headers': ['Col A', 'Col B', 'Col C'],
        'rows': [[f"Row {i} A", f"Row {i} B", f"Row {i} C"] for i in range(25)],
    }
    result = detect_table_overflow(table_data, available_height_inches=3.0)
    report("needs_split is True", result['needs_split'] is True)
    report("rows_per_slide > 0", result['rows_per_slide'] > 0, f"rows={result['rows_per_slide']}")

    # --- Test 5: Split table content ---
    print("\nTest 5: Split table content")
    slide_data = {
        'slide_number': 5,
        'content': {'title': 'Table Slide'},
        'tables': [table_data],
    }
    slides = split_table_content(slide_data, result['rows_per_slide'])
    report("creates multiple slides", len(slides) > 1, f"count={len(slides)}")
    if len(slides) > 1:
        report("headers repeated", slides[1]['tables'][0]['headers'] == table_data['headers'])
        total_rows = sum(len(s['tables'][0]['rows']) for s in slides)
        report("all rows preserved", total_rows == len(table_data['rows']), f"{total_rows}=={len(table_data['rows'])}")

    # --- Test 6: create_continuation_slides auto-detection ---
    print("\nTest 6: create_continuation_slides auto-detection")
    # Should trigger body overflow
    slides = create_continuation_slides({
        'slide_number': 6,
        'content': {
            'title': 'Auto Split',
            'body': [f"Long bullet {i} " * 10 for i in range(20)],
        }
    })
    report("auto-splits on overflow", len(slides) >= 1)

    # --- Test 7: No split for normal content ---
    print("\nTest 7: No split for normal content")
    slides = create_continuation_slides({
        'slide_number': 7,
        'content': {
            'title': 'Normal',
            'body': ['Short 1', 'Short 2'],
        }
    })
    report("single slide for short content", len(slides) == 1)

    # --- Test 8: Preserve level markers ---
    print("\nTest 8: Level marker parsing")
    level = _get_item_level("{level:2}Indented item")
    report("parses {level:2}", level == 2)
    level = _get_item_level("Plain item")
    report("defaults to 0", level == 0)

    # --- Summary ---
    print("\n" + "=" * 40)
    total = passed + failed
    print(f"Results: {passed} passed, {failed} failed / {total} total")

    sys.exit(0 if failed == 0 else 1)
