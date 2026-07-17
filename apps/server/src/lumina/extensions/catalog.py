from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..models import (
    Extension,
    ExtensionInstallation,
    ExtensionVersion,
    Run,
    User,
    UserSetting,
)
from .service import can_manage_skill, extension_access_query, require_extension


CatalogSort = Literal["popular", "runs", "likes", "recent", "name"]
_LIKE_KEY_PREFIX = "marketplace.skill.like."


def _like_key(extension_id: str) -> str:
    return f"{_LIKE_KEY_PREFIX}{extension_id}"


def _manifest_tags(manifest: dict[str, Any]) -> list[str]:
    raw_tags = manifest.get("tags")
    if not isinstance(raw_tags, list):
        return []
    tags: list[str] = []
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, str):
            continue
        tag = raw_tag.strip().removeprefix("#")[:40]
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) == 8:
            break
    return tags


def _manifest_category(manifest: dict[str, Any]) -> str:
    value = manifest.get("category")
    if isinstance(value, str) and value.strip():
        return value.strip().removeprefix("#")[:80]
    return "미분류"


def _applied_skill_ids(snapshot: dict[str, Any]) -> set[str]:
    extensions = [
        item
        for item in snapshot.get("extensions", [])
        if isinstance(item, dict) and str(item.get("extension_id", ""))
    ]
    if snapshot.get("extension_application") == "all_snapshot":
        return {str(item["extension_id"]) for item in extensions}
    explicit_ids = {
        str(item.get("reference_id"))
        for item in snapshot.get("prompt_references", [])
        if isinstance(item, dict)
        and item.get("kind") == "skill"
        and item.get("reference_id")
    }
    auto_ids = {
        str(item)
        for item in snapshot.get("auto_selected_skill_ids", [])
        if str(item)
    }
    return explicit_ids | auto_ids


def _run_counts(
    db: Session, *, organization_id: str, extension_ids: set[str]
) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not extension_ids:
        return counts
    for snapshot in db.scalars(
        select(Run.snapshot_json).where(
            Run.organization_id == organization_id,
            Run.started_at.is_not(None),
        )
    ):
        if not isinstance(snapshot, dict):
            continue
        for extension_id in _applied_skill_ids(snapshot) & extension_ids:
            counts[extension_id] += 1
    return counts


