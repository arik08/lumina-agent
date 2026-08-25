# Visual Review Checklist

## Browser rendering

- No console/page errors.
- No missing images or broken CDN resources.
- No unintended horizontal overflow.
- The artifact works at the requested viewport.

## Presentation quality

- Purpose is obvious in the first viewport or first slide.
- Visual hierarchy guides the eye: title → key number/finding → detail.
- Similar elements have consistent alignment, spacing, and sizing.
- A full-bleed masthead may span the viewport, but its inner title, summary, and metadata share the same computed left and right content axes as the first main row and footer at desktop and narrow widths.
- Header and body do not use independent width systems such as viewport-relative header padding beside a separately centered fixed-width main container.
- On a gray or tinted report canvas, major headings and introductory copy sit inside a clear section surface or intentional section band instead of floating bare between detached cards.
- No major analytical section runs for four or more paragraphs without a chart, table, diagram, timeline, matrix, callout, evidence-card group, or structured list unless uninterrupted prose is explicitly justified as clearer.
- Added depth replaces targeted sections inside the existing visual hierarchy while preserving the rest of the report; a chain of new prose sections does not continue after the executive conclusion.
- Charts are labeled and not over-decorated.
- Chart geometry matches the data semantics: lines connect time, continuous values, or meaningful ordered stages, not nominal categories such as countries or companies.
- Multi-series comparisons across nominal categories use grouped bars, dot plots, or aligned small multiples; a secondary axis or different unit does not by itself justify a line series.
- Tables are used for exact values.

## Export quality

- Screenshot captures the intended content without clipped edges.
- PDF includes backgrounds when required and does not split critical blocks awkwardly.
- Slide-like pages preserve the target aspect ratio.
- Print mode does not depend on hover states, animations, or hidden controls.

## Accessibility

- Text contrast is readable.
- Body text is not too small for screenshot/PDF use.
- Color is not the only way to distinguish positive/negative/critical states.

## Common fixes

- Add `box-sizing: border-box` globally.
- Replace fixed pixel widths with `max-width` and responsive grids.
- Add `overflow-wrap: anywhere` for long URLs or labels.
- Reduce chart label density or rotate/shorten labels.
- Add `break-inside: avoid` for cards/tables in print mode.
