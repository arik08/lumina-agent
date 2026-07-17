---
name: idea-orchestrator
description: Systematically generate, combine, and rank practical ideas by routing a problem through two or three complementary methods such as TRIZ, SIT, morphological analysis, SCAMPER, Jobs to Be Done, Design Thinking, Six Thinking Hats, reverse thinking, or Five Whys. Use for product, service, process, business, UX, strategy, or technical innovation when the user asks for ideas, alternatives, concepts, creative problem solving, brainstorming, innovation workshops, or a structured ideation method. Do not use for simple factual questions or when the user already requests one narrowly defined solution with no exploration.
---

# Idea Orchestrator

Select a small combination of methods that fits the problem, generate ideas independently, then synthesize the results into testable recommendations. Respond in the user's language.

## Workflow

1. Extract the target outcome, affected users, constraints, available evidence, and decision horizon. State assumptions instead of inventing facts.
2. Reframe the request as a specific challenge. If the stated problem is only a symptom, use Five Whys or Design Thinking before ideating.
3. Read [method-selector.md](references/method-selector.md) and select two or three complementary methods. Never run every method by default.
4. Load only the selected method references:
   - For SCAMPER, Six Thinking Hats, Design Thinking, Jobs to Be Done, or Five Whys, read the matching `references/upstream-*.md` file.
   - For TRIZ, SIT/ASIT, morphological analysis, first principles, reverse thinking, rapid ideation, or random/forced connections, read [structured-methods.md](references/structured-methods.md).
5. Apply each selected method independently so one framing does not collapse the others into the same ideas. Generate both safe and non-obvious options.
6. Merge duplicates, preserve materially different mechanisms, and explain which method produced each surviving idea.
7. Score the shortlist using impact, feasibility, differentiation, evidence confidence, and time-to-learn. Do not disguise guesses as precise measurements.
8. Return the result using [output-format.md](references/output-format.md), ending with a small reversible experiment for the leading idea.

## Quality Rules

- Prefer concrete mechanisms over slogans such as "use AI" or "improve UX."
- Resolve trade-offs explicitly; do not hide a worsened constraint.
- Separate observed facts, assumptions, hypotheses, and ideas.
- Include at least one idea that removes work, a step, or a feature instead of adding more.
- Keep a deliberately unusual idea when it reveals a useful principle, even if it is not the final recommendation.
- Ask a clarifying question only when a missing decision would materially change method selection; otherwise proceed with stated assumptions.

## Upstream Method Sources

Several detailed method cards are vendored from the MIT-licensed `neurofoo/agent-skills` repository at a pinned commit. Treat them as method references, not as separate Skills. See [upstream-sources.md](references/upstream-sources.md) for attribution, integrity checks, and the controlled refresh procedure.
