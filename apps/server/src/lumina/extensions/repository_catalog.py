from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import REPOSITORY_ROOT
from ..mcp.service import (
    add_configuration_revision,
    approve_revision,
    create_definition,
    normalize_slug,
    validate_configuration,
)
from ..models import (
    Extension,
    ExtensionVersion,
    McpConfigurationRevision,
    McpDefinition,
    SkillOwnership,
    User,
    utc_now,
)
from .service import normalize_package, package_digest


_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".js",
    ".mjs",
    ".ts",
    ".tsx",
}
_IGNORED_PARTS = {".git", "__pycache__", "node_modules", "vendor", ".venv"}


def _frontmatter(text: str) -> dict[str, str]:
    match = _FRONTMATTER.match(text.replace("\r\n", "\n"))
    if not match:
        return {}
    result: dict[str, str] = {}
    active_key: str | None = None
    for raw_line in match.group(1).splitlines():
        if raw_line[:1].isspace() and active_key:
            result[active_key] = f"{result[active_key]} {raw_line.strip()}".strip()
            continue
        key, separator, value = raw_line.partition(":")
        if separator and key.strip() in {"name", "description"}:
            active_key = key.strip()
            cleaned = value.strip().strip("'\"")
            result[active_key] = "" if cleaned in {">", "|", ">-", "|-"} else cleaned
        else:
            active_key = None
    return result


def _catalog_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = str(item).strip().removeprefix("#").strip()
        if not tag or tag in tags:
            continue
        tags.append(tag[:24])
        if len(tags) == 3:
            break
    return tags


