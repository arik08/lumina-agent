---
name: visual-artifact
description: Create polished single-file HTML visual artifacts such as visually rich reports, dashboards, infographics, one-pagers, slide-like webpages, visual summaries, comparison pages, timelines, and interactive previews. Use when the user asks for a beautiful/dynamic webpage-like output, HTML preview, visual report, presentation-style page, screenshot-ready artifact, PDF-ready page, business/research summary, or any reusable visual deliverable intended to be opened in a browser or captured into PPT/PDF. Preserve the requested artifact type; ordinary report-style HTML should remain a web-native scrolling report unless the user explicitly asks for a fixed page, A4, or slide format.
---

# Visual Artifact

Create browser-native visual deliverables that are polished enough to screenshot, present, print, or convert to PDF/PPT.

## Default output

- Prefer one self-contained `.html` file with inline CSS and JS.
- For MyHarness single-file previews, keep CSS and app code in the HTML file when practical so the file card can open it directly; relative external files can break in `iframe srcdoc` previews.
- If the user describes report length in tokens, including Korean forms such as `5000~8000 토큰`, `10000 토큰 수준`, `15000~20000 토큰 이상`, or `30000토큰 수준`, treat the number as an approximate output-size target that should be checked, not merely a style cue. Use the target to plan content depth, but do not crowd the page with walls of prose, cramped tables, or repetitive cards just to hit a length. Preserve visual rhythm with section summaries, charts, callouts, and source notes.
- Use a short purpose-specific filename, not `index.html`, unless the user explicitly asks for it or an existing app requires it. Prefer concise readable Korean filenames with underscores for Korean-facing reports/previews; use English kebab-case or snake_case for code-heavy demos, games, or English-facing artifacts.
- Keep dependencies purposeful. CDN libraries are optional, not mandatory: use React/ReactDOM via CDN only when repeated sections, controls, reusable state, or chart containers would materially benefit from component structure without a build step. Use plain static HTML/CSS/JS when it is sufficient for the artifact.
- Make the artifact readable in a constrained iframe and in a normal browser window.
- Do not include secrets or unsanitized user-provided HTML.

## Decide the artifact type

- **Executive/report page**: structured findings, tables, charts, recommendations, sources in a polished scrolling web report.
- **A4 landscape page report**: only when the user explicitly asks for A4 landscape, A4 가로, 가로형 A4, printable horizontal PDF, or a fixed-page report, use this skill for HTML/browser visual direction and use `html-a4-landscape-report` together with it for fixed-page structure, density limits, table splitting, and overflow QA. For A4 PPTX, pair `html-a4-landscape-report` with `pptx-writer` instead.
- **Dashboard**: KPI cards, charts, filters/toggles if useful, data table.
- **Infographic/one-pager**: strong story flow, big numbers, compact sections, print/capture-ready layout.
- **Slide-like HTML**: 16:9 sections, keyboard or scroll navigation only if useful.
- **Diagram/timeline/comparison**: SVG, Mermaid, or HTML/CSS layouts depending on complexity.

## Report-first rule

When the user asks for analysis, research, company information, financial results, market review,
quarterly trends, sources, or a report:

- Make it read like a report, not like a company homepage.
- Start with report metadata and an executive summary, not a marketing hero with CTA buttons.
- Do not ask the user to choose a layout, style, or report archetype when they already asked for a report. Infer the best direction from the subject, audience, source material, and requested format, then proceed.
- For ordinary vertical HTML reports, use a web-native report composition: masthead, executive summary, strong section rhythm, visual anchors, charts, callouts, tables, footnotes, and a clear closing. It should feel designed, not like a plain document exported to HTML.
- Prefer well-composed section bands, tables, footnotes, callouts, and charts over oversized feature cards.
- Use brand/style references as surface treatment only: typography, spacing, material, color, chart
  finish, and tone.
- Avoid nav menus, sign-up buttons, pricing blocks, testimonials, "features" funnels, and generic
  landing-page conversion sections unless explicitly requested.
- Put exact numbers in tables and chart labels; use charts for trend cognition.
- For analysis requests, actively consider adding a compact Mermaid `flowchart` when causal logic, process steps, decision paths, stakeholder relationships, system flow, or issue-to-action structure would make the analysis easier to scan. This is recommended, not mandatory; skip it when prose, a table, or a numeric chart communicates the point more clearly.
- For financial/company reports, include a compact source note area and make uncertainty explicit.
- If important claims, numbers, charts, or recommendations rely on external knowledge such as web research, MCP/vector database results, source documents, or database queries, cite the source in the report using a compact footnote, source note, or sources section. Use the most specific identifier available: URL/title, document page/path, MCP server/resource, document id, table name, or query label. Do not invent citations when source metadata is missing; state the limitation instead.

