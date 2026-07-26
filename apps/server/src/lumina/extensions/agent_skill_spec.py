from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping

from yaml import YAMLError, safe_load  # type: ignore[import-untyped]


_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class AgentSkillSpecError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AgentSkillDocument:
    name: str
    description: str
    body: str
    license: str | None
    compatibility: str | None
    metadata: Mapping[str, str]
    allowed_tools: str | None


def parse_agent_skill(
    content: str,
    *,
    expected_name: str | None = None,
) -> AgentSkillDocument:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    match = _FRONTMATTER.match(normalized)
    if match is None:
        raise AgentSkillSpecError("SKILL.md must start with YAML frontmatter.")
    try:
        raw = safe_load(match.group(1))
    except YAMLError as exc:
        raise AgentSkillSpecError("SKILL.md frontmatter is not valid YAML.") from exc
    if not isinstance(raw, dict):
        raise AgentSkillSpecError("SKILL.md frontmatter must be a mapping.")

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise AgentSkillSpecError("SKILL.md frontmatter requires name.")
    if len(name) > 64 or not _SKILL_NAME.fullmatch(name):
        raise AgentSkillSpecError(
            "SKILL.md name must be 1-64 lowercase letters, numbers, or hyphens."
        )
    if expected_name is not None and name != expected_name:
        raise AgentSkillSpecError(
            "SKILL.md name must match the Skill directory name or slug."
        )

    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        raise AgentSkillSpecError("SKILL.md frontmatter requires description.")
    description = " ".join(description.split())
    if len(description) > 1_024:
        raise AgentSkillSpecError(
            "SKILL.md description must be at most 1024 characters."
        )

    license_value = _optional_string(raw.get("license"), field="license")
    compatibility = _optional_string(
        raw.get("compatibility"),
        field="compatibility",
        maximum=500,
    )
    allowed_tools = _optional_string(
        raw.get("allowed-tools"),
        field="allowed-tools",
    )
    metadata_value = raw.get("metadata", {})
    if not isinstance(metadata_value, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in metadata_value.items()
    ):
        raise AgentSkillSpecError(
            "SKILL.md metadata must map string keys to string values."
        )
    return AgentSkillDocument(
        name=name,
        description=description,
        body=normalized[match.end() :].strip(),
        license=license_value,
        compatibility=compatibility,
        metadata=dict(metadata_value),
        allowed_tools=allowed_tools,
    )


def ensure_agent_skill_package(
    package: Mapping[str, str],
    *,
    expected_name: str,
    fallback_description: str,
) -> tuple[dict[str, str], AgentSkillDocument]:
    normalized = dict(package)
    skill_path = next(
        (path for path in normalized if path.casefold() == "skill.md"),
        None,
    )
    if skill_path is None:
        raise AgentSkillSpecError("Skill package requires SKILL.md.")
    content = normalized[skill_path]
    if _FRONTMATTER.match(content.replace("\r\n", "\n").replace("\r", "\n")) is None:
        description = " ".join(fallback_description.split())
        if not description:
            raise AgentSkillSpecError(
                "A description is required to create standard SKILL.md frontmatter."
            )
        content = (
            "---\n"
            f"name: {expected_name}\n"
            f"description: {json.dumps(description, ensure_ascii=False)}\n"
            "---\n\n"
            f"{content.lstrip()}"
        )
        normalized[skill_path] = content
    document = parse_agent_skill(content, expected_name=expected_name)
    return dict(sorted(normalized.items())), document


def skill_resource_paths(package: Mapping[str, str]) -> list[str]:
    return sorted(path for path in package if path.casefold() != "skill.md")


def _optional_string(
    value: Any,
    *,
    field: str,
    maximum: int | None = None,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise AgentSkillSpecError(f"SKILL.md {field} must be a non-empty string.")
    if maximum is not None and len(value) > maximum:
        raise AgentSkillSpecError(
            f"SKILL.md {field} must be at most {maximum} characters."
        )
    return value


__all__ = [
    "AgentSkillDocument",
    "AgentSkillSpecError",
    "ensure_agent_skill_package",
    "parse_agent_skill",
    "skill_resource_paths",
]
