#!/usr/bin/env python3
"""
preview_layout.py: Preview layout plan decisions before generation.

Shows a human-readable summary of layout decisions made by ingest.py,
including layout assignments, content routing, and potential issues.

Usage:
    python .claude/skills/slide-outline-to-layout/scripts/preview_layout.py layout_plan.json

Output:
    Markdown-formatted preview showing:
    - Layout assignments per slide
    - Content type routing
    - Placeholder mapping
    - Warnings for image placeholders and potential issues
"""

import argparse
import json
import sys
from pathlib import Path


def load_layout_plan(path: str) -> dict:
    """Load layout plan JSON."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def count_image_placeholders(slide: dict) -> int:
    """Count image placeholders in a slide."""
    count = 0

    # Check columns
    for col in slide.get('columns', []):
        if col.get('image_placeholder'):
            count += 1

    # Check cards
    for card in slide.get('cards', []):
        if card.get('image_placeholder'):
            count += 1

    # Check extras
    if slide.get('extras', {}).get('image_placeholder'):
        count += 1

    # Check background
    if slide.get('background'):
        count += 1

    return count


def format_content_summary(slide: dict) -> str:
    """Create a brief summary of slide content."""
    content = slide.get('content', {})
    parts = []

    title = content.get('title')
    if title:
        parts.append(f'Title: "{title[:40]}..."' if len(str(title)) > 40 else f'Title: "{title}"')

    headline = content.get('headline')
    if headline:
        parts.append(f'Headline: "{headline[:40]}..."' if len(str(headline)) > 40 else f'Headline: "{headline}"')

    body = content.get('body', [])
    if body:
        parts.append(f'{len(body)} bullet(s)')

    columns = slide.get('columns', [])
    if columns:
        parts.append(f'{len(columns)} column(s)')

    cards = slide.get('cards', [])
    if cards:
        parts.append(f'{len(cards)} card(s)')

    timeline = slide.get('timeline', []) or content.get('timeline', [])
    if timeline:
        parts.append(f'{len(timeline)} timeline entry(ies)')

    deliverables = slide.get('deliverables', []) or content.get('deliverables', [])
    if deliverables:
        parts.append(f'{len(deliverables)} deliverable(s)')

    tables = slide.get('tables', []) or content.get('tables', [])
    if tables:
        parts.append(f'{len(tables)} table(s)')
    elif content.get('table'):
        parts.append('1 table')

    return ', '.join(parts) if parts else '(no content)'


def generate_preview(layout_plan: dict) -> str:
    """Generate markdown preview of layout plan."""
    lines = []

    meta = layout_plan.get('_meta', {})
    slides = layout_plan.get('slides', [])

    # Header
    lines.append('# Layout Plan Preview')
    lines.append('')
    lines.append(f'**Version:** {meta.get("version", "unknown")}')
    lines.append(f'**Template:** {meta.get("template", "unknown")}')
    lines.append(f'**Total Slides:** {len(slides)}')
    lines.append('')

    # Warnings from meta
    warnings = meta.get('warnings', [])
    if warnings:
        lines.append('## Warnings')
        lines.append('')
        for w in warnings:
            lines.append(f'- {w}')
        lines.append('')

    # Slide summary table
    lines.append('## Slide Summary')
    lines.append('')
    lines.append('| Slide | Title | Layout | Content Type | Visual Type |')
    lines.append('|-------|-------|--------|--------------|-------------|')

    for slide in slides:
        num = slide.get('slide_number', '?')
        title = slide.get('content', {}).get('title', '')
        if title:
            title = title[:30] + '...' if len(str(title)) > 30 else title
        else:
            title = '-'

        layout = slide.get('layout', {})
        layout_name = layout.get('name', 'unknown')
        layout_index = layout.get('index', '?')

        content_type = slide.get('content_type', '-')
        visual_type = slide.get('visual_type', '-') or '-'

        lines.append(f'| {num} | {title} | {layout_name} ({layout_index}) | {content_type} | {visual_type} |')

    lines.append('')

    # Detailed slide breakdown
    lines.append('## Slide Details')
    lines.append('')

    total_image_placeholders = 0

    for slide in slides:
        num = slide.get('slide_number', '?')
        layout = slide.get('layout', {})
        layout_name = layout.get('name', 'unknown')
        layout_index = layout.get('index', '?')
        match_type = layout.get('match_type', 'unknown')

        content_type = slide.get('content_type', 'unknown')
        visual_type = slide.get('visual_type') or '-'

        title = slide.get('content', {}).get('title', '(no title)')

        lines.append(f'### Slide {num}: {title}')
        lines.append('')
        lines.append(f'- **Layout:** `{layout_name}` (index {layout_index})')
        lines.append(f'- **Match Type:** {match_type}')
        lines.append(f'- **Content Type:** {content_type}')
        lines.append(f'- **Visual Type:** {visual_type}')

        # Content summary
        content_summary = format_content_summary(slide)
        lines.append(f'- **Content:** {content_summary}')

        # Image placeholders
        img_count = count_image_placeholders(slide)
        if img_count > 0:
            total_image_placeholders += img_count
            lines.append(f'- **Image Placeholders:** {img_count} (will render as dashed boxes)')

        # Columns detail
        columns = slide.get('columns', [])
        if columns:
            lines.append('')
            lines.append('| Placeholder | Content |')
            lines.append('|-------------|---------|')
            for i, col in enumerate(columns, 1):
                header = col.get('header', '(no header)')
                body_count = len(col.get('body', []))
                has_img = 'yes' if col.get('image_placeholder') else 'no'
                lines.append(f'| Column {i} | {header} ({body_count} items, img: {has_img}) |')

        # Cards detail
        cards = slide.get('cards', [])
        if cards:
            lines.append('')
            lines.append('| Card | Title |')
            lines.append('|------|-------|')
            for i, card in enumerate(cards, 1):
                card_title = card.get('title', card.get('header', '(no title)'))
                lines.append(f'| {i} | {card_title[:40]} |')

        lines.append('')

    # Summary warnings
    if total_image_placeholders > 0:
        lines.append('---')
        lines.append('')
        lines.append('## Image Placeholder Summary')
        lines.append('')
        lines.append(f'**Total image placeholders:** {total_image_placeholders}')
        lines.append('')
        lines.append('> **Note:** Image placeholders will render as dashed boxes with labels.')
        lines.append('> You will need to manually insert images after generation.')
        lines.append('')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Preview layout plan before PPTX generation'
    )
    parser.add_argument('layout_plan', help='Path to layout plan JSON file')
    parser.add_argument('--output', '-o', help='Output markdown file (default: stdout)')

    args = parser.parse_args()

    if not Path(args.layout_plan).exists():
        print(f"Error: Layout plan not found: {args.layout_plan}", file=sys.stderr)
        sys.exit(1)

    layout_plan = load_layout_plan(args.layout_plan)
    preview = generate_preview(layout_plan)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(preview)
        print(f"Preview written to: {args.output}", file=sys.stderr)
    else:
        print(preview)


if __name__ == '__main__':
    main()
