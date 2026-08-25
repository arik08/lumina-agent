# PPTX Quality Gates

Run QA on the saved `.pptx`. A generation script completing successfully is not enough.

## Required Checks

- Deck opens with package tooling.
- Slide count matches the plan.
- Every non-appendix slide has a title or deliberate title-less layout.
- No visible placeholder prompts remain.
- No `Slide Number` or `sldNum` placeholder is visible unless intentionally replaced.
- Korean text is extractable and not mojibake.
- Important text does not overflow or collide in rendered/inspected output.
- Charts and tables have readable labels and non-default styling.
- Footers, sources, page markers, logos, and confidentiality labels fit inside the slide.

## Script

```powershell
python .skills\pptx-writer\scripts\qa_pptx.py deck.pptx --output outputs\deck_qa.json
```

Treat a nonzero exit code as blocking. If render tooling is missing, say that visual parity was not fully checked and rely on content/XML/package inspection.

## Repair Loop

Patch and rerun QA until clean, or stop after three loops and report the remaining defects with slide numbers.

