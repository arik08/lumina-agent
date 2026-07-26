# Agent Skills Standard Checklist

Use the current official sources as the authority:

- Specification: <https://agentskills.io/specification>
- Skill creation best practices: <https://agentskills.io/skill-creation/best-practices>
- Script guidance: <https://agentskills.io/skill-creation/using-scripts>
- Evaluation guidance: <https://agentskills.io/skill-creation/evaluating-skills>
- Reference validator: <https://github.com/agentskills/agentskills/tree/main/skills-ref>
- Anthropic example Skills: <https://github.com/anthropics/skills>

## Required package contract

- The Skill is a directory containing `SKILL.md`.
- `SKILL.md` begins with YAML frontmatter and continues with Markdown instructions.
- `name` and `description` are required.
- The parent directory and `name` match exactly.
- `name` is 1-64 characters using lowercase ASCII letters, digits, and single hyphens.
- `description` is 1-1024 characters and explains both capability and activation context.

## Optional standard fields

- `license`: non-empty license name or reference to a bundled license file.
- `compatibility`: 1-500 characters describing material environment requirements.
- `metadata`: string keys mapped to string values for client or organization data.
- `allowed-tools`: experimental, space-separated pre-approved tool declaration.

Do not reject a standard field because a particular client ignores it. Do not treat a
client-specific field as portable unless the open specification adopts it.

## Progressive disclosure

- Catalog: expose only `name` and `description`.
- Activation: load the full `SKILL.md`.
- Resources: load or execute only the files required for the current task.
- Keep `SKILL.md` below 500 lines and roughly 5,000 tokens when practical.
- Use root-relative resource paths and avoid deep chains of references.

## Structural and behavioral proof

1. Run `skills-ref validate <skill-directory>`.
2. Run changed scripts with representative success and failure inputs.
3. Run realistic prompts through the real client activation path.
4. Test both expected triggers and close non-trigger cases.
5. For high-impact publication, compare against a baseline and bind evidence to the exact
   Skill digest and runtime configuration.

The standard validator proves package conformance. It does not prove that the Skill triggers
correctly, completes its workflow, or improves results.