def _skill_package(folder: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in _TEXT_SUFFIXES:
            continue
        relative = path.relative_to(folder)
        if any(part in _IGNORED_PARTS for part in relative.parts):
            continue
        if path.stat().st_size > 500_000:
            continue
        try:
            files[relative.as_posix()] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    return normalize_package(files)


def sync_repository_skills(
    db: Session, *, admin: User, root: Path | None = None
) -> int:
    skills_root = (root or REPOSITORY_ROOT) / "extensions" / "skills"
    if not skills_root.is_dir():
        return 0
    translations_path = skills_root / "catalog.ko.json"
    translations = (
        json.loads(translations_path.read_text(encoding="utf-8"))
        if translations_path.is_file()
        else {}
    )
    tags_path = skills_root / "catalog.tags.json"
    tags_by_slug = (
        json.loads(tags_path.read_text(encoding="utf-8")) if tags_path.is_file() else {}
    )
    changed = 0
    for folder in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_md = folder / "SKILL.md"
        if not skill_md.is_file():
            continue
        package = _skill_package(folder)
        digest = package_digest(package)
        metadata = _frontmatter(package["SKILL.md"])
        slug = (
            re.sub(
                r"[^a-z0-9]+", "-", metadata.get("name", folder.name).casefold()
            ).strip("-")
            or folder.name
        )
        description = str(translations.get(slug) or metadata.get("description", ""))
        manifest = {
            "source": "repository",
            "sourcePath": folder.relative_to(root or REPOSITORY_ROOT).as_posix(),
            "category": "기본 제공",
            "tags": _catalog_tags(tags_by_slug.get(slug)),
            "publisher": "Lumina",
            "fileCount": len(package),
        }
        extension = db.scalar(
            select(Extension).where(
                Extension.owner_user_id == admin.id, Extension.slug == slug
            )
        )
        if extension is None:
            extension = Extension(
                kind="skill",
                slug=slug,
                name=metadata.get("name", folder.name),
                description=description,
                owner_user_id=admin.id,
                creator_user_id=admin.id,
                organization_id=admin.organization_id,
                visibility="organization",
                publisher_user_id=admin.id,
            )
            db.add(extension)
            db.flush()
            db.add(
                SkillOwnership(
                    skill_id=extension.id,
                    principal_type="user",
                    principal_id=admin.id,
                    role="owner",
                    created_by_user_id=admin.id,
                )
            )
        latest = db.scalar(
            select(ExtensionVersion)
            .where(ExtensionVersion.extension_id == extension.id)
            .order_by(ExtensionVersion.version_number.desc())
        )
        extension.name = metadata.get("name", folder.name)
        extension.description = description
        extension.visibility = "organization"
        extension.publisher_user_id = admin.id
        if (
            latest is not None
            and latest.package_digest == digest
            and all(
                latest.manifest_json.get(key) == value
                for key, value in manifest.items()
            )
        ):
            continue
        version = ExtensionVersion(
            extension_id=extension.id,
            version_number=(latest.version_number + 1 if latest else 1),
            parent_version_id=latest.id if latest else None,
            package_json=package,
            package_digest=digest,
            manifest_json=manifest,
            status="published",
            created_by_user_id=admin.id,
            published_at=utc_now(),
        )
        db.add(version)
        db.flush()
        extension.latest_published_version_id = version.id
        changed += 1
    db.flush()
    return changed


def _declared_python_tools(
    raw: dict[str, Any], repository_root: Path
) -> list[dict[str, Any]]:
    args = [str(item) for item in raw.get("args", [])]
    script = next(
        (repository_root / item for item in args if item.endswith(".py")), None
    )
    if script is None or not script.is_file():
        return []
    source = script.read_text(encoding="utf-8")
    names = re.findall(
        r"@\w+\.tool\(\)\s*\ndef\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", source
    )
    return [
        {
            "name": name,
            "description": f"{name.replace('_', ' ')} 도구",
            "input_schema": {"type": "object", "additionalProperties": True},
        }
        for name in names
    ]


def _mcp_configuration(raw: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    transport = "streamable_http" if raw.get("type") == "streamable_http" else "stdio"
    command = (
        [str(raw.get("command", "")), *[str(item) for item in raw.get("args", [])]]
        if transport == "stdio"
        else []
    )
    return {
        "transport": transport,
        "command": [item for item in command if item],
        "url_template": raw.get("url") if transport == "streamable_http" else None,
        "allowed_hosts": raw.get("allowedHosts", []),
        "allowed_ip_ranges": raw.get("allowedIpRanges", []),
        "header_templates": raw.get("headers", {}),
        "tools": raw.get("tools", []) or _declared_python_tools(raw, repository_root),
        "required_secret_names": raw.get("requiredSecretNames", []),
        "timeout_seconds": raw.get("timeoutSeconds", 30),
    }


def sync_repository_mcp(db: Session, *, admin: User, root: Path | None = None) -> int:
    repository_root = root or REPOSITORY_ROOT
    mcp_root = repository_root / "extensions" / "mcp"
    if not mcp_root.is_dir():
        return 0
    changed = 0
    for path in sorted(mcp_root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for slug, raw in payload.get("mcpServers", {}).items():
            catalog_slug = normalize_slug(slug)
            configuration = _mcp_configuration(raw, repository_root)
            if not configuration["tools"]:
                continue
            _, digest = validate_configuration(configuration)
            definition = db.scalar(
                select(McpDefinition).where(
                    McpDefinition.organization_id == admin.organization_id,
                    McpDefinition.slug == catalog_slug,
                )
            )
            if definition is None:
                definition, revision = create_definition(
                    db,
                    user=admin,
                    name=slug.replace("-", " ").title(),
                    slug=catalog_slug,
                    description=str(raw.get("description", "")),
                    configuration=configuration,
                )
            else:
                current = (
                    db.get(McpConfigurationRevision, definition.current_revision_id)
                    if definition.current_revision_id
                    else None
                )
                if current is not None and current.config_digest == digest:
                    continue
                revision = add_configuration_revision(
                    db,
                    user=admin,
                    definition_id=definition.id,
                    configuration=configuration,
                )
            approve_revision(
                db, user=admin, definition_id=definition.id, revision_id=revision.id
            )
            changed += 1
    db.flush()
    return changed


def sync_repository_catalog(
    db: Session, *, admin: User, root: Path | None = None
) -> tuple[int, int]:
    return (
        sync_repository_skills(db, admin=admin, root=root),
        sync_repository_mcp(db, admin=admin, root=root),
    )
