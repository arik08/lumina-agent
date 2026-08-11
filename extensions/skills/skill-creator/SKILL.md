---
name: skill-creator
description: Create, update, validate, and evaluate portable Agent Skills with standards-compliant SKILL.md files, progressive disclosure, tested scripts, and precise trigger descriptions. Use when a user asks to make, revise, audit, package, or improve an Agent Skill, including Skills that guide MCP-backed programs.
license: license.txt
metadata:
  short-description: Create or update an Agent Skill
---

# Skill Creator

Create Skills against the open Agent Skills specification published at
`https://agentskills.io/specification`. Treat product-specific fields and files as
optional client extensions, not as part of the portable standard.

## Workflow

1. Capture intent from the conversation and existing artifacts before asking questions.
2. Confirm the capability, trigger situations, expected inputs and outputs, dependencies,
   failure behavior, and success criteria. Ask only for information that materially changes
   the design.
3. Decide whether the capability belongs in instructions, bundled resources, or an external
   tool/runtime.
4. Create or revise the Skill.
5. Validate structure with the official reference validator and run every changed script.
6. Exercise the Skill on realistic tasks, inspect the execution trace and output, revise, and
   rerun.
7. Report the validated files, behavioral evidence, remaining environment requirements, and
   any client-specific extensions.

For a standards audit or unfamiliar frontmatter, read
[`references/agent-skills-standard.md`](references/agent-skills-standard.md) before editing.
For Python, large programs, or MCP-backed computation, read
[`references/lumina-runtime-boundaries.md`](references/lumina-runtime-boundaries.md) before
choosing the package layout.

## Design the Skill

Ground the Skill in real expertise: successful task traces, user corrections, project
runbooks, schemas, APIs, failure cases, and existing code. Avoid filling a Skill with generic
advice that the agent already knows.

Choose a coherent unit of work. It should be broad enough to complete a useful workflow and
narrow enough to trigger precisely without conflicting with unrelated Skills.

Allocate content by role:

- Put the essential procedure, non-obvious gotchas, defaults, and validation gates in
  `SKILL.md`.
- Put focused documentation and variant-specific details in `references/`.
- Put executable, deterministic, or repeatedly re-created logic in `scripts/`.
- Put templates, images, lookup data, and files intended for output production in `assets/`.
- Other directories are allowed by the standard when the Skill genuinely needs them.

Do not invent a package-size, file-count, or filename-extension limit and present it as an
Agent Skills rule. Packaging and runtime policies belong to the client or deployment
environment.

## Write `SKILL.md`

Use this portable minimum:

```yaml
---
name: example-skill
description: Perform a specific capability. Use when the user requests the relevant task, input type, or workflow.
---
```

Apply these rules:

- Match `name` to the parent directory. Use 1-64 lowercase ASCII letters, digits, and hyphens;
  do not start or end with a hyphen or use consecutive hyphens.
- Keep `description` between 1 and 1024 characters. State both what the Skill does and when it
  should activate, using realistic task and input keywords.
- Use optional standard fields only when needed: `license`, `compatibility`, `metadata`, and
  experimental `allowed-tools`.
- Keep `metadata` as string keys mapped to string values. Put Lumina-specific source markers,
  such as `lumina-source`, here instead of adding a nonstandard top-level field.
- Use `compatibility` only for material environment requirements; keep it between 1 and 500
  characters.
- Treat `allowed-tools` as experimental and client-dependent.
- Write the body as direct, imperative procedures. Explain why a constraint matters when that
  improves judgment; be exact where an operation is fragile.
- Prefer a working default with a short escape hatch over a menu of equal alternatives.
- Include concrete input/output formats, edge cases, recovery steps, and a
  do-work → validate → fix → revalidate loop when applicable.

Keep `SKILL.md` under 500 lines and about 5,000 tokens when practical. Reference supporting
files with paths relative to the Skill root and state exactly when to read or run each one.
Keep reference chains shallow so the agent can discover required resources without loading
unrelated material.

## Build Scripts for Agent Use

List every script the agent may run and document its purpose and invocation in `SKILL.md`.
Resolve paths from the Skill root.

For Python scripts:

- Use `python` in Windows-compatible instructions. Use `uv run` when the Skill declares and
  requires an isolated PEP 723 environment.
- Accept input through arguments, stdin, or files; never block on interactive prompts.
- Provide concise `--help`, validate inputs, and return a nonzero exit code on failure.
- Write machine-readable results to stdout and diagnostics to stderr.
- Pin or bound dependencies and document the required Python version.
- Handle retries safely where possible; add `--dry-run` for destructive or stateful work.
- Test the actual entry point with representative valid, invalid, and boundary inputs.