## HTML Source Footnotes

- For standalone HTML reports, cite source-backed facts with compact clickable numbered source badges instead of long inline URLs or visible source chips.
- Use this fixed markup pattern next to the sourced fact: `<sup class="source-ref"><a href="https://example.com" target="_blank" rel="noreferrer">3</a></sup>`.
- Put `<!-- myharness:source-footnotes-css -->` once in the HTML `<head>`. Do not write custom CSS for `.source-ref`; the `write_file` tool expands this marker into the fixed tooltip CSS when saving the artifact.
- The visible mark should stay short: a small circular badge containing only the number, such as `3`. The click target opens the original source link in a new tab.
- For web sources gathered through `web_search`/`web_fetch`, do not write the excerpt yourself. Leave `data-tooltip` absent or empty; `write_file` fills it from stored tool evidence when saving. The filled tooltip contains the short source address on the first line and a short verbatim excerpt directly taken from the source/tool result on the second line. The excerpt line is wrapped in double quotes to show it was copied unchanged. Do not summarize the excerpt in your own words when a direct source sentence is available.
- Keep a compact `Sources`/`출처` list near the end of the HTML that maps the same numbers to site names or titles and URLs.

## Visual direction

- Choose a visual concept before writing CSS. Keep it business-appropriate, but vary the format to fit the subject instead of reusing the same card grid every time.
- Choose the archetype yourself. Do not pause to offer these as options unless the user explicitly asks for alternatives.
- Useful report archetypes include: editorial briefing, analytical dashboard-report, consulting memo, intelligence dossier, market map, timeline review, operating review, and executive decision note.
- Let the archetype change the composition: a market map may use broad comparison bands and quadrant visuals; a timeline review may use a strong chronology spine; an executive decision note may use a tight recommendation stack; an intelligence dossier may use compact evidence panels and source trails.
- Avoid defaulting to the same hero/KPI-card/three-section/table layout unless it is clearly the best fit for the content.

## Interactive Elements

- For MyHarness HTML reports, dashboards, infographics, and interactive previews, actively use interaction when it improves scanning, comparison, or decision-making, but keep the artifact report-first. Prefer interactions that enrich visible content in place, such as hover/focus tooltips, chart hover details, source/excerpt tooltips, inline highlighting, sortable tables, search/filter refinement, and chart-series toggles.
- Treat interaction as a report-reading aid, not decoration. Each control should answer a reader question such as “which segment matters?”, “what changed by period?”, “where is the risk?”, “what evidence supports this?”, or “how do scenarios compare?”
- Be cautious with click-to-reveal screens such as tabs, accordions, hidden panels, modal detail views, and multi-step drilldowns. Use them only when space or density genuinely requires it, and never make them the only path to the executive summary, primary recommendation, key risks, or essential evidence.
- Keep the core conclusion and main narrative visible without requiring interaction. Use controls to refine, annotate, compare, sort, or reveal secondary detail; do not turn the report into an app where the reader must click through hidden screens to understand the message.
- Make interactive states explicit and polished: selected tabs/filters should be visually clear, empty states should explain what filter/search removed, and charts/tables should update together when they represent the same lens.
- Prefer compact, businesslike controls: inline search, table sort headers, chart legend toggles, hover/focus tooltips, small filter chips, and restrained segmented controls. Avoid oversized game-like controls, click-heavy navigation, or controls that create layout jumps. Hover-only interaction is fine for supplemental tooltips and excerpts, but not for core meaning.
- For search/filter interactions, default to case-insensitive and whitespace-tolerant matching when matching labels, titles, names, or evidence snippets.
- Ensure keyboard and screen-reader basics: use real buttons/inputs where possible, add `aria-label` where text is not sufficient, expose active state with `aria-pressed`/`aria-selected` where appropriate, and keep focus outlines visible.

## Design bar

