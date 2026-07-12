---
name: visual-review
description: Review browser-rendered visual artifacts for layout, export, accessibility, and presentation quality. Use after creating or modifying HTML reports, dashboards, infographics, slide-like pages, screenshots, PDFs, or PPT-ready visual assets; use when the user asks to polish, QA, make it look professional, check for clipping/overflow, verify PDF/screenshot readiness, or improve visual quality.
---

# Visual Review

Use this skill to catch visual defects before delivering HTML, screenshots, PDFs, or PPT-ready images.

## Review goals

- Detect layout breakage: horizontal overflow, clipped text, elements outside viewport, awkward spacing.
- Check export readiness: print styles, page breaks, background printing, slide aspect ratios.
- Check readability: contrast, font sizes, label density, chart/title clarity.
- Check professionalism: restrained styling, consistent spacing, no generic AI-dashboard excess.

## Script

Use `scripts/check_render.py` for a fast browser-level inspection.

```bash
python <skill>/scripts/check_render.py path/to/artifact.html --width 1440 --height 1000
python <skill>/scripts/check_render.py path/to/slides.html --width 1920 --height 1080
python <skill>/scripts/check_render.py path/to/a4-landscape.html --width 1440 --height 1018
```

The script reports console errors, page errors, document size, horizontal overflow, empty images, and elements that exceed the document bounds.

## Workflow

1. Inspect the artifact source briefly if you have not read it.
2. Run `check_render.py` at the target viewport.
   - For A4 landscape HTML, use an A4-like viewport, then inspect each `section.page` for visible overflow, clipped text, cramped charts, and tables over 8 body rows.
3. If the artifact is for PDF or screenshot delivery, also use `playwright-capture` to produce an output file.
4. Fix only defects relevant to the user request. Do not redesign unrelated areas.
5. Re-run the check after changes.
6. Summarize remaining limitations if any are intentional or not worth changing.

## Human visual checklist

Read `references/review-checklist.md` for final manual criteria when the artifact is high-stakes, dense, or presentation-bound.