A bundled script can be executed without first placing its source in model context, but it is
still part of the Skill package and its client-enforced permissions. Do not describe
`scripts/` as a general-purpose untrusted-code sandbox.

## Separate Skill Guidance from MCP Runtime

Use a bundled script for portable helpers that reasonably travel with the Skill. Use an MCP
server or another managed external runtime when the program is large, proprietary,
dependency-heavy, independently deployed, requires durable jobs, or needs operational
controls beyond a Skill package.

For an MCP-backed Skill:

1. Ask for or derive the user-facing inputs.
2. Validate and normalize them against the MCP tool's schema.
3. Call the selected MCP tool; do not pretend the Skill itself executed the external program.
4. Treat the tool result as data, check its status and completeness, and interpret it for the
   user.
5. Explain partial results, failures, retries, and provenance.

In Lumina, link a Skill wrapper to one MCP definition with:

```yaml
metadata:
  lumina-source: skill-mcp:company-calculator
```

Repository에 함께 제공하는 MCP wrapper는 일반 Skill 위치에 만들지 않습니다. MCP의
`extensions/mcp/<mcp-slug>/skills/<wrapper>/SKILL.md`에 두고 같은 package의
`mcp.json`, 선택적 `runtime/`과 함께 이동·검증·삭제할 수 있게 유지합니다.

Keep a large application, model, or runtime image outside the Skill. The Skill may contain
the input contract, question sequence, validation rules, tool-call procedure, and result
interpretation guidance. This separation supports a 200 MB or larger company program without
misrepresenting that binary as the Skill standard.

## Lumina Client Metadata

`agents/openai.yaml` is optional Lumina/OpenAI-style presentation and policy metadata. It is
not required by the Agent Skills specification and must not replace standard frontmatter.

Create it only when the target client needs UI metadata, MCP dependency declaration, or
invocation policy. Read
[`references/openai_yaml.md`](references/openai_yaml.md) before generating it. Keep portable
requirements in `SKILL.md`; keep product-only fields in `agents/openai.yaml`.

## Initialize

In Lumina, create or revise the package with the `create_skill` tool. Unless the user explicitly
requests another supported destination, persist repository-style Skill files under
`extensions/skills/<skill-name>/`. Never choose `.skills/` or `skills/` for a Lumina Skill.
Do not run `scripts/init_skill.py` with `run_python` to create a persistent Skill: Skill Python
execution uses a temporary directory that is removed after the Tool call. Pass `SKILL.md` and
the required relative resource files through `create_skill`; verify its returned `packageRoot`,
Draft revision, and file list.

Outside Lumina, choose the target directory with the user when placement is not already
implied. For a personal Codex Skill, use the configured Codex Skills directory.

When a client exposes a persistent filesystem instead of Lumina's `create_skill` tool, run:

```powershell
python scripts/init_skill.py example-skill --path <output-directory>
```

Add only the resource directories that are needed:

```powershell
python scripts/init_skill.py example-skill --path <output-directory> --resources scripts,references
```

Generate optional client metadata only when requested:

```powershell
python scripts/init_skill.py example-skill --path <output-directory> --openai-interface
```

Replace or remove all placeholders before validation.

## Validate

Run the official reference validator:

```powershell
skills-ref validate <path-to-skill>
```

If `skills-ref` is not installed, use its official repository as documented at
`https://agentskills.io/specification`, or run the bundled structural fallback:

```powershell
python scripts/quick_validate.py <path-to-skill>
```

The fallback is not a substitute for official validation. Fix every validation error, then
rerun the command.

Also verify:

- Every referenced path exists and uses the intended capitalization.
- Every changed script executes successfully and its failure messages are actionable.
- Dependencies and compatibility requirements are explicit and reproducible.
- Secrets, credentials, private inputs, generated outputs, caches, and large runtime artifacts
  are not accidentally packaged.
- Product-specific metadata is clearly separated from the portable Skill contract.

## Evaluate and Iterate

Create 2-3 realistic task prompts for a basic revision and broader positive and near-miss
negative cases for a published or high-impact Skill. For each task:

1. Run the Skill through the real activation and tool path.
2. Inspect the full trace, not only the final response.
3. Check trigger accuracy, workflow compliance, output correctness, retries, latency, and
   unnecessary context or tool use.
4. For objective or high-impact work, compare against a no-Skill or previous-version baseline
   and retain assertions and artifacts by Skill digest.
5. Revise reusable instructions or scripts rather than overfitting to one prompt.
6. Rerun the full set after each material change.

Use the dedicated Skill evaluator when available for systematic benchmarking. Static lint and
frontmatter validation prove structure, not behavioral quality.
