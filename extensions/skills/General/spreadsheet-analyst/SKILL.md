---
name: spreadsheet-analyst
description: "Use when a spreadsheet is the primary input or output: creating, reading, editing, auditing, cleaning, or converting .xlsx, .xlsm, .csv, or .tsv files; building Excel workbooks with formulas, formatting, charts, tables, pivots, data validation, financial or operational models, and office reports. Trigger when the user asks for Excel, spreadsheets, workbook creation, spreadsheet analysis, table cleanup, CSV/XLSX conversion, or formula/formatting fixes. Do not use when the requested deliverable is only a prose report, HTML page, database pipeline, or Google Sheets API task unless a spreadsheet file is explicitly requested."
---

# Spreadsheet Analyst

## Core Rules

- Preserve existing workbook structure, formulas, formatting, hidden sheets, named ranges, tables, charts, and template conventions unless the user asks to change them.
- Prefer Excel formulas for calculated cells. Do not hardcode totals, growth rates, ratios, rollups, or scenario outputs that should update when inputs change.
- Never overwrite an existing user workbook unless explicitly requested. Save a new output file or make a clear backup.
- Treat row/column labels, IDs, dates, currencies, percentages, and units as data contracts. Preserve leading zeros and parse dates deliberately.
- Deliver workbooks with no known formula error literals such as `#REF!`, `#DIV/0!`, `#VALUE!`, `#N/A`, or `#NAME?`.
- For Korean-language deliverables, prefer concise Korean filenames under `outputs/` unless the user gives a path.

## Tool Choice

- Use `pandas` for tabular analysis, cleaning, joins, summaries, profiling, and bulk import/export.
- Use `openpyxl` when editing existing `.xlsx`/`.xlsm` files, preserving formulas/styles, adding formulas, validations, tables, comments, freeze panes, filters, and conditional formatting.
- Use `xlsxwriter` when creating a new workbook from scratch and advanced chart formatting matters more than editing an existing file.
- Use Python's `csv` module for malformed CSV/TSV recovery before loading into pandas.
- Use LibreOffice or Excel recalculation only when available. If formulas cannot be recalculated locally, perform static validation, reopen the workbook, and state that live recalculation was not available.

## Workflow

1. Identify whether the task is create, edit, analyze, clean, convert, or audit.
2. If an existing spreadsheet is involved, inspect it before changing it. Run `scripts/workbook_audit.py <path>` and also inspect relevant sheets directly with `pandas` or `openpyxl`.
3. Decide the workbook structure: sheets, source data, calculated sections, summary views, formulas, number formats, charts, filters, validations, and assumptions.
4. Implement the smallest workbook changes that satisfy the request. Match existing style for templates; otherwise use a restrained office style with readable column widths, frozen headers, filters, and clear number formats.
5. Save to a new file unless the user explicitly requested in-place editing.
6. Reopen the output file and verify that sheets exist, formulas are preserved, important ranges are populated, formatting is not obviously broken, and static formula-error scans pass.
7. Report the output path and the verification performed. Mention any limitations, such as missing live formula recalculation.

## Spreadsheet Quality Bar

- Add filters or Excel tables for structured tabular data.
- Freeze the header row for sheets intended for review.
- Use number formats consistently: dates as dates, currencies as currencies, percentages as percentages, counts as integers.
- Use named sheets with business meaning. Avoid generic names like `Sheet1` in final deliverables unless preserving a template.
- Add cell comments only for non-obvious assumptions, source notes, or formulas a future user may need to trust.
- Keep dashboards compact and scan-friendly. Avoid oversized decorative formatting.

## Formula Guidance

Use formulas for workbook logic:

```python
sheet["E2"] = "=C2*D2"
sheet["E10"] = "=SUM(E2:E9)"
sheet["F2"] = "=IFERROR(E2/B2,0)"
```

Avoid Python-hardcoded calculations when the workbook should remain dynamic:

```python
# Avoid for calculated workbook outputs
sheet["E10"] = df["sales"].sum()
```

## Validation Helper

Run the bundled audit helper when a spreadsheet already exists or after creating one:

```bash
python .skills/spreadsheet-analyst/scripts/workbook_audit.py outputs/report.xlsx
python .skills/spreadsheet-analyst/scripts/workbook_audit.py data/source.csv
```

The helper summarizes sheets, dimensions, formulas, obvious error literals, tables, merged ranges, and CSV shape issues. It is not a substitute for opening/recalculating the workbook when formulas or visuals are critical.
