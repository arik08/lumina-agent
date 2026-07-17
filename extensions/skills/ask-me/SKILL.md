---
name: ask-me
description: Clarify a user's intent through adaptive question-and-answer before and, when necessary, during execution. Use when the user explicitly invokes $ask-me, asks to be interviewed or questioned, wants a plan or design stress-tested, or needs research, reports, documents, skills, automation, implementation, or other work made concrete without avoidable assumptions.
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
4. Choose the question cadence from the decision structure:
   - If no Blocking item remains, proceed without asking.
   - If multiple Blocking items are independent and already known, ask them together, normally no more than three.
   - If the next useful question depends on the previous answer, ask exactly one, incorporate the answer, and call the question UI again for the next unresolved branch.
5. Call `request_user_input` by itself for every user-facing question. Never place a question in ordinary response text.
6. Give each question two or three distinct options. Put the recommended option first, suffix its label with ` (추천)`, and briefly explain its effect. Do not add custom-answer or AI-judgment options because the UI provides them.
7. Stop questioning when the goal, material constraints, and success conditions are actionable, when the user asks to proceed, or when ten total questions have been asked. Never repeat a resolved question.
8. Treat the answers as the execution contract. Execute the original task and verify the result against that contract.
9. Re-enter the question UI only when execution reveals a new Blocking decision that cannot be resolved safely. Otherwise correct the work yourself and finish it.

## Restraint

- Do not ask about cosmetic preferences, reversible implementation details, or choices with an obvious conventional default.
- Do not ask for information already present in the request, files, project instructions, prior messages, or accessible systems.
- Keep the execution contract in Run context; do not create a separate plan, specification, or intake artifact unless the user requests one.
- Do not use clarification questions for Tool permission or approval; use the normal approval flow.
- Prefer a useful assumption over another question when the downside is small.
- Do not ask whether to continue after every answer. Continue automatically until another material decision is required or the work is ready to execute.

## Examples

- For broad research, ask about the decision the research must support only when it changes source selection or depth.
- For an HTML report, ask about audience or required content only when the request does not already imply them; choose layout details yourself.
- For a new Skill, ask about triggering behavior or allowed capabilities when those materially affect its contract; infer ordinary package structure and validation steps.
- For a plan or design stress test, walk one unresolved decision branch at a time until dependencies and success conditions are clear, then execute the agreed work.
