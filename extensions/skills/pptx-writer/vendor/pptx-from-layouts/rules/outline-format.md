# Outline Format

**Core Principle: Structure determines parsing.** Use explicit headers for control, separators to finalize slides.

## Basic Structure

```markdown
# Slide 1: Title

## Project Name

### Subtitle

Client x Partner
January 2026

---

# Slide 2: The Challenge

**Brief headline summarizing the tension.**

- First supporting point
- Second supporting point

---
```

## Slide Separator Modes

**Explicit Headers Mode** (recommended):
```markdown
# Slide 5: Research Findings
...content...
---

# Slide 6: Recommendations
...content...
---
```

**Legacy Mode** (auto-numbered, no `# Slide N:` headers):
```markdown
## Introduction
...content...
---

## Key Findings
...content...
---
```

Parser auto-detects based on presence of `# Slide N:` headers.

## Visual Type Declaration

Single line after slide header:

```markdown
# Slide 10: Our Approach

**Visual: process-4-phase**

[Column 1: Discover]
...
```

## Layout Override

When auto-detection picks wrong layout:

```markdown
# Slide 8: Our Approach

**Visual: process-4-phase**
**Layout: column-4-centered**
```

## Content Detection

| Element | Marker | Example |
|---------|--------|---------|
| Slide header | `# Slide N: Label` | `# Slide 5: Methodology` |
| Slide separator | `---` | Finalizes current slide |
| Visual type | `**Visual: type**` | `**Visual: process-4-phase**` |
| Layout override | `**Layout: name**` | `**Layout: column-4-centered**` |
| Column block | `[Column N: Header]` | `[Column 1: Discover]` |
| Card block | `[Card N: Title]` | `[Card 1: Framework]` |
| Table block | `[Table N: Header]` | `[Table 1: Option A]` |
| Image placeholder | `[Image: description]` | `[Image: customer interview]` |
| Background image | `[Background: description]` | `[Background: cozy workspace]` |
| Timeline entry | `[Date] Activity` | `[Week 1] Kickoff` |
| Headline | First `**bold**` line | `**This is the key point.**` |
| Quote | `>` blockquote | `> "Quoted text"` |
| Appendix | `## Appendix` | Stops parsing |

## FORBIDDEN

- NEVER omit the `---` separator between slides
- NEVER use `---` inside slide content (confuses parser)
- NEVER skip slide numbers in explicit mode
- NEVER mix explicit and legacy modes in one outline
- NEVER put Visual declaration before slide header
