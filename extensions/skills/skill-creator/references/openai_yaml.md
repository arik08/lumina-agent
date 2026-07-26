# `agents/openai.yaml` fields

`agents/openai.yaml` is optional Lumina/OpenAI-style client metadata for the machine or
harness to read, not the agent. It is not part of the portable Agent Skills specification
and must not replace standard `SKILL.md` frontmatter.

## Full example

```yaml
interface:
  display_name: "Optional user-facing name"
  short_description: "Optional user-facing description"
  icon_small: "./assets/small-400px.png"
  icon_large: "./assets/large-logo.svg"
  brand_color: "#3B82F6"
  default_prompt: "Use $skill-name to complete the relevant workflow."

dependencies:
  tools:
    - type: "mcp"
      value: "github"
      description: "GitHub MCP server"
      transport: "streamable_http"
      url: "https://api.githubcopilot.com/mcp/"

policy:
  allow_implicit_invocation: true
```

## Field descriptions and constraints

Quote string values and keep keys unquoted.

- `interface.display_name`: Human-facing title shown in Skill lists and chips.
- `interface.short_description`: Human-facing UI description of 25-64 characters.
- `interface.icon_small`: Small icon path relative to the Skill root.
- `interface.icon_large`: Large icon path relative to the Skill root.
- `interface.brand_color`: Hex color used for UI accents.
- `interface.default_prompt`: Short example prompt that explicitly mentions `$skill-name`.
- `dependencies.tools[].type`: Dependency category. Lumina currently supports `mcp`.
- `dependencies.tools[].value`: MCP identifier.
- `dependencies.tools[].description`: Human-readable dependency purpose.
- `dependencies.tools[].transport`: MCP connection type.
- `dependencies.tools[].url`: MCP server URL when applicable.
- `policy.allow_implicit_invocation`: When false, exclude the Skill from implicit model
  selection while still allowing explicit invocation. The default is true.

Use `metadata.lumina-source` in `SKILL.md` for the portable wrapper-to-MCP source marker.
Use `dependencies.tools` only for client-side connection metadata.
