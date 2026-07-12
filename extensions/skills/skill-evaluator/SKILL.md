---
name: skill-evaluator
description: Use when assessing, installing, updating, or reviewing Agent Skills, Codex Skills, MyHarness skills, or any .skills/**/SKILL.md folder for trigger precision, safety, progressive disclosure, resource layout, UI metadata, naming, conflicts with existing skills, malicious or overbroad instructions, maintainability, and readiness before enabling or sharing.
---

# Skill Evaluator

## Evaluation Stance

Review skills like code: lead with concrete risks, line references, and practical fixes. Prefer small, trigger-specific skills over broad always-on guidance. Treat scripts and assets as part of the trusted execution surface.

## Workflow

1. Inventory the skill folder: `SKILL.md`, `agents/openai.yaml`, `scripts/`, `references/`, and `assets/`.
2. Run the bundled linter when possible:

   ```bash
   python .skills/skill-evaluator/scripts/skill_lint.py .skills/example-skill
   ```

3. Read `SKILL.md` and check that frontmatter has only `name` and `description`, with a precise trigger description that says when to use and when not to use the skill.
4. Compare the skill name and description against existing skills to find overlap, shadowing, or trigger ambiguity.
5. Inspect referenced scripts before recommending execution. Look for shell injection, destructive commands, network downloads, credential access, hidden payloads, prompt-injection text, and broad filesystem operations.
6. Check progressive disclosure: keep core workflow in `SKILL.md`; move long optional details to one-level `references/` files; avoid README-style clutter.
7. Check MyHarness compatibility: lowercase hyphenated name, UTF-8 text, no source-translation edits for UI labels, and concise `agents/openai.yaml` metadata when present.
8. If the skill is complex or high-risk, forward-test it with a realistic user task before calling it ready.

## Finding Severity

- P0: Must not install or enable. Malicious, destructive, credential-exfiltrating, or silently changes external systems.
- P1: High risk. Can trigger broadly, run unsafe scripts, overwrite user data, or mislead the agent on important workflows.
- P2: Quality issue. Ambiguous triggers, missing validation, stale references, excessive context, or maintainability gaps.
- P3: Polish. Naming, metadata, examples, or minor clarity improvements.

## Readiness Criteria

A skill is ready when:

- The trigger is specific enough that unrelated tasks will not load it.
- The body gives only the non-obvious procedure an agent needs.
- Scripts are inspectable, deterministic, scoped, and fail clearly.
- Resources are referenced from `SKILL.md` and are not bulk-loaded by default.
- Installation does not overwrite unrelated user changes.
- Validation output is clean or residual risks are explicitly documented.

## Report Format

Start with the verdict: `ready`, `needs changes`, or `do not install`. Then list findings by severity with file and line references. Finish with the smallest concrete patch plan or acceptance note.
