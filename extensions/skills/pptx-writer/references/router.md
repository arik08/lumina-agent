# PPTX Writer Router

Use this router before planning slides. Pick one primary path and only add secondary paths when the request truly needs them.

## Decision Matrix

| Signal | Route | Output expectation |
| --- | --- | --- |
| "standard template", "POSCO template", "keep this format", supplied `.pptx` template | Corporate template | Template profile plus editable deck using actual layouts/placeholders |
| "make a PPT", "executive report", "7 slides", no template | General create | Editable PPTX with native text/shapes/tables/charts |
| "edit this PPT", "summarize this deck", "change slide 3" | Existing edit/read | Inventory first, then targeted patch |
| PDF/DOCX/Markdown/URL/source dossier to slides | Document draft | Editable draft, not final-polished unless QA/polish requested |
| "check", "polish", "usable", "overflow", "font broken" | QA/repair | Defect list and fixed PPTX when requested |

## Planning Contract

Before generating, write or keep a compact internal contract:

```text
audience:
decision_to_unlock:
tone:
slide_count:
template_source:
source_material:
per_slide_claims:
evidence_mapping:
engine:
qa_requirements:
```

## Defaults

- Audience defaults to Korean business/executive readers when the prompt is Korean or mentions internal reports.
- Tone defaults to concise, evidence-led, and non-marketing.
- Use fewer slides only when the story stays readable; split overfull content instead of shrinking text.
- Treat unknown template quality as a risk until `inspect_template.py` proves real layouts/placeholders exist.