def list_skill_catalog(
    db: Session,
    *,
    user: User,
    query: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    sort: CatalogSort = "popular",
    offset: int = 0,
    limit: int = 60,
) -> dict[str, Any]:
    extensions = list(
        db.scalars(
            extension_access_query(user)
            .where(Extension.kind == "skill")
            .order_by(Extension.updated_at.desc(), Extension.id)
        )
    )
    extension_ids = {item.id for item in extensions}
    versions_by_extension: dict[str, list[ExtensionVersion]] = defaultdict(list)
    if extension_ids:
        for version in db.scalars(
            select(ExtensionVersion)
            .where(ExtensionVersion.extension_id.in_(extension_ids))
            .order_by(ExtensionVersion.extension_id, ExtensionVersion.version_number)
        ):
            versions_by_extension[version.extension_id].append(version)

    user_installations = {
        item.extension_id: item
        for item in db.scalars(
            select(ExtensionInstallation).where(
                ExtensionInstallation.extension_id.in_(extension_ids),
                ExtensionInstallation.scope_type == "user",
                ExtensionInstallation.scope_id == user.id,
                ExtensionInstallation.removed_at.is_(None),
            )
        )
    }
    install_counts = {
        str(extension_id): int(count)
        for extension_id, count in db.execute(
            select(
                ExtensionInstallation.extension_id,
                func.count(func.distinct(ExtensionInstallation.scope_id)),
            )
            .where(
                ExtensionInstallation.extension_id.in_(extension_ids),
                ExtensionInstallation.scope_type == "user",
                ExtensionInstallation.removed_at.is_(None),
            )
            .group_by(ExtensionInstallation.extension_id)
        )
    }
    like_keys = {_like_key(extension_id): extension_id for extension_id in extension_ids}
    like_counts = {
        like_keys[str(key)]: int(count)
        for key, count in db.execute(
            select(UserSetting.key, func.count(UserSetting.id))
            .where(UserSetting.key.in_(like_keys))
            .group_by(UserSetting.key)
        )
        if str(key) in like_keys
    }
    liked_ids = {
        like_keys[str(key)]
        for key in db.scalars(
            select(UserSetting.key).where(
                UserSetting.user_id == user.id,
                UserSetting.key.in_(like_keys),
            )
        )
        if str(key) in like_keys
    }
    run_counts = _run_counts(
        db, organization_id=user.organization_id, extension_ids=extension_ids
    )

    records: list[dict[str, Any]] = []
    for extension in extensions:
        manageable = can_manage_skill(db, user, extension)
        visible_versions = [
            version
            for version in versions_by_extension.get(extension.id, [])
            if manageable
            or version.status == "published"
            or version.created_by_user_id == user.id
        ]
        latest_version = visible_versions[-1] if visible_versions else None
        installable_version = next(
            (
                version
                for version in reversed(visible_versions)
                if version.status not in {"deprecated", "revoked"}
                and version.revoked_at is None
                and (manageable or version.status == "published")
            ),
            None,
        )
        manifest = latest_version.manifest_json if latest_version is not None else {}
        tags = (
            _manifest_tags({"tags": extension.tags_json})
            if extension.tags_json is not None
            else _manifest_tags(manifest)
        )
        category_value = _manifest_category(manifest)
        installation = user_installations.get(extension.id)
        records.append(
            {
                "id": extension.id,
                "name": extension.name,
                "description": extension.description,
                "category": category_value,
                "tags": tags,
                "latestVersionId": installable_version.id
                if installable_version is not None
                else None,
                "installed": installation is not None,
                "installationId": installation.id if installation is not None else None,
                "canInstall": installable_version is not None,
                "installCount": install_counts.get(extension.id, 0),
                "runCount": run_counts.get(extension.id, 0),
                "likeCount": like_counts.get(extension.id, 0),
                "likedByMe": extension.id in liked_ids,
                "updatedAt": extension.updated_at,
            }
        )

    category_counts = Counter(item["category"] for item in records)
    tag_counts = Counter(tag_value for item in records for tag_value in item["tags"])
    normalized_query = " ".join((query or "").split()).casefold()
    normalized_category = (category or "").strip().casefold()
    normalized_tag = (tag or "").strip().removeprefix("#").casefold()
    filtered = [
        item
        for item in records
        if (
            not normalized_query
            or normalized_query
            in " ".join(
                [
                    item["name"],
                    item["description"],
                    item["category"],
                    *item["tags"],
                ]
            ).casefold()
        )
        and (
            not normalized_category
            or item["category"].casefold() == normalized_category
        )
        and (
            not normalized_tag
            or normalized_tag in {value.casefold() for value in item["tags"]}
        )
    ]
    if sort == "runs":
        filtered.sort(key=lambda item: (-item["runCount"], item["name"].casefold()))
    elif sort == "likes":
        filtered.sort(key=lambda item: (-item["likeCount"], item["name"].casefold()))
    elif sort == "recent":
        filtered.sort(key=lambda item: (item["updatedAt"], item["id"]), reverse=True)
    elif sort == "name":
        filtered.sort(key=lambda item: (item["name"].casefold(), item["id"]))
    else:
        filtered.sort(
            key=lambda item: (
                -item["installCount"],
                -item["runCount"],
                -item["likeCount"],
                item["name"].casefold(),
            )
        )

    total = len(filtered)
    page = filtered[offset : offset + limit]
    return {
        "items": page,
        "total": total,
        "offset": offset,
        "hasMore": offset + len(page) < total,
        "facets": {
            "categories": [
                {"value": value, "count": count}
                for value, count in sorted(
                    category_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "tags": [
                {"value": value, "count": count}
                for value, count in sorted(
                    tag_counts.items(), key=lambda item: (-item[1], item[0])
                )[:24]
            ],
        },
    }


def set_skill_catalog_like(
    db: Session, *, user: User, extension_id: str, liked: bool
) -> dict[str, Any]:
    extension = require_extension(db, user, extension_id)
    if extension.kind != "skill":
        raise ApiProblem(404, "extension_not_found", "Skill을 찾을 수 없습니다.")
    key = _like_key(extension.id)
    setting = db.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user.id,
            UserSetting.key == key,
        )
    )
    if liked and setting is None:
        db.add(UserSetting(user_id=user.id, key=key, value_json={"liked": True}))
    elif not liked and setting is not None:
        db.delete(setting)
    db.flush()
    like_count = int(
        db.scalar(select(func.count(UserSetting.id)).where(UserSetting.key == key)) or 0
    )
    return {"liked": liked, "likeCount": like_count}
