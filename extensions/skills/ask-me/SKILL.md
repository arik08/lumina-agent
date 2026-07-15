---
name: ask-me
description: Clarify the few user decisions that could materially change a task before executing it. Use when the user explicitly invokes $ask-me or asks for a short preflight interview to align research, reports, documents, skills, automation, implementation, or other work without excessive questioning.
---

# Ask Me

Clarify only what would materially change the result, then execute the requested work.

## Workflow

1. Inspect the conversation, referenced files, workspace, and available tools before asking. Resolve discoverable facts yourself.
2. Separate unresolved items into:
   - **Blocking**: A wrong choice would substantially change the goal, scope, audience, output, cost, or irreversible effect.
   - **Delegatable**: A reasonable default is safe and reversible.
   - **Discoverable**: The answer can be found from available context or tools.
3. Ask only about Blocking items. Make reasonable defaults for Delegatable items and investigate Discoverable items.
4. Call `request_user_input` by itself. Never place a user-facing question in ordinary response text.
5. Normally ask one question and prefer no more than three in the single UI bundle. Use more only when every additional answer is independently necessary before execution. Never exceed ten questions.
6. Give each question two or three distinct options. Put the recommended option first, suffix its label with ` (추천)`, and briefly explain its effect. Do not add custom-answer or AI-judgment options because the UI provides them.
7. After the answer resumes the Run, apply the selected decisions and continue the original task. Briefly restate the agreed direction only when it helps the user verify the result.

## Restraint

- Do not ask about cosmetic preferences, reversible implementation details, or choices with an obvious conventional default.
- Do not ask for information already present in the request, files, project instructions, prior messages, or accessible systems.
- Do not create a separate plan, specification, or intake artifact unless the user requests one.
- Do not use clarification questions for Tool permission or approval; use the normal approval flow.
- If no Blocking item remains, do not manufacture a question. Proceed immediately.
- Prefer a useful assumption over another question when the downside is small.

## Examples

- For broad research, ask about the decision the research must support only when it changes source selection or depth.
- For an HTML report, ask about audience or required content only when the request does not already imply them; choose layout details yourself.
- For a new Skill, ask about triggering behavior or allowed capabilities when those materially affect its contract; infer ordinary package structure and validation steps.
