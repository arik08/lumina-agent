---
name: ask-me
description: Clarify a user's intent through adaptive question-and-answer before and, when necessary, during execution. Use when the user explicitly invokes $ask-me, asks to be interviewed or questioned, requests personalized guidance without facts that could materially change the recommendation, gives an underspecified search or retrieval request, wants a plan or design stress-tested, or needs research, reports, documents, skills, automation, implementation, or other work made concrete without avoidable assumptions.
---

# Ask Me

Turn the user's intent into an actionable execution contract, then complete and verify the work.

## Workflow

1. Inspect the conversation, referenced files, workspace, and available tools before asking. Resolve discoverable facts yourself.
2. Separate unresolved items into:
   - **Blocking**: A wrong choice would substantially change the goal, scope, audience, output, cost, or irreversible effect.
   - **Delegatable**: A reasonable default is safe and reversible.
   - **Discoverable**: The answer can be found from available context or tools.
3. Ask only about Blocking items. Make reasonable defaults for Delegatable items and investigate Discoverable items.
   - Treat missing user-specific facts as Blocking when the user asks what they personally should do, choose, prioritize, diagnose, respond to, or plan and those facts could materially change the recommendation, urgency, safety, scope, or next action.
   - Do not substitute a generic conditional checklist for this intake. Role-play framing or an assigned profession does not provide the person's facts.
   - Treat a search or retrieval request as Blocking when the conversation does not identify a useful target. Before using files, enterprise search, MCP, or web search, ask for the highest-information missing criterion such as subject, purpose, scope, recency, owner, or document type. Do not ask for filters already implied by the conversation or selected context.
4. Choose the question cadence from the decision structure:
   - If no Blocking item remains, proceed without asking.
   - If multiple Blocking items are independent and already known, ask them together, normally no more than three.
   - Represent each independent fact or decision as its own question in that bundle. Never combine several requested facts into one prompt or free-form answer instruction.
   - For an explicit interview or intake, include every currently foreseeable high-value question in the first bundle, up to the ten-question Run limit. Do not intentionally split known questions across repeated submit-and-wait cycles.
   - Open a later question bundle only if an answer reveals a material Blocking question that could not reasonably have been anticipated before the first bundle.
5. Call `request_user_input` by itself for every user-facing question. Never place a question in ordinary response text.
6. Give each question two or three distinct options. Put the recommended option first, suffix its label with ` (추천)`, and briefly explain its effect. Do not add custom-answer or AI-judgment options because the UI provides them.
7. Stop questioning when the goal, material constraints, and success conditions are actionable, when the user asks to proceed, or when ten total questions have been asked. Never repeat a resolved question.
8. Treat the answers as the execution contract. Execute the original task and verify the result against that contract.
9. Re-enter the question UI only when execution reveals a new Blocking decision that could not reasonably have been anticipated and cannot be resolved safely. Otherwise correct the work yourself and finish it.

## Restraint

- Do not ask about cosmetic preferences, reversible implementation details, or choices with an obvious conventional default.
- Do not ask for information already present in the request, files, project instructions, prior messages, or accessible systems.
- Keep the execution contract in Run context; do not create a separate plan, specification, or intake artifact unless the user requests one.
- Do not use clarification questions for Tool permission or approval; use the normal approval flow.
- Prefer a useful assumption over another question when the downside is small.
- Do not trigger intake for general knowledge, clearly hypothetical examples, open brainstorming without a personal decision, or requests that already contain enough facts for a responsible answer.
- Do not ask whether to continue after every answer. Continue automatically until another material decision is required or the work is ready to execute.

## Examples

- For broad research, ask about the decision the research must support only when it changes source selection or depth.
- For an HTML report, ask about audience or required content only when the request does not already imply them; choose layout details yourself.
- For a new Skill, ask about triggering behavior or allowed capabilities when those materially affect its contract; infer ordinary package structure and validation steps.
- For an interview, intake, plan, or design stress test, gather all currently foreseeable high-value questions in one bundle; open another bundle only for a material branch that the answers newly reveal.
- For personalized consequential guidance, first ask only for the facts that could change the recommended next action; do not answer with a forest of `if` branches in place of intake.
- For a bare request such as `find a document`, ask what the document should be about or support before invoking retrieval; if the preceding conversation already identifies it, search directly.
