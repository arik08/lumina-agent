---
name: ui-design-essence
description: Design-quality guardrails for UI and visual artifacts. Use as a supporting skill when polishing or reviewing visual hierarchy, design tokens, density, responsiveness, accessibility, and purposeful motion for pages, components, dashboards, reports, prototypes, landing pages, or HTML previews. Do not use as the primary creator for HTML reports, A4/PDF reports, homepages, or app UIs; pair it with visual-artifact, html-a4-landscape-report, frontend-design, or the relevant primary skill.
---

# UI Design Essence

Use this skill as a design-quality guardrail when polishing or reviewing visual UI and visual artifacts. It should sharpen hierarchy, tokens, density, responsiveness, accessibility, and motion without changing the requested artifact type.

This is usually a supporting skill, not the primary creator:

- Use `frontend-design` as the primary skill for homepages, landing pages, marketing/product sites, branded websites, app UI, prototypes, demos, and game UI.
- Use `visual-artifact` as the primary skill for scrolling HTML reports, dashboards, infographics, timelines, visual summaries, and report-style browser artifacts.
- Use `html-a4-landscape-report` together with `visual-artifact` for fixed-page A4 landscape reports.
- Use this skill after or alongside those skills when the work needs better visual hierarchy, consistent tokens, density tuning, responsiveness, accessibility, or generic-AI-UI cleanup.

Do not make a generic good-looking UI; preserve the artifact type and improve the design decisions inside that type.

## Start with a design direction

Before coding, decide and briefly state:

- **Purpose**: what the interface must accomplish.
- **User**: who uses it and in what context.
- **Mood**: the intended feeling, not a vague adjective pile.
- **Density**: spacious, balanced, or compact. Default to slim, clean, work-focused density.
- **Signature detail**: one memorable visual or interaction detail, not many.

## Define a small token system

Create or reuse tokens before styling components:

- Colors: `background`, `surface`, `text`, `muted text`, `border`, `accent`.
- Spacing scale.
- Radius scale.
- Shadow/elevation scale.
- Motion timing.

Do not invent new colors, font sizes, radii, shadows, or animation timings inside individual components. If a new visual value is needed, add it to the token system first.

## Prioritize hierarchy before decoration

Decide:

- What should the user notice first?
- What is the primary action?
- What is secondary?
- What can be hidden, softened, or removed?

Make the first read obvious. Keep secondary content quieter. Remove decorative elements that do not support comprehension or action.

## Avoid generic AI UI clichés

Do not default to:

- Purple/blue/pink gradients.
- Inter, Roboto, Arial, or `system-ui` as lazy primary fonts.
- Repeated fallback to the same “interesting” fonts.
- Generic SaaS blue (`#3B82F6`) as the default accent.
- Rounded card grids with gradient buttons as the default recipe.
- Random glassmorphism or blob backgrounds.
- Emoji as structural icons.
- Fake logos, fake metrics, fake testimonials.
- Decorative icon spam.

Use honest placeholders: `[icon]`, simple geometry, aspect-ratio image placeholders, or clearly marked sample data.

## Choose density intentionally

- Marketing/editorial: spacious is allowed.
- Product UI: balanced density.
- Dashboard/admin/report: compact, aligned, information-dense.

For business-style reports and dashboards, prefer restrained, work-focused visuals: aligned tables, clear labels, compact panels, and square or lightly rounded corners.

## Preserve the requested format

Style direction is not product definition. If the user asks for a report, dashboard, note, analysis,
or briefing "in the style of" a brand, keep the artifact's structure in that format and apply the
brand as visual language only. Do not turn reports into landing pages merely because the referenced
brand has strong homepage patterns.

For dense reports, prioritize:

- compact editorial hierarchy over hero-scale marketing hierarchy
- tables, charts, source notes, and findings over CTA sections
- slim section headers and repeated data blocks over big feature cards
- readable print/export behavior over immersive website storytelling

## Use motion only for state

Use motion to explain state changes, not to decorate:

- Prefer 150–300ms transitions.
- Animate `transform` and `opacity`.
- Respect `prefers-reduced-motion`.
- Use one well-timed reveal rather than many scattered animations.

## Delivery checklist

Before delivering, check:

- Clear first read and primary action.
- Consistent tokens.
- No generic AI clichés.
- Responsive layout works.
- Touch targets and focus states exist.
- Text does not overflow.
- Motion is purposeful and not excessive.
