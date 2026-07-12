---
name: playwright-capture
description: Render local or remote HTML pages with Playwright/Chromium and export screenshots or PDFs. Use when the user asks to capture a webpage, convert HTML to PNG/PDF, inspect browser-rendered output, generate screenshots for PPT, render slide/report artifacts, test responsive viewports, or verify that a visual HTML file actually opens and exports correctly.
---

# Playwright Capture

Use this skill to turn HTML artifacts into browser-rendered screenshots and PDFs.

## Core behavior

- Prefer local, reproducible rendering with Playwright.
- For local files, resolve to an absolute file path and load it as `file:///...`.
- Capture both a screenshot and/or PDF depending on the user request.
- Use deterministic viewport sizes. Defaults:
  - report/dashboard screenshot: `1440x1000`, full page
  - slide screenshot: `1920x1080`, viewport only unless full-page is requested
  - PDF: print background enabled
- Wait for network idle and a short settle delay before capture.

## Script

Use `scripts/capture_html.py` for common cases.

Examples:

```bash
python <skill>/scripts/capture_html.py path/to/report.html --png report.png --pdf report.pdf
python <skill>/scripts/capture_html.py path/to/slides.html --png slide.png --width 1920 --height 1080 --no-full-page
python <skill>/scripts/capture_html.py https://example.com --png page.png
```

The script installs nothing. If Playwright is missing, report the missing dependency and ask before installing packages.

## Workflow

1. Confirm the source HTML/URL exists.
2. Choose viewport and output filenames based on artifact type.
3. Run `capture_html.py`.
4. If capture fails, read the error and fix the page or dependency issue before retrying.
5. For high-stakes visuals, use `visual-review` after capture.

## Safety

- Do not capture private/authenticated pages unless the user explicitly provided access and confirmed intent.
- Do not invent URLs.
- Avoid sending local file contents to external services.
