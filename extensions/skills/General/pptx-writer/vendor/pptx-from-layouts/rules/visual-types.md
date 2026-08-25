# Visual Types

**Core Principle: Visual decisions happen at outline time, not parse time.** A table is correct. A process diagram with image placeholders is compelling.

## Decision Framework

Ask in order until you get a match:

1. **Is there sequence?** (Step 1 -> Step 2 -> Step 3) -> `process-N-phase`
2. **Is there comparison?** (Option A vs Option B) -> `comparison-N`
3. **Are items discrete but parallel?** (5 deliverables, 4 findings) -> `cards-N`
4. **Is there tension between numbers?** (+12% vs -3%) -> `data-contrast`
5. **Is there a powerful quote?** -> `quote-hero`
6. **Is the data genuinely tabular?** (rows AND columns meaningful) -> `table`
7. **Is this a single punchy statement?** (1-2 sentences, no list) -> `hero-statement`
8. **Default** -> `bullets` (left-aligned with image placeholder)

## Visual Type Reference

| Visual Type | Use When | Column Count |
|-------------|----------|--------------|
| `process-N-phase` | Sequential steps, methodology flows | 2-5 |
| `comparison-N` | Side-by-side options, market comparisons | 2-5 |
| `comparison-tables` | Two tables side-by-side (pricing options) | 2 |
| `cards-N` | Discrete non-sequential items | 2-5 |
| `data-contrast` | Gap/tension between two metrics | 2 |
| `quote-hero` | Powerful quote that deserves emphasis | - |
| `hero-statement` | Single punchy statement ONLY | - |
| `story-card` | Full-bleed image with text overlay | - |
| `table-with-image` | Table with image placeholder right | - |
| `timeline-horizontal` | Date-based sequences | - |
| `table` | Genuinely tabular data | - |
| `bullets` | Standard content with 3+ items | - |
| `framework` | Generic framework, auto-detects 2-4 col | 2-4 |

## Grid Layouts (Images + Content)

| Visual Type | Structure |
|-------------|-----------|
| `grid-3x2-image-top-3-body` | 3 columns, images top, single body |
| `grid-3x2-image-top-6-body-a` | 3 columns, images top, header+body |
| `grid-2x2-image-top-2-body-a` | 2 columns, images top, single body |
| `content-image-top-4-body` | 4 columns with images top |

## Content Length Guidelines

Some visual types have constrained shape sizes. Exceeding these limits causes text overflow.

| Visual Type | Element | Max Length | Notes |
|-------------|---------|------------|-------|
| `timeline-horizontal` | Phase description | 30 chars | ~3 lines at 8pt font |
| `hero-statement` | Statement text | 100 chars | Single sentence only |
| `comparison-tables` | Table header | 25 chars | Keep concise |
| `process-N-phase` | Phase body | 50 chars/bullet | 3-4 bullets max |
| `cards-N` | Card body | 60 chars/bullet | 4-5 bullets max |

**If content exceeds limits:**
- Split into multiple slides
- Condense language (consultant prose: dense, punchy)
- Choose a different visual type with more space

## Detection Patterns

### `process-N-phase`
Keywords: step, phase, stage, then, next, methodology, approach, workflow

### `comparison-N`
Keywords: vs, versus, compared to, option A/B, pro/con, tradeoff

### `cards-N`
Keywords: deliverables, what you'll get, features, findings, recommendations

### `table`
Pattern: Explicit rows AND columns both carry meaning

### `timeline-horizontal`
Keywords: Week 1, January, Q1, schedule, milestones

### `hero-statement`
Pattern: ONE sentence that is the entire point, no supporting bullets

### `quote-hero`
Pattern: Direct quote with attribution as main content

## Quick Lookup: Common Content

| Content | Wrong | Correct |
|---------|-------|---------|
| Methodology phases | Table | `process-N-phase` |
| Market A vs Market B | Bullet lists | `comparison-2` |
| "What You'll Get" | Centered | `cards-N` or `bullets` |
| Project timeline | Table | `timeline-horizontal` |
| Research questions | Dense table | `cards-N` |
| Single memorable tagline | Left-aligned | `hero-statement` |

## FORBIDDEN

- NEVER use `hero-statement` for slides with 3+ items or deliverables
- NEVER use `hero-statement` for multi-sentence content (use `quote-hero` instead)
- NEVER use tables for methodology/process flows
- NEVER use bullet lists for side-by-side comparisons
- NEVER use centered layouts for "What You'll Get" slides
- NEVER use centered layouts for "Why Us" proof points
- NEVER default to tables when a visual type would be more compelling
- NEVER skip visual type declaration (parser defaults may not match)
