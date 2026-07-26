# Lumina Skill and Runtime Boundaries

Read this reference when a Skill includes Python, substantial dependencies, or an MCP-backed
company program.

## Choose the execution boundary

| Need | Put it in |
| --- | --- |
| Reusable instructions, input questions, validation, tool-call sequence, interpretation | `SKILL.md` |
| Focused schemas, domain rules, examples, API notes | `references/` |
| Portable deterministic helper that travels with the Skill | `scripts/` |
| Output template, lookup data, image, static resource | `assets/` |
| Large/proprietary program, managed dependencies, durable or high-resource compute | MCP or managed worker runtime |

The Agent Skills standard does not define a 5 MB package limit. Lumina deployment policy may
still impose operational limits, but those must be documented as client policy rather than
presented as part of the standard.

## Bundled Python

Use `run_python` only for a Python entry point from the exact active Skill snapshot. Declare
the required execution profile and compatibility. Keep inputs explicit and outputs bounded.
Write structured results to stdout and diagnostics to stderr.

The standard profile is appropriate for ordinary helpers. The heavy profile is an
administrator-enabled Lumina execution option, not an Agent Skills field. It still runs as a
managed child process and is not equivalent to an OS security sandbox or a durable batch
platform.

## MCP-backed programs

Use MCP for a large, independently versioned program such as a 200 MB company calculator.
The MCP deployment owns the program, dependencies, compute limits, secrets, job lifecycle,
and runtime digest. The Skill wrapper owns:

1. User intent and required input collection.
2. The input schema and clarification sequence.
3. Validation and normalization before the tool call.
4. Selection of the exact MCP tool.
5. Status, error, and partial-result handling.
6. Interpretation of structured output for the user.

Link the wrapper through standard metadata:

```yaml
metadata:
  lumina-source: skill-mcp:company-calculator
```

Do not expose the same capability as unrelated duplicate Skill and MCP entries. Keep the
Skill's source link and the MCP definition synchronized and snapshot both sides for a Run.
