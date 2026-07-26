#!/usr/bin/env python3
"""Offline structural fallback for the open Agent Skills specification."""

import re
import sys
from pathlib import Path

import yaml

MAX_SKILL_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500
ALLOWED_PROPERTIES = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}


def validate_skill(skill_path):
    """Validate the standard SKILL.md contract without replacing skills-ref."""
    skill_path = Path(skill_path)

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, "SKILL.md not found"

    content = (
        skill_md.read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    if not content.startswith("---"):
        return False, "No YAML frontmatter found"

    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return False, "Invalid frontmatter format"

    frontmatter_text = match.group(1)

    try:
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            return False, "Frontmatter must be a YAML dictionary"
    except yaml.YAMLError as e:
        return False, f"Invalid YAML in frontmatter: {e}"

    unexpected_keys = set(frontmatter.keys()) - ALLOWED_PROPERTIES
    if unexpected_keys:
        allowed = ", ".join(sorted(ALLOWED_PROPERTIES))
        unexpected = ", ".join(sorted(unexpected_keys))
        return (
            False,
            f"Unexpected key(s) in SKILL.md frontmatter: {unexpected}. Allowed properties are: {allowed}",
        )

    if "name" not in frontmatter:
        return False, "Missing 'name' in frontmatter"
    if "description" not in frontmatter:
        return False, "Missing 'description' in frontmatter"

    name = frontmatter.get("name")
    if not isinstance(name, str) or not name:
        return False, "Name must be a non-empty string"
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        return (
            False,
            f"Name '{name}' must use lowercase ASCII letters, digits, and single hyphens",
        )
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return (
            False,
            f"Name is too long ({len(name)} characters). "
            f"Maximum is {MAX_SKILL_NAME_LENGTH} characters.",
        )
    if name != skill_path.name:
        return (
            False,
            f"Name '{name}' must match parent directory '{skill_path.name}'",
        )

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        return False, "Description must be a non-empty string"
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return (
            False,
            f"Description is too long ({len(description)} characters). "
            f"Maximum is {MAX_DESCRIPTION_LENGTH} characters.",
        )

    for field in ("license", "allowed-tools"):
        value = frontmatter.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            return False, f"{field} must be a non-empty string when provided"

    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str) or not compatibility.strip():
            return False, "compatibility must be a non-empty string when provided"
        if len(compatibility) > MAX_COMPATIBILITY_LENGTH:
            return (
                False,
                f"Compatibility is too long ({len(compatibility)} characters). "
                f"Maximum is {MAX_COMPATIBILITY_LENGTH} characters.",
            )

    metadata = frontmatter.get("metadata")
    if metadata is not None and (
        not isinstance(metadata, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in metadata.items()
        )
    ):
        return False, "metadata must map string keys to string values"

    return True, "Skill is valid!"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        sys.exit(1)

    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)
