---
name: grill-me
description: Pressure-test and sharpen a plan, decision, or idea through a focused adaptive interview. Use only when the user explicitly invokes $grill-me or directly asks to be grilled; do not activate for ordinary clarification, factual questions, or direct implementation requests.
license: MIT; see LICENSE
---

# Grill Me

Turn a vague or weakly tested proposal into confirmed shared understanding before acting on it.

This Skill adapts Matt Pocock's `grill-me` and `grilling` workflow to Lumina's durable confirmation-question UI.

## Interview

1. Inspect the conversation, referenced files, workspace, and available tools first. Finding facts is the agent's job; ask the user only for decisions, preferences, or information that cannot be discovered.
2. Map the proposal as a design tree. A decision can lead to dependent decisions that should not be asked until their prerequisites are settled.
3. Work the tree in rounds. The frontier is the set of material decisions whose prerequisites are already settled. Ask the useful frontier together instead of artificially splitting independent questions across multiple rounds.
4. Keep each round focused. Prefer the smallest set of high-leverage questions that can materially change the goal, scope, feasibility, risk, success criteria, or next action. Merge equivalent branches and skip cosmetic, reversible, already answered, or discoverable details.
5. Call `request_user_input` by itself for every user-facing question. Never place an interview question in ordinary visible response text.
6. Give every question two or three distinct options. Put the recommended answer first, suffix its label with ` (추천)`, and briefly explain the trade-off. The UI already provides custom-answer and AI-judgment paths.
7. After each submitted round, challenge vague answers, contradictions, hidden assumptions, missing ownership, failure modes, and second-order effects. Recompute the frontier from the answers instead of following a fixed checklist.
8. Open another round when earlier answers unlock or materially reshape dependent decisions. Never repeat a resolved question.
9. Never put more than twenty questions in one question card. There is no cumulative question limit across the Run: after the user answers, open another card when material dependent decisions remain. Twenty is a per-round ceiling, not a target; stop as soon as the material tree is resolved and the proposal is actionable.
10. Present the resulting shared understanding and request confirmation through `request_user_input`. Do not implement or create side-effecting artifacts before confirmation. After confirmation, continue only with work already authorized by the user's original request.

## Boundaries

- Be direct and constructive, not hostile or performative.
- Do not use this Skill for Tool permission or approval; use the normal approval flow.
- Do not create a separate interview log unless the user requests one. The Run already preserves submitted question cards and answers.
- If the user asks to stop grilling or proceed with reasonable assumptions, stop the interview and respect that instruction.
