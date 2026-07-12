# Decision Guide

Quick reference for common PPTX generation decisions.

## Mode Selection

| Task | Mode | Command |
|------|------|---------|
| New presentation from outline | Generate | `generate.py outline.md -o deck.pptx` |
| Fix typos in existing deck | Edit | `edit.py deck.pptx --replace ...` |
| Reorder slides | Edit | `edit.py deck.pptx --reorder "..."` |
| Change layouts | Regenerate | Modify outline, run generate.py |
| Add new slides | Regenerate | Update outline, run generate.py |
| Custom template setup | Profile | `profile.py template.pptx --generate-config` |
| Check quality | Validate | `validate.py deck.pptx` |

## Visual Type Selection

Ask these questions in order:

1. **Sequence?** → `process-N-phase`
2. **Comparison?** → `comparison-N`
3. **Parallel items?** → `cards-N`
4. **Number tension?** → `data-contrast`
5. **Quote?** → `quote-hero`
6. **Tabular?** → `table`
7. **One statement?** → `hero-statement`
8. **Default** → `bullets`

## Content → Visual Type Mapping

| Content Type | Visual Type |
|--------------|-------------|
| Methodology phases | `process-N-phase` |
| Option comparison | `comparison-N` |
| Deliverables list | `cards-N` |
| Pricing options | `comparison-tables` |
| Project timeline | `timeline-horizontal` |
| Financial data | `table` |
| Key insight | `hero-statement` |
| Customer quote | `quote-hero` |

## Edit vs Regenerate

| Change Type | Decision |
|-------------|----------|
| < 30% slides text-only | Edit |
| > 30% slides | Regenerate |
| Layout changes | Regenerate |
| Add/remove slides | Regenerate |
| Reorder only | Edit |
| Typos/values | Edit |

## Validation Modes

| Need | Command |
|------|---------|
| Basic quality check | `validate.py deck.pptx` |
| Layout coverage | `validate.py deck.pptx --template template.pptx` |
| Advanced checks | `validate.py deck.pptx --layout-plan layout.json` |
| Compare to reference | `validate.py deck.pptx --reference expected.pptx` |
| Detailed diff | `validate.py deck.pptx --diff other.pptx -o diff.md` |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Methodology in table | Use `process-N-phase` |
| Bullets for options | Use `comparison-N` |
| Centered deliverables | Use `cards-N` or `bullets` |
| Dense content in hero | Split to multiple slides |
| Edit for layout change | Regenerate instead |
| Skip validation | Always validate after generate |
