from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..extensions.package_content import package_content_for_model
from ..models import (
    ExtensionDraft,
    ExtensionDraftRevision,
    ExtensionVersion,
    Run,
)


MAX_SKILL_RESOURCE_PAGE_CHARS = 20_000


SKILL_RESOURCE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_skill_resource",
        "description": (
            "Read one text resource from the exact active Skill snapshot. Activate the "
            "Skill first, then use a relative path listed in the activation result only "
            "when its SKILL.md instructions make that resource relevant. Do not eagerly "
            "read every resource. Python scripts can be executed directly with run_python "
            "without reading their source first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "ID or slug of an active Skill in the current Run.",
                },
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1_000,
                    "description": (
                        "Relative resource path from the Skill root, such as "
                        "references/schema.md."
                    ),
                },
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {
                    "type": "integer",
                    "minimum": 500,
                    "maximum": MAX_SKILL_RESOURCE_PAGE_CHARS,
                    "default": 8_000,
                },
            },
            "required": ["skill_id", "path"],
            "additionalProperties": False,
        },
    },
}


def read_skill_resource(
    db: Session,
    *,
    run: Run,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    requested_skill = str(arguments.get("skill_id") or "").strip()
    if not requested_skill:
        raise ValueError("Skill resource를 읽으려면 skill_id가 필요합니다.")
    snapshot = active_skill_snapshot(run, requested_skill)
    package = frozen_skill_package(db, snapshot)
    path = safe_skill_package_path(str(arguments.get("path") or ""))
    if path.casefold() == "skill.md":
        raise ValueError("SKILL.md는 Skill 활성화 결과에서 이미 제공됩니다.")
    if path not in package:
        raise ValueError(f"Skill snapshot에 resource가 없습니다: {path}")

    offset = _bounded_integer(arguments.get("offset"), default=0, minimum=0)
    limit = _bounded_integer(
        arguments.get("limit"),
        default=8_000,
        minimum=500,
        maximum=MAX_SKILL_RESOURCE_PAGE_CHARS,
    )
    content, encoding = package_content_for_model(package[path])
    page = content[offset : offset + limit]
    next_offset = offset + len(page)
    complete = next_offset >= len(content)
    return {
        "skillId": str(snapshot.get("extension_id", "")),
        "slug": str(snapshot.get("slug", "")),
        "digest": str(snapshot.get("digest", "")),
        "path": path,
        "content": page,
        "encoding": encoding,
        "offset": offset,
        "nextOffset": None if complete else next_offset,
        "complete": complete,
        "totalChars": len(content),
    }


def active_skill_snapshot(run: Run, requested: str) -> dict[str, Any]:
    extensions = [
        dict(item)
        for item in run.snapshot_json.get("extensions", [])
        if isinstance(item, Mapping)
    ]
    wrappers = [
        dict(wrapper)
        for server in run.snapshot_json.get("mcp_servers", [])
        if isinstance(server, Mapping)
        and isinstance((wrapper := server.get("skill_wrapper")), Mapping)
    ]
    if run.snapshot_json.get("extension_application") == "all_snapshot":
        active_ids = {str(item.get("extension_id", "")) for item in extensions}
    else:
        active_ids = {
            str(reference.get("reference_id", ""))
            for reference in run.snapshot_json.get("prompt_references", [])
            if isinstance(reference, Mapping) and reference.get("kind") == "skill"
        }
        active_ids.update(
            str(item)
            for item in run.snapshot_json.get("auto_selected_skill_ids", [])
        )
    active_ids.update(str(item.get("extension_id", "")) for item in wrappers)
    selected = next(
        (
            item
            for item in [*extensions, *wrappers]
            if str(item.get("extension_id", "")) in active_ids
            and requested
            in {
                str(item.get("extension_id", "")),
                str(item.get("slug", "")),
            }
        ),
        None,
    )
    if selected is None:
        raise ApiProblem(
            403,
            "skill_not_active",
            "현재 Run에서 활성화되고 고정된 Skill만 사용할 수 있습니다.",
        )
    return selected


def frozen_skill_package(
    db: Session,
    snapshot: Mapping[str, Any],
) -> dict[str, str]:
    extension_id = str(snapshot.get("extension_id") or "")
    digest = str(snapshot.get("digest") or "")
    if snapshot.get("source") == "version":
        version = db.get(ExtensionVersion, str(snapshot.get("version_id") or ""))
        if (
            version is None
            or version.extension_id != extension_id
            or version.package_digest != digest
        ):
            raise ValueError("고정된 Skill version package를 확인할 수 없습니다.")
        package = dict(version.package_json)
    elif snapshot.get("source") == "draft":
        draft_id = str(snapshot.get("draft_id") or "")
        revision_number = snapshot.get("draft_revision")
        revision = (
            db.scalar(
                select(ExtensionDraftRevision).where(
                    ExtensionDraftRevision.draft_id == draft_id,
                    ExtensionDraftRevision.revision_number == revision_number,
                )
            )
            if isinstance(revision_number, int)
            and not isinstance(revision_number, bool)
            else None
        )
        if revision is not None and revision.package_digest == digest:
            package = dict(revision.package_json)
        else:
            draft = db.get(ExtensionDraft, draft_id)
            if (
                draft is None
                or draft.extension_id != extension_id
                or draft.current_revision != revision_number
                or draft.current_digest != digest
            ):
                raise ValueError("고정된 Skill draft package를 확인할 수 없습니다.")
            package = dict(draft.package_json)
    else:
        raise ValueError("지원하지 않는 Skill snapshot source입니다.")
    return {
        safe_skill_package_path(path): content for path, content in package.items()
    }


def safe_skill_package_path(value: str) -> str:
    normalized = str(value).replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or ":" in normalized
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or len(path.parts) > 20
    ):
        raise ValueError("안전하지 않은 Skill package 경로입니다.")
    return path.as_posix()


def _bounded_integer(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("offset과 limit은 정수여야 합니다.")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError("offset 또는 limit이 허용 범위를 벗어났습니다.")
    return value


__all__ = [
    "SKILL_RESOURCE_TOOL_SCHEMA",
    "active_skill_snapshot",
    "frozen_skill_package",
    "read_skill_resource",
    "safe_skill_package_path",
]
