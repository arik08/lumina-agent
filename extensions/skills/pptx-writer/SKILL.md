---
name: pptx-writer
description: Use when creating, editing, reading, analyzing, converting, or quality-checking PowerPoint decks, PPT/PPTX files, slide decks, executive reports, corporate template presentations, or document-to-presentation drafts.
---

# PPTX Writer

Editable PPTX is the default outcome. Use this skill for PowerPoint work that must survive real business review: template fidelity, readable Korean text, editable shapes/charts/tables, and a QA loop that catches layout damage before delivery.

## Operating Flow

Always run the request through this six-stage pipeline:

1. **Intent Router**: classify the task as new deck, existing PPTX edit, document-to-draft, corporate-template generation, QA-only, or mixed.
2. **Outline Planner**: define slide count, executive message, per-slide claim, evidence/source mapping, and the decision the deck must unlock.
3. **Layout Mapper**: map each slide to cover, TOC, section divider, content, comparison, roadmap, table, chart, summary, appendix, or template layout.
4. **PPTX Generator**: choose the narrowest reliable engine.
5. **Visual QA**: inspect text overflow, Korean font damage, placeholder remnants, collisions, chart/table readability, and missing titles/page markers.
6. **Final Reviewer**: check executive tone, message sharpness, source credibility, and slide-to-slide logic.

Do not stop at "file created." A deck is complete only after the generated or edited `.pptx` passes QA, or the remaining risks are explicitly reported.

## Router

Read `references/router.md` first when the task is not obvious.

| Request shape | Primary path | Required reference |
| --- | --- | --- |
| Company/POSCO/internal template must be preserved | Template-first placeholder workflow | `references/corporate-template.md` |
| New deck without a strict template | PptxGenJS/MiniMax-style generation | `references/general-create-edit.md` |
| Existing PPTX read, summarize, modify, merge, split, or inspect | Read/thumbnail/XML inspection workflow | `references/general-create-edit.md` |
| PDF/DOCX/Markdown/URL/source material to editable draft | PPT Master document draft workflow | `references/document-draft.md` |
| Final checking, repair, or "make it usable" | QA gate workflow | `references/quality-gates.md` |

Load only the needed reference files. Use vendored material in `vendor/` for concrete implementation details when the short references are not enough.

## Engine Selection

- **Corporate templates**: prefer `vendor/pptx-from-layouts` because it profiles slide masters, layouts, and placeholders instead of treating the template as a background image.
- **General create/edit**: prefer `vendor/minimax-pptx-generator` and local PptxGenJS for editable shapes, text, charts, tables, images, and XML-level repair.
- **Document draft**: prefer `vendor/ppt-master` for source conversion, strategist/executor/QA staging, and editable draft expectations.
- **Inspection and QA**: use Anthropic-style practice rebuilt here: read content, render/thumbnail when available, inspect raw OOXML when visual output is suspicious, patch, then verify again.

If a strict template is mostly hand-drawn shapes with weak placeholders, say so and switch to clone-first/reference rebuild or general generation rather than pretending placeholder insertion will be reliable.

## Script Quick Start

Run these from the MyHarness project root:

```powershell
python .skills\pptx-writer\scripts\check_pptx_env.py --report-only
python .skills\pptx-writer\scripts\inspect_template.py path\to\template.pptx --output outputs\template_profile.json
python .skills\pptx-writer\scripts\read_pptx.py path\to\deck.pptx --output outputs\deck_inventory.json
python .skills\pptx-writer\scripts\qa_pptx.py path\to\deck.pptx --output outputs\deck_qa.json
```

Use `scripts/bootstrap_pptx_env.py` only when the user asks to install dependencies or when running `Installer.bat`; do not surprise-install packages during ordinary deck work.

## Delivery Rules

- Put new human-facing artifacts under `outputs/`; prefer concise Korean filenames for Korean decks.
- Do not store private corporate templates inside this skill. Profile the user-supplied `.pptx` for the current task.
- Preserve editability unless the user explicitly accepts an image/PDF-only deliverable.
- Use native charts/tables for chartable or tabular data whenever possible.
- For current facts, markets, companies, people, laws, or prices, verify before putting claims into slides.
- Final response should include deck path, QA command, preview/render status if available, and unresolved risks.

