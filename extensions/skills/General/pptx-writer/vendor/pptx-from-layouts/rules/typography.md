# Typography Markers

Apply inline markers for rich text formatting in outlines and layout plans.

## Inline Markers (Text Styling)

| Marker | Purpose | Example |
|--------|---------|---------|
| `{blue}text{/blue}` | IC brand blue (#0196FF) | `{blue}premium{/blue}` |
| `{color:#HEX}text{/color}` | Custom hex color | `{color:#FF6600}alert{/color}` |
| `{size:N}text{/size}` | Font size in points | `{size:18}large{/size}` |
| `{font:Name}text{/font}` | Font family | `{font:Arial}text{/font}` |
| `{bold}text{/bold}` | Bold | `{bold}important{/bold}` |
| `{italic}text{/italic}` | Italic | `{italic}emphasis{/italic}` |
| `{underline}text{/underline}` | Underline | |
| `{strike}text{/strike}` | Strikethrough | |
| `{super}2{/super}` | Superscript | CO{super}2{/super} |
| `{sub}2{/sub}` | Subscript | H{sub}2{/sub}O |
| `{caps}text{/caps}` | ALL CAPS | `{caps}label{/caps}` |
| `{question}text?{/question}` | Blue italic (research questions) | |
| `{signpost}LABEL{/signpost}` | Blue, 14pt (section labels) | |
| `**text**` | Markdown bold | Also supported |

## Paragraph Markers (Bullet/Indent Control)

| Marker | Purpose |
|--------|---------|
| `{bullet:-}` | Dash bullet (–) - hyphen auto-converts to en-dash |
| `{bullet:•}` | Round bullet |
| `{bullet:none}` | No bullet (continuation) |
| `{bullet:1}` | Numbered list |
| `{level:N}` | Indent level (0-4) |
| `{space:before:Npt}` | Space before paragraph |
| `{space:after:Npt}` | Space after paragraph |

## Application Rules

### Blue Emphasis (`{blue}`)
- Key terms that recur throughout the deck
- Brand or product names
- Strategic concepts (e.g., "premium indulgence")
- **Consistency required:** If blue on slide 5, blue everywhere

### Research Questions (`{question}`)
- Questions framed as what research will answer
- Exploratory or hypothesis statements
- "How do...", "What makes...", "When do..."

### Signposting (`{signpost}`)
- Major section transitions only
- Always ALL CAPS
- Use sparingly (not every slide)

### Dash Bullets (`{bullet:-}`)
- Professional deck, formal tone
- European style
- Apply at paragraph level

## Table Cell Typography

Table cells support inline markers for rich formatting:

```json
{
  "headers": ["Scenario", "Year 1", "{bold}NPV{/bold}"],
  "rows": [
    ["Conservative", "$1.8M", "{blue}$8.9M{/blue}"],
    ["Aggressive", "$3.2M", "{blue}$17.2M{/blue}"]
  ]
}
```

## FORBIDDEN

- NEVER apply blue inconsistently across slides
- NEVER use `{signpost}` on every slide (major transitions only)
- NEVER forget to close typography tags
- NEVER mix marker styles arbitrarily
- NEVER use inline markers in headers (use `**bold**` instead)