- Aim for “usable in a real meeting,” not merely “AI-generated.”
- Use restrained but visually intentional business styling: clear type scale, crisp spacing, meaningful hierarchy, a subject-appropriate palette, and enough contrast between sections to guide the eye.
- Restrained does not mean all-white, gray, or template-like. Give each report a coherent visual system with a few distinctive accents, chart colors, rules, tags, or background bands that match the topic.
- Avoid oversized radii, pill-heavy cards, excessive gradients, and bloated padding unless requested.
- Prefer 4–8px radius for panels/cards/buttons.
- Avoid yellowed report palettes. Unless the user explicitly asks for that look, do not make reports feel like aged paper, parchment, sepia, or a cream/beige/yellowed document. Choose an appropriate non-yellowed palette for the subject instead of defaulting to all-white/all-gray surfaces.
- Avoid arbitrary pastel flooding across large cards, quadrants, table cells, or sections just to label categories. This is a caution against noisy decoration, not a ban on color. For business reports, use color with intent: section bands, pale fills with crisp accents, chart marks, left/top borders, small tags, icons, or callouts. Use stronger color when it supports quantitative intensity, status severity, selected state, brand tone, or a deliberately infographic-style artifact.
- Use exact tables for exact values; use charts for trends, comparisons, proportions, timelines, or distributions.
- For standalone HTML reports or web reports, use Mermaid when workflow, architecture, sequence, dependency, approval, or organization-change diagrams would explain the subject better than prose or a table. Organization redesign, governance, handoff, approval, and operating-model reports should usually include at least one real process/workflow map when the source material supports it.
- In MyHarness previews, raw `<div class="mermaid">...</div>` and `language-mermaid` code blocks are rendered by the same app Mermaid renderer used for chat. Do not leave visible raw Mermaid text or placeholder boxes in the finished preview. If an artifact must work as a fully standalone file outside MyHarness, include Mermaid.js and initialize it in the artifact itself.
- For report-like artifacts, actively consider restrained semantic icons for section markers, KPIs, risks, recommendations, and action items when they improve scanning. Keep icons small, consistent, and businesslike; avoid childish, toy-like, emoji-heavy, or purely decorative icon use. Do not force icons into every card or paragraph.
- Prefer this default color palette for charts, categorical accents, heat scales, and report highlights unless the user provides a brand palette or the artifact clearly needs another scheme: `#3288bd`, `#66c2a5`, `#e6f598`, `#d53e4f`, `#9e0142`, `#f46d43`, `#fdae61`, `#fee08b`, `#abdda4`, `#5e4fa2`. Use a few colors intentionally; avoid turning every section into a rainbow.
- For Mermaid process maps and dense diagrams, use semantic color groups so the reader can scan the system at a glance: blue for standards/requests/reports, teal for operations/market/planning, orange for investment/CAPEX/strategic decisions, red for risk/issues, and purple for governance/approval. Prefer pale fills with crisp colored borders and readable dark text; use stronger fills only for start/end, warnings, or key status nodes. In flowcharts, add `classDef` styles and assign classes by meaning instead of leaving all nodes the same color.
- Use accessible contrast and semantic HTML.

## Layout Density And Whitespace QA

- Treat large unused white space inside report panels as a layout defect, especially when a chart or table occupies only the top half of a bordered card. Do not leave a mostly empty card just because its sibling column is taller.
- Fill report panel space with meaningful content before changing dimensions: key takeaways, interpretation bullets, metric strips, benchmark notes, anomaly explanations, source notes, confidence/limitation notes, or a compact secondary visual. Do not solve sparse panels by merely shrinking everything into a tiny chart.
- Size charts to their actual data and reading task while preserving readable scale. Use `aspect-ratio`, `min()`/`clamp()`, and explicit `max-height` to prevent accidental oversizing, but prefer adding relevant analysis around the chart when the section has room.
- In any two-column or multi-card row, adjacent cards must read as one aligned row: matching top edges, matching bottom edges when framed, consistent outer gutters, and comparable internal padding. Do not leave lower-row cards with visibly mismatched heights or dangling side edges unless the composition is intentionally masonry/editorial and unframed.
- In two-column report sections, do not force equal-height cards when the content is imbalanced unless both cards are intentionally filled. If one side is taller, use the other side to explain what the reader should conclude from the visual rather than leaving blank space.
- For paired chart-plus-interpretation sections, align the right panel with the left panel deliberately: top edges, right column width, and bottom edges should read as one clean row. If the explanation card is shorter than the chart/table card, fill it with additional analysis, caveats, source notes, ranked implications, or next-step interpretation; do not leave a ragged right-side border floating halfway down the row.
- Use CSS grid intentionally for paired report panels (`align-items: stretch` only when both sides are content-filled; otherwise change the composition). Avoid accidental masonry-like ragged edges in formal report sections unless the whole section is intentionally unframed and editorial.
- Before finalizing an HTML report, scan each section at desktop width and ask: “Is more than about one-third of this panel blank?” If yes, first add useful analysis or supporting evidence; if there is nothing meaningful to add, then split the table, adjust the grid, or change the composition.
- Keep vertical rhythm deliberate: section gaps should separate ideas, not compensate for sparse content. Avoid `min-height`, viewport-height sections, oversized padding, and stretch-aligned grid rows unless the content actually fills them with information.

