# Tables

Tables support multiple JSON structures and rendering modes.

## Markdown Table Syntax

In outlines, use standard markdown tables:

```markdown
# Investment Summary
**Visual: table**

| Category | Investment |
|----------|------------|
| Research | $50,000 |
| Design | $75,000 |
| **Total** | **$125,000** |
```

## Layout Plan JSON Patterns

### Pattern A: Column Headers

```json
{
  "content_type": "table",
  "content": {
    "table": {
      "headers": ["Column A", "Column B"],
      "rows": [
        ["Value 1", "Value 2"],
        ["Value 3", "Value 4"]
      ]
    }
  }
}
```

### Pattern B: Section Header (No Column Headers)

```json
{
  "content_type": "table",
  "content": {
    "tables": [
      {
        "header": "Section Title",
        "rows": [
          ["Label 1", "Description 1"],
          ["Label 2", "Description 2"]
        ]
      }
    ]
  }
}
```

### Pattern C: Multiple Tables

```json
{
  "tables": [
    {"headers": [...], "rows": [...]},
    {"headers": [...], "rows": [...]}
  ]
}
```

## Data Location Search Order

The generator checks for table data in this order:
1. `slide.tables[]`
2. `content.tables[]`
3. `content.table`
4. `extras.table`

## Typography in Table Cells

Table cells support inline typography markers:

```json
{
  "headers": ["Scenario", "Year 1", "{bold}NPV{/bold}"],
  "rows": [
    ["Conservative", "$1.8M", "{blue}$8.9M{/blue}"],
    ["Aggressive", "$3.2M", "{blue}$17.2M{/blue}"]
  ]
}
```

**Supported markers:**
- `{bold}text{/bold}` - Bold text
- `{blue}text{/blue}` - IC brand blue (#0196FF)
- `{italic}text{/italic}` - Italic text
- `{color:#HEX}text{/color}` - Custom color

## IC Brand Styling

| Element | Style |
|---------|-------|
| Header row | Black (#000000) background, white bold text |
| Data rows | White (#FFFFFF) background, black text |
| Header font | 10pt |
| Data font | 9pt |
| Columns | Auto-sized widths |

## Table with Image

For tables with an adjacent image placeholder:

```markdown
# Data Summary
**Visual: table-with-image**

| Metric | Value |
|--------|-------|
| Revenue | $10M |
| Growth | 15% |

[Image: supporting chart or graphic]
```

## Comparison Tables

Side-by-side pricing or option tables:

```markdown
# Pricing Options
**Visual: comparison-tables**

[Table 1: Standard]
| Feature | Included |
|---------|----------|
| Support | Email |
| Price | $999/mo |

[Table 2: Premium]
| Feature | Included |
|---------|----------|
| Support | 24/7 |
| Price | $2,499/mo |
```

## FORBIDDEN

- NEVER use `header` (singular) when you mean `headers` (plural) for column names
- NEVER put non-array values in `rows`
- NEVER assume table location without checking all paths
- NEVER use tables for sequential process flows (use `process-N-phase`)
