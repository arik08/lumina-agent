# General Create/Edit Workflow

Use this for new editable decks or existing deck edits that do not require strict template placeholder insertion.

## New Decks

- Use PptxGenJS for editable text, shapes, images, charts, and tables.
- Use MiniMax slide-type guidance from `vendor/minimax-pptx-generator/references/slide-types.md` for cover, TOC, section divider, content, summary, comparison, chart, and table slides.
- Define a small design system before writing slides: page size, fonts, palette, title/body scale, margins, chart/table styling, and source-note style.
- Prefer native charts/tables for business data. Avoid default Office chart styling.

## Existing PPTX Work

1. Inventory before editing:

```powershell
python .skills\pptx-writer\scripts\read_pptx.py source.pptx --output outputs\source_inventory.json
```

2. Render thumbnails or inspect saved PPTX when tooling is available.
3. Patch only the requested slides/objects.
4. Inspect raw OOXML when placeholder remnants, numbering, notes, comments, embedded charts, or theme relationships matter.
5. Re-run QA after every edit pass.

## Anthropic-Style QA Pattern

Use the rebuilt pattern, not a blind script-only pass:

- read semantic content
- inspect visible slide output when available
- inspect XML/package structure when visual or semantic checks disagree
- fix source/deck
- reopen or re-extract the saved deck
- report unresolved parity limits

## Copy Rules

- Keep titles as assertion sentences where appropriate.
- Put details in speaker notes or appendix when live slides become dense.
- Use Korean business wording for Korean decks; avoid casual translation artifacts.
- Do not include meta text such as "generated with", "using native chart", or tool names on slides.