## Library choices

- **React/ReactDOM via CDN**: optional for MyHarness HTML reports, dashboards, infographics, and interactive previews. Use it when repeated report sections, tabs, filters, search, chart panels, sortable/explorable tables, or reusable UI state would be clearer as component-driven browser JS inside a single HTML file. Skip it when plain static HTML/CSS/JS is simpler and sufficient. Prefer prewritten browser JS over in-browser JSX/Babel when practical to keep load time lower.
- **ECharts**: multi-chart business dashboards/reports.
- **Chart.js**: simple common charts.
- **Lucide or similar icon sets**: restrained semantic icons for reports, dashboards, and visual summaries.
- **SVG/CSS**: small bespoke static visuals, cards, fixed callouts, and simple timelines when Mermaid or ECharts would be heavier than the job.
- **Mermaid**: maintainable diagrams in the Mermaid.js family, not only flowcharts. Prefer Mermaid over hand-drawn SVG for structured diagrams when the visual type fits, because Mermaid is usually cleaner and easier to revise. In MyHarness chat or Markdown artifact previews, prefer fenced `mermaid` blocks for compact diagrams such as `flowchart`, `sequenceDiagram`, `classDiagram`, `stateDiagram`, `erDiagram`, `gantt`, `pie`, `journey`, `gitGraph`, `timeline`, `mindmap`, `quadrantChart`, and `sankey`. Choose the type that fits the content instead of defaulting to flowchart. Use `quadrantChart` freely for 2x2 prioritization/positioning and use `sankey` for flow/allocation diagrams; MyHarness validates Mermaid before writing human-facing HTML/Markdown artifacts so syntax errors can be fixed before preview. Avoid Mermaid keyword-like flowchart class names such as `end`; use names like `finish` or `done`. If a requirement diagram is the right choice, quote user-defined `id`/`text` values and use canonical enum casing so MyHarness can render it reliably. In standalone HTML artifacts, include Mermaid via CDN only when the artifact needs those diagram types, and render from `<div class="mermaid">...</div>` blocks rather than showing Mermaid as code.
- **Reveal.js**: full HTML slide decks.
- **Three.js/D3/Leaflet**: only when 3D, advanced data visualization, or maps are central.

## Workflow

1. Infer audience, output type, size target, reuse goal, and visual archetype. For report requests, choose the visual archetype yourself and proceed; ask only when missing information prevents the factual work or the requested output format is genuinely unclear.
2. Structure the content before styling: sections, data, charts, interactions, export needs. Decide which reader questions deserve interactive controls and which findings must remain visible by default.
3. Build the single HTML artifact with responsive CSS and print/capture considerations.
4. Include `@media print` for PDF-friendly output when the artifact is report-like or slide-like.
5. If the user wants screenshots/PDF, use the `playwright-capture` skill after creating the HTML.
6. For important or dense visuals, use the `visual-review` skill to inspect clipping, overflow, chart labels, and print layout.

## Capture-friendly conventions

- For presentation-style output, include a `.stage` or `.slide` layout with 16:9 ratio when appropriate.
- For A4 landscape HTML/PDF/browser reports, use both this skill and `html-a4-landscape-report`; keep visual direction here, and let `html-a4-landscape-report` own the page-based layout workflow. For A4 landscape PPTX, use `html-a4-landscape-report` with `pptx-writer`.
- For reports, make A4/Letter print behavior explicit with sensible page breaks.
- Avoid content that depends on hover-only interactions for core meaning.
- Keep animations subtle and disable or simplify them for print.

## References

- Read `references/design-checklist.md` when polishing a high-stakes visual, report, dashboard, or presentation artifact.
