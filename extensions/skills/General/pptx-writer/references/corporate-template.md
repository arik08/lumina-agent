# Corporate Template Workflow

This path is for internal or executive decks where layout fidelity matters more than creative freedom.

## Steps

1. Inspect the template:

```powershell
python .skills\pptx-writer\scripts\inspect_template.py template.pptx --output outputs\template_profile.json
```

2. Decide if the template is placeholder-friendly:
   - Good: named slide layouts, title/body/table/chart placeholders, stable footer/page structures.
   - Weak: mostly freeform shapes, pasted screenshots, unnamed text boxes, no useful placeholders.

3. If good, use the `vendor/pptx-from-layouts` workflow as the first implementation reference.
4. If weak, clone an existing slide closest to the needed shape or rebuild with PptxGenJS while preserving visual tokens.
5. QA the saved `.pptx`, not only source JSON or thumbnails.

## Mapping Rules

- Use the template's real slide layouts for cover, divider, content, table/chart, and closing slides.
- Insert text into matching placeholders instead of laying text on top of backgrounds.
- Preserve corporate chrome: logo, page number, confidentiality labels, footer, source notes, safe margins, and typography.
- When content does not fit a template placeholder, shorten, split, or choose another layout. Do not silently overflow.

## Failure Signals

- Placeholder count is near zero across layouts.
- Layout names are generic and no useful placeholder types appear.
- Extracted text includes template prompts such as "Click to add title" in final output.
- Korean text wraps differently after saving/reopening.

If these occur, report that exact limitation and switch to the least destructive fallback.

