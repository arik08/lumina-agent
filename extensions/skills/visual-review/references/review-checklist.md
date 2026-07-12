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
- Charts are labeled and not over-decorated.
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
