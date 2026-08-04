from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only
from yaml import YAMLError, safe_load

from ..api.errors import ApiProblem
from ..authorization import require_conversation, require_project
from ..models import (
    Extension,
    ExtensionDraft,
    ExtensionDraftBinding,
    ExtensionDraftRevision,
    ExtensionInstallation,
    ExtensionVersion,
    Organization,
    ProjectMembership,
    SkillFolder,
    SkillFolderPlacement,
    SkillOwnership,
    User,
    new_uuid,
    utc_now,
)
from ..secret_policy import reject_secret_key_names
from .agent_skill_spec import (
    AgentSkillDocument,
    AgentSkillSpecError,
    ensure_agent_skill_package,
    parse_agent_skill,
    skill_resource_paths,
)
from .package_content import decode_package_content


_SAFE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*"
    r"(?:['\"](?!<|\$\{|your[_-]|replace[_-]|example)"
    r"[A-Za-z0-9_./+=-]{8,}['\"]|"
    r"(?!<|\$\{|your[_-]|replace[_-]|example)[A-Za-z0-9_./+=-]{8,})\s*$"
)
_FORBIDDEN_PACKAGE_NAMES = {".env", "credentials", "secrets"}
_FORBIDDEN_PACKAGE_SUFFIXES = {".key", ".p12", ".pfx", ".pem"}
SKILL_TRASH_RETENTION_DAYS = 30
_SKILL_TRASH_RETENTION = timedelta(days=SKILL_TRASH_RETENTION_DAYS)


def normalize_package(files: dict[str, str]) -> dict[str, str]:
    if not files:
        raise ApiProblem(422, "skill_package_empty", "Skill package가 비어 있습니다.")
    normalized: dict[str, str] = {}
    normalized_names: set[str] = set()
    for raw_path, content in files.items():
        path_text = raw_path.replace("\\", "/").strip()
        path = PurePosixPath(path_text)
        if (
            not path_text
            or path.is_absolute()
            or ".." in path.parts
            or "." in path.parts
            or len(path.parts) > 20
        ):
            raise ApiProblem(
                422, "unsafe_package_path", "Skill package 경로가 안전하지 않습니다."
            )
        canonical = path.as_posix()
        lowered_parts = {part.casefold() for part in path.parts}
        if (
            lowered_parts & _FORBIDDEN_PACKAGE_NAMES
            or path.suffix.casefold() in _FORBIDDEN_PACKAGE_SUFFIXES
        ):
            raise ApiProblem(
                422,
                "secret_file_forbidden",
                "비밀값이나 인증 파일은 Skill package에 저장할 수 없습니다.",
            )
        casefolded = canonical.casefold()
        if casefolded in normalized_names:
            raise ApiProblem(
                422, "duplicate_package_path", "중복된 Skill package 경로입니다."
            )
        if not isinstance(content, str):
            raise ApiProblem(
                422, "invalid_package_content", "Skill package 파일은 text여야 합니다."
            )
        try:
            raw_content, encoding = decode_package_content(content)
        except ValueError as exc:
            raise ApiProblem(422, "invalid_package_content", str(exc)) from exc
        secret_scan_content = (
            content
            if encoding == "utf-8"
            else raw_content.decode("utf-8", errors="ignore")
        )
        if (
            "-----BEGIN" in secret_scan_content
            and "PRIVATE KEY-----" in secret_scan_content
        ):
            raise ApiProblem(
                422,
                "secret_content_forbidden",
                "Private key는 Skill package에 저장할 수 없습니다.",
            )
        if _SECRET_ASSIGNMENT.search(content):
            raise ApiProblem(
                422,
                "secret_content_forbidden",
                "실제 비밀값으로 보이는 내용은 Skill package에 저장할 수 없습니다.",
            )
        normalized_names.add(casefolded)
        normalized[canonical] = content
    if "skill.md" not in normalized_names:
        raise ApiProblem(
            422, "skill_md_required", "Skill package에는 SKILL.md가 필요합니다."
        )
    return dict(sorted(normalized.items()))


def standardize_skill_package(
    package: dict[str, str],
    *,
    expected_name: str,
    fallback_description: str,
) -> tuple[dict[str, str], AgentSkillDocument]:
    try:
        return ensure_agent_skill_package(
            package,
            expected_name=expected_name,
            fallback_description=fallback_description,
        )
    except AgentSkillSpecError as exc:
        raise ApiProblem(422, "invalid_agent_skill", str(exc)) from exc


def package_digest(package: dict[str, str]) -> str:
    canonical = json.dumps(
        package, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def draft_etag(draft: ExtensionDraft) -> str:
    return f'"draft:{draft.id}:r{draft.current_revision}:{draft.current_digest}"'


def _slug(value: str | None, name: str, extension_id: str) -> str:
    candidate = value or re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    if not candidate:
        candidate = f"skill-{extension_id[:8]}"
    if not _SAFE_SLUG.fullmatch(candidate):
        raise ApiProblem(
            422,
            "invalid_extension_slug",
            "slug는 소문자 영문, 숫자와 하이픈만 사용할 수 있습니다.",
        )
    return candidate


def _ensure_no_secrets(value: Any, *, path: str = "settings") -> None:
    reject_secret_key_names(value, path=path)


def extension_access_query(user: User):
    if user.role == "admin":
        return select(Extension).where(
            Extension.kind == "skill", Extension.archived_at.is_(None)
        )
    project_ids = select(ProjectMembership.project_id).where(
        ProjectMembership.user_id == user.id,
        ProjectMembership.status == "active",
    )
    owned_skill_ids = select(SkillOwnership.skill_id).where(
        SkillOwnership.principal_type == "user",
        SkillOwnership.principal_id == user.id,
        SkillOwnership.role.in_(("owner", "maintainer")),
    )
    return select(Extension).where(
        Extension.kind == "skill",
        Extension.archived_at.is_(None),
        or_(
            Extension.owner_user_id == user.id,
            Extension.id.in_(owned_skill_ids),
            (
                (Extension.organization_id == user.organization_id)
                & (Extension.visibility == "organization")
            ),
            (
                (Extension.visibility == "project")
                & (Extension.project_id.in_(project_ids))
            ),
        ),
    )


def require_extension(db: Session, user: User, extension_id: str) -> Extension:
    extension = db.scalar(
        extension_access_query(user).where(Extension.id == extension_id)
    )
    if extension is None:
        raise ApiProblem(404, "extension_not_found", "Skill을 찾을 수 없습니다.")
    return extension


def require_owned_draft(db: Session, user: User, draft_id: str) -> ExtensionDraft:
    draft = db.get(ExtensionDraft, draft_id)
    if (
        draft is None
        or (draft.owner_user_id != user.id and user.role != "admin")
        or draft.status != "active"
    ):
        raise ApiProblem(404, "draft_not_found", "Skill Draft를 찾을 수 없습니다.")
    return draft


def skill_role(db: Session, user: User, extension: Extension) -> str | None:
    if user.role == "admin" or extension.owner_user_id == user.id:
        return "owner"
    return db.scalar(
        select(SkillOwnership.role).where(
            SkillOwnership.skill_id == extension.id,
            SkillOwnership.principal_type == "user",
            SkillOwnership.principal_id == user.id,
        )
    )


def can_manage_skill(db: Session, user: User, extension: Extension) -> bool:
    return skill_role(db, user, extension) in {"owner", "maintainer"}


def can_view_skill_package(db: Session, user: User, extension: Extension) -> bool:
    if can_manage_skill(db, user, extension):
        return True
    project_ids = select(ProjectMembership.project_id).where(
        ProjectMembership.user_id == user.id,
        ProjectMembership.status == "active",
    )
    installation_id = db.scalar(
        select(ExtensionInstallation.id)
        .where(
            ExtensionInstallation.extension_id == extension.id,
            ExtensionInstallation.removed_at.is_(None),
            or_(
                (
                    (ExtensionInstallation.scope_type == "user")
                    & (ExtensionInstallation.scope_id == user.id)
                ),
                (
                    (ExtensionInstallation.scope_type == "organization")
                    & (ExtensionInstallation.scope_id == user.organization_id)
                ),
                (
                    (ExtensionInstallation.scope_type == "project")
                    & (ExtensionInstallation.scope_id.in_(project_ids))
                ),
            ),
        )
        .limit(1)
    )
    return installation_id is not None


def _normalize_skill_tags(raw_tags: list[str]) -> list[str]:
    tags: list[str] = []
    for raw_tag in raw_tags:
        tag = raw_tag.strip().removeprefix("#").strip()
        if not tag or tag in tags:
            continue
        if len(tag) > 40:
            raise ApiProblem(
                422, "skill_tag_too_long", "Skill 태그는 40자 이하여야 합니다."
            )
        tags.append(tag)
    return tags


def update_extension_metadata(
    db: Session,
    *,
    user: User,
    extension_id: str,
    name: str,
    description: str,
    tags: list[str] | None = None,
) -> Extension:
    extension = require_extension(db, user, extension_id)
    if not can_manage_skill(db, user, extension):
        raise ApiProblem(
            403, "extension_write_forbidden", "Skill을 수정할 권한이 없습니다."
        )
    extension.name = " ".join(name.split())
    extension.description = description.strip()
    if tags is not None:
        extension.tags_json = _normalize_skill_tags(tags)
    extension.updated_at = utc_now()
    db.flush()
    return extension


def delete_skill(db: Session, *, user: User, extension_id: str) -> Extension:
    extension = require_extension(db, user, extension_id)
    if skill_role(db, user, extension) != "owner":
        raise ApiProblem(
            403, "extension_delete_forbidden", "Skill을 삭제할 권한이 없습니다."
        )

    trashed_at = utc_now()
    extension.archived_at = trashed_at
    extension.updated_at = trashed_at
    db.flush()
    return extension


def purge_expired_trashed_skills(db: Session, *, now: datetime | None = None) -> int:
    cutoff = (now or utc_now()) - _SKILL_TRASH_RETENTION
    expired_ids = list(
        db.scalars(
            select(Extension.id).where(
                Extension.kind == "skill",
                Extension.archived_at.is_not(None),
                Extension.archived_at <= cutoff,
            )
        )
    )
    if not expired_ids:
        return 0
    db.execute(
        delete(ExtensionInstallation).where(
            ExtensionInstallation.extension_id.in_(expired_ids)
        )
    )
    db.execute(delete(Extension).where(Extension.id.in_(expired_ids)))
    db.flush()
    return len(expired_ids)


def trashed_extension_access_query(user: User):
    if user.role == "admin":
        return select(Extension).where(Extension.archived_at.is_not(None))
    owned_skill_ids = select(SkillOwnership.skill_id).where(
        SkillOwnership.principal_type == "user",
        SkillOwnership.principal_id == user.id,
        SkillOwnership.role == "owner",
    )
    return select(Extension).where(
        Extension.archived_at.is_not(None),
        or_(
            Extension.owner_user_id == user.id,
            Extension.id.in_(owned_skill_ids),
        ),
    )


def list_trashed_extensions(
    db: Session, *, user: User, query: str | None = None
) -> list[Extension]:
    statement = trashed_extension_access_query(user)
    if query:
        normalized = f"%{' '.join(query.split()).casefold()}%"
        statement = statement.where(
            or_(
                func.lower(Extension.name).like(normalized),
                func.lower(Extension.slug).like(normalized),
            )
        )
    return list(
        db.scalars(statement.order_by(Extension.archived_at.desc(), Extension.id))
    )


def restore_skill(db: Session, *, user: User, extension_id: str) -> Extension:
    purge_expired_trashed_skills(db)
    extension = db.scalar(
        trashed_extension_access_query(user).where(Extension.id == extension_id)
    )
    if extension is None:
        raise ApiProblem(
            404, "trashed_extension_not_found", "복원할 Skill을 찾을 수 없습니다."
        )
    extension.archived_at = None
    extension.updated_at = utc_now()
    db.flush()
    return extension


def checkout_draft(db: Session, *, user: User, extension_id: str) -> ExtensionDraft:
    extension = require_extension(db, user, extension_id)
    draft = db.scalar(
        select(ExtensionDraft).where(
            ExtensionDraft.extension_id == extension.id,
            ExtensionDraft.owner_user_id == user.id,
        )
    )
    if draft is not None:
        if draft.status != "active":
            raise ApiProblem(
                409, "draft_not_active", "활성 상태의 Skill Draft가 아닙니다."
            )
        return draft
    if not can_view_skill_package(db, user, extension):
        raise ApiProblem(
            404,
            "version_not_found",
            "설치된 Skill version만 편집할 수 있습니다.",
        )
    version_query = select(ExtensionVersion).where(
        ExtensionVersion.extension_id == extension.id
    )
    if not can_manage_skill(db, user, extension):
        version_query = version_query.where(ExtensionVersion.status == "published")
    version = db.scalar(version_query.order_by(ExtensionVersion.version_number.desc()))
    if version is None:
        raise ApiProblem(
            409, "version_required", "편집을 시작할 Skill 버전이 없습니다."
        )
    draft = ExtensionDraft(
        extension_id=extension.id,
        owner_user_id=user.id,
        base_version_id=version.id,
        current_revision=1,
        current_digest=version.package_digest,
        package_json=dict(version.package_json),
        status="active",
    )
    db.add(draft)
    db.flush()
    db.add(
        ExtensionDraftRevision(
            draft_id=draft.id,
            revision_number=1,
            package_json=dict(version.package_json),
            package_digest=version.package_digest,
            change_summary=f"v{version.version_number} 편집 시작",
            created_by_user_id=user.id,
        )
    )
    db.add(
        ExtensionDraftBinding(
            draft_id=draft.id,
            user_id=user.id,
            project_id=None,
            enabled=True,
        )
    )
    placement = db.scalar(
        select(SkillFolderPlacement).where(
            SkillFolderPlacement.skill_id == extension.id,
            SkillFolderPlacement.scope_type == "user",
            SkillFolderPlacement.scope_id == user.id,
        )
    )
    if placement is None:
        folder = ensure_unclassified_folder(
            db, user=user, scope_type="user", scope_id=user.id
        )
        db.add(
            SkillFolderPlacement(
                folder_id=folder.id,
                skill_id=extension.id,
                scope_type="user",
                scope_id=user.id,
                moved_by_user_id=user.id,
            )
        )
    db.flush()
    return draft


def create_skill(
    db: Session,
    *,
    user: User,
    name: str,
    slug: str | None,
    description: str,
    package_files: dict[str, str],
    project_id: str | None = None,
    source_conversation_id: str | None = None,
) -> tuple[Extension, ExtensionDraft]:
    if project_id is not None:
        require_project(db, user, project_id, write=True)
    if source_conversation_id is not None:
        source_conversation = require_conversation(
            db, user, source_conversation_id, write=True
        )
        if project_id is not None and source_conversation.project_id != project_id:
            raise ApiProblem(
                409,
                "source_project_mismatch",
                "원본 대화와 Skill Project가 일치하지 않습니다.",
            )
    extension_id = new_uuid()
    resolved_slug = _slug(slug, name, extension_id)
    package, skill_document = standardize_skill_package(
        normalize_package(package_files),
        expected_name=resolved_slug,
        fallback_description=(
            description.strip()
            or f"Use this Skill for the {name.strip()} workflow when requested."
        ),
    )
    digest = package_digest(package)
    duplicate = db.scalar(
        select(Extension).where(
            Extension.owner_user_id == user.id,
            Extension.slug == resolved_slug,
            Extension.archived_at.is_(None),
        )
    )
    if duplicate is not None:
        raise ApiProblem(409, "extension_slug_exists", "같은 slug의 Skill이 있습니다.")
    extension = Extension(
        id=extension_id,
        kind="skill",
        slug=resolved_slug,
        name=name.strip(),
        description=skill_document.description,
        owner_user_id=user.id,
        creator_user_id=user.id,
        organization_id=user.organization_id,
        project_id=project_id,
        visibility="private",
    )
    db.add(extension)
    db.flush()
    db.add(
        SkillOwnership(
            skill_id=extension.id,
            principal_type="user",
            principal_id=user.id,
            role="owner",
            created_by_user_id=user.id,
        )
    )
    draft = ExtensionDraft(
        extension_id=extension.id,
        owner_user_id=user.id,
        current_revision=1,
        current_digest=digest,
        package_json=package,
        status="active",
        source_conversation_id=source_conversation_id,
    )
    db.add(draft)
    db.flush()
    db.add(
        ExtensionDraftRevision(
            draft_id=draft.id,
            revision_number=1,
            package_json=package,
            package_digest=digest,
            change_summary="초기 WorkingDraft",
            created_by_user_id=user.id,
        )
    )
    db.add(
        ExtensionDraftBinding(
            draft_id=draft.id,
            user_id=user.id,
            project_id=None,
            enabled=True,
        )
    )
    folder = ensure_unclassified_folder(
        db, user=user, scope_type="user", scope_id=user.id
    )
    db.add(
        SkillFolderPlacement(
            folder_id=folder.id,
            skill_id=extension.id,
            scope_type="user",
            scope_id=user.id,
            moved_by_user_id=user.id,
        )
    )
    db.flush()
    return extension, draft


def sync_workspace_skill(
    db: Session,
    *,
    user: User,
    project_id: str,
    source_conversation_id: str,
    slug: str,
    name: str,
    description: str,
    package_files: dict[str, str],
) -> tuple[Extension, ExtensionDraft, bool]:
    """Create or refresh the active Draft represented by extensions/skills/."""
    resolved_slug = _slug(slug, name, new_uuid())
    extension = db.scalar(
        select(Extension).where(
            Extension.owner_user_id == user.id,
            Extension.slug == resolved_slug,
            Extension.archived_at.is_(None),
        )
    )
    if extension is None:
        extension, created_draft = create_skill(
            db,
            user=user,
            name=name,
            slug=resolved_slug,
            description=description,
            package_files=package_files,
            project_id=project_id,
            source_conversation_id=source_conversation_id,
        )
        return extension, created_draft, True
    if extension.project_id != project_id:
        raise ApiProblem(
            409,
            "workspace_skill_project_conflict",
            "같은 slug의 Skill이 다른 Project에 있습니다.",
        )

    draft = db.scalar(
        select(ExtensionDraft).where(
            ExtensionDraft.extension_id == extension.id,
            ExtensionDraft.owner_user_id == user.id,
            ExtensionDraft.status == "active",
        )
    )
    if draft is None:
        draft = checkout_draft(db, user=user, extension_id=extension.id)

    normalized_name = " ".join(name.split())
    normalized_description = description.strip()
    if (
        extension.name != normalized_name
        or extension.description != normalized_description
    ):
        extension.name = normalized_name
        extension.description = normalized_description
        extension.updated_at = utc_now()

    package, skill_document = standardize_skill_package(
        normalize_package(package_files),
        expected_name=extension.slug,
        fallback_description=normalized_description,
    )
    if extension.description != skill_document.description:
        extension.description = skill_document.description
    digest = package_digest(package)
    if draft.current_digest == digest:
        db.flush()
        return extension, draft, False
    draft, changed = update_draft(
        db,
        user=user,
        draft_id=draft.id,
        expected_revision=draft.current_revision,
        expected_digest=draft.current_digest,
        package_files=package,
        change_summary="Project workspace Skill 동기화",
    )
    return extension, draft, changed


def update_draft(
    db: Session,
    *,
    user: User,
    draft_id: str,
    expected_revision: int,
    expected_digest: str,
    package_files: dict[str, str],
    change_summary: str,
) -> tuple[ExtensionDraft, bool]:
    draft = require_owned_draft(db, user, draft_id)
    _check_draft_precondition(draft, expected_revision, expected_digest)
    extension = db.get(Extension, draft.extension_id)
    if extension is None:
        raise ApiProblem(404, "extension_not_found", "Skill을 찾을 수 없습니다.")
    package, skill_document = standardize_skill_package(
        normalize_package(package_files),
        expected_name=extension.slug,
        fallback_description=extension.description,
    )
    if extension.description != skill_document.description:
        extension.description = skill_document.description
        extension.updated_at = utc_now()
    digest = package_digest(package)
    if digest == draft.current_digest:
        return draft, False
    next_revision = expected_revision + 1
    result = db.execute(
        update(ExtensionDraft)
        .where(
            ExtensionDraft.id == draft.id,
            ExtensionDraft.current_revision == expected_revision,
            ExtensionDraft.current_digest == expected_digest,
        )
        .values(
            current_revision=next_revision,
            current_digest=digest,
            package_json=package,
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        db.expire(draft)
        db.refresh(draft)
        _check_draft_precondition(draft, expected_revision, expected_digest)
        raise RuntimeError("Skill Draft compare-and-swap failed without a conflict")
    db.add(
        ExtensionDraftRevision(
            draft_id=draft.id,
            revision_number=next_revision,
            package_json=package,
            package_digest=digest,
            change_summary=change_summary,
            created_by_user_id=user.id,
        )
    )
    db.flush()
    db.expire(draft)
    db.refresh(draft)
    return draft, True


def _check_draft_precondition(
    draft: ExtensionDraft, expected_revision: int, expected_digest: str
) -> None:
    if (
        draft.current_revision != expected_revision
        or draft.current_digest != expected_digest
    ):
        raise ApiProblem(
            409,
            "draft_conflict",
            "Skill Draft가 다른 곳에서 변경되었습니다. 최신 revision을 다시 불러오세요.",
        )


def activate_draft(
    db: Session,
    *,
    user: User,
    draft_id: str,
    project_id: str | None,
    enabled: bool,
) -> ExtensionDraftBinding:
    draft = require_owned_draft(db, user, draft_id)
    if project_id is not None:
        require_project(db, user, project_id, write=True)
    project_filter = (
        ExtensionDraftBinding.project_id.is_(None)
        if project_id is None
        else ExtensionDraftBinding.project_id == project_id
    )
    binding = db.scalar(
        select(ExtensionDraftBinding).where(
            ExtensionDraftBinding.draft_id == draft.id,
            ExtensionDraftBinding.user_id == user.id,
            project_filter,
        )
    )
    if binding is None:
        binding = ExtensionDraftBinding(
            draft_id=draft.id,
            user_id=user.id,
            project_id=project_id,
            enabled=enabled,
        )
        db.add(binding)
    else:
        binding.enabled = enabled
        binding.bound_at = utc_now()
    db.flush()
    return binding


def save_draft_version(
    db: Session,
    *,
    user: User,
    draft_id: str,
    expected_revision: int,
    expected_digest: str,
    base_version_id: str | None,
    manifest: dict[str, Any],
) -> ExtensionVersion:
    draft = require_owned_draft(db, user, draft_id)
    _check_draft_precondition(draft, expected_revision, expected_digest)
    if draft.base_version_id != base_version_id:
        raise ApiProblem(
            409,
            "base_version_conflict",
            "Skill Draft의 base version이 변경되었습니다.",
        )
    _ensure_no_secrets(manifest, path="manifest")
    revision = db.scalar(
        select(ExtensionDraftRevision).where(
            ExtensionDraftRevision.draft_id == draft.id,
            ExtensionDraftRevision.revision_number == draft.current_revision,
        )
    )
    latest_number = (
        db.scalar(
            select(func.max(ExtensionVersion.version_number)).where(
                ExtensionVersion.extension_id == draft.extension_id
            )
        )
        or 0
    )
    version = ExtensionVersion(
        extension_id=draft.extension_id,
        version_number=latest_number + 1,
        parent_version_id=base_version_id,
        package_json=dict(draft.package_json),
        package_digest=draft.current_digest,
        manifest_json=manifest,
        change_summary=(revision.change_summary if revision else ""),
        change_type="save",
        status="private",
        created_by_user_id=user.id,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiProblem(
            409,
            "version_conflict",
            "Skill version이 다른 작업에서 먼저 저장되었습니다.",
        ) from exc
    base_filter = (
        ExtensionDraft.base_version_id.is_(None)
        if base_version_id is None
        else ExtensionDraft.base_version_id == base_version_id
    )
    result = db.execute(
        update(ExtensionDraft)
        .where(
            ExtensionDraft.id == draft.id,
            ExtensionDraft.current_revision == expected_revision,
            ExtensionDraft.current_digest == expected_digest,
            base_filter,
        )
        .values(base_version_id=version.id, updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        db.expire(draft)
        db.refresh(draft)
        _check_draft_precondition(draft, expected_revision, expected_digest)
        if draft.base_version_id != base_version_id:
            raise ApiProblem(
                409,
                "base_version_conflict",
                "Skill Draft의 base version이 변경되었습니다.",
            )
        raise RuntimeError("Skill version compare-and-swap failed without a conflict")
    db.expire(draft)
    db.refresh(draft)
    return version


def publish_version(
    db: Session, *, user: User, version_id: str
) -> tuple[Extension, ExtensionVersion]:
    version = db.get(ExtensionVersion, version_id)
    if version is None:
        raise ApiProblem(404, "version_not_found", "Skill version을 찾을 수 없습니다.")
    extension = db.get(Extension, version.extension_id)
    if extension is None or extension.archived_at is not None:
        raise ApiProblem(404, "extension_not_found", "Skill을 찾을 수 없습니다.")
    if skill_role(db, user, extension) != "owner":
        raise ApiProblem(403, "extension_write_forbidden", "게시 권한이 없습니다.")
    organization = db.get(Organization, user.organization_id)
    auto = (
        organization is not None and organization.marketplace_permission_mode == "auto"
    )
    if user.role != "admin" and not auto:
        raise ApiProblem(
            403,
            "marketplace_review_required",
            "공용 게시에는 관리자 검토가 필요합니다.",
        )
    if version.revoked_at is not None or version.status == "revoked":
        raise ApiProblem(409, "version_revoked", "폐기된 version은 게시할 수 없습니다.")
    version.status = "published"
    version.published_at = utc_now()
    extension.visibility = "organization"
    extension.publisher_user_id = user.id
    extension.latest_published_version_id = version.id
    db.flush()
    return extension, version


def _version_is_visible_to_user(
    db: Session,
    *,
    user: User,
    extension: Extension,
    version: ExtensionVersion,
) -> bool:
    return (
        can_manage_skill(db, user, extension)
        or version.status == "published"
        or version.created_by_user_id == user.id
    )


def _diff_file(
    *,
    path: str,
    before: str | None,
    after: str | None,
) -> dict[str, Any]:
    before_lines = [] if before is None else before.splitlines()
    after_lines = [] if after is None else after.splitlines()
    matcher = SequenceMatcher(None, before_lines, after_lines, autojunk=False)
    hunks: list[dict[str, Any]] = []
    additions = 0
    deletions = 0
    for group in matcher.get_grouped_opcodes(n=3):
        old_start = group[0][1] + 1
        new_start = group[0][3] + 1
        lines: list[dict[str, Any]] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for offset, content in enumerate(before_lines[i1:i2]):
                    lines.append(
                        {
                            "kind": "context",
                            "oldLine": i1 + offset + 1,
                            "newLine": j1 + offset + 1,
                            "content": content,
                        }
                    )
                continue
            if tag in {"replace", "delete"}:
                for offset, content in enumerate(before_lines[i1:i2]):
                    deletions += 1
                    lines.append(
                        {
                            "kind": "delete",
                            "oldLine": i1 + offset + 1,
                            "newLine": None,
                            "content": content,
                        }
                    )
            if tag in {"replace", "insert"}:
                for offset, content in enumerate(after_lines[j1:j2]):
                    additions += 1
                    lines.append(
                        {
                            "kind": "add",
                            "oldLine": None,
                            "newLine": j1 + offset + 1,
                            "content": content,
                        }
                    )
        hunks.append(
            {
                "oldStart": old_start,
                "oldLines": group[-1][2] - group[0][1],
                "newStart": new_start,
                "newLines": group[-1][4] - group[0][3],
                "lines": lines,
            }
        )
    return {
        "path": path,
        "status": "added"
        if before is None
        else "deleted"
        if after is None
        else "modified",
        "additions": additions,
        "deletions": deletions,
        "hunks": hunks,
    }


def compare_skill_versions(
    db: Session,
    *,
    user: User,
    extension_id: str,
    from_version_id: str,
    to_version_id: str,
) -> dict[str, Any]:
    extension = require_extension(db, user, extension_id)
    if not can_view_skill_package(db, user, extension):
        raise ApiProblem(
            404, "version_not_found", "설치된 Skill version만 비교할 수 있습니다."
        )
    versions = [
        db.get(ExtensionVersion, version_id)
        for version_id in (from_version_id, to_version_id)
    ]
    if any(
        version is None
        or version.extension_id != extension.id
        or not _version_is_visible_to_user(
            db, user=user, extension=extension, version=version
        )
        for version in versions
    ):
        raise ApiProblem(404, "version_not_found", "Skill version을 찾을 수 없습니다.")
    before, after = versions
    assert before is not None and after is not None
    paths = sorted(set(before.package_json) | set(after.package_json))
    files = [
        _diff_file(
            path=path,
            before=before.package_json.get(path),
            after=after.package_json.get(path),
        )
        for path in paths
        if before.package_json.get(path) != after.package_json.get(path)
    ]
    return {
        "fromVersion": version_payload(before, include_package=False),
        "toVersion": version_payload(after, include_package=False),
        "files": files,
        "summary": {
            "filesChanged": len(files),
            "additions": sum(item["additions"] for item in files),
            "deletions": sum(item["deletions"] for item in files),
        },
    }


def rollback_skill_version(
    db: Session,
    *,
    user: User,
    extension_id: str,
    target_version_id: str,
    expected_current_version_id: str,
    change_summary: str,
) -> tuple[Extension, ExtensionVersion]:
    extension = require_extension(db, user, extension_id)
    if skill_role(db, user, extension) != "owner":
        raise ApiProblem(
            403,
            "skill_rollback_forbidden",
            "Skill Owner만 공식 버전을 복원할 수 있습니다.",
        )
    if extension.latest_published_version_id != expected_current_version_id:
        raise ApiProblem(
            409,
            "published_version_conflict",
            "현재 공식 Skill version이 변경되었습니다.",
        )
    current = db.get(ExtensionVersion, expected_current_version_id)
    target = db.get(ExtensionVersion, target_version_id)
    if (
        current is None
        or current.extension_id != extension.id
        or current.status != "published"
    ):
        raise ApiProblem(
            409,
            "published_version_conflict",
            "현재 공식 Skill version을 확인할 수 없습니다.",
        )
    if target is None or target.extension_id != extension.id:
        raise ApiProblem(
            404, "version_not_found", "복원할 Skill version을 찾을 수 없습니다."
        )
    if target.revoked_at is not None or target.status == "revoked":
        raise ApiProblem(
            409, "version_revoked", "폐기된 Skill version은 복원할 수 없습니다."
        )
    if target.id == current.id:
        raise ApiProblem(
            409, "version_already_current", "이미 현재 공식 Skill version입니다."
        )
    latest_number = (
        db.scalar(
            select(func.max(ExtensionVersion.version_number)).where(
                ExtensionVersion.extension_id == extension.id
            )
        )
        or 0
    )
    restored = ExtensionVersion(
        extension_id=extension.id,
        version_number=latest_number + 1,
        parent_version_id=current.id,
        package_json=dict(target.package_json),
        package_digest=target.package_digest,
        manifest_json=dict(target.manifest_json),
        change_summary=change_summary.strip() or f"v{target.version_number} 기반 복원",
        change_type="rollback",
        restored_from_version_id=target.id,
        status="published",
        created_by_user_id=user.id,
        published_at=utc_now(),
    )
    db.add(restored)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiProblem(
            409, "version_conflict", "다른 작업에서 Skill version을 먼저 만들었습니다."
        ) from exc
    result = db.execute(
        update(Extension)
        .where(
            Extension.id == extension.id,
            Extension.latest_published_version_id == expected_current_version_id,
        )
        .values(
            latest_published_version_id=restored.id,
            publisher_user_id=user.id,
            visibility="organization",
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        raise ApiProblem(
            409,
            "published_version_conflict",
            "현재 공식 Skill version이 변경되었습니다.",
        )
    db.expire(extension)
    db.refresh(extension)
    return extension, restored


def add_skill_ownership(
    db: Session,
    *,
    user: User,
    extension_id: str,
    principal_user_id: str,
    role: str,
) -> SkillOwnership:
    extension = require_extension(db, user, extension_id)
    if skill_role(db, user, extension) != "owner":
        raise ApiProblem(
            403, "skill_owner_forbidden", "Skill Owner만 담당자를 변경할 수 있습니다."
        )
    principal = db.get(User, principal_user_id)
    if principal is None or principal.organization_id != extension.organization_id:
        raise ApiProblem(
            404, "skill_owner_user_not_found", "같은 조직의 사용자를 찾을 수 없습니다."
        )
    ownership = db.scalar(
        select(SkillOwnership).where(
            SkillOwnership.skill_id == extension.id,
            SkillOwnership.principal_type == "user",
            SkillOwnership.principal_id == principal.id,
        )
    )
    if ownership is None:
        ownership = SkillOwnership(
            skill_id=extension.id,
            principal_type="user",
            principal_id=principal.id,
            role=role,
            created_by_user_id=user.id,
        )
        db.add(ownership)
    else:
        ownership.role = role
    db.flush()
    return ownership


def remove_skill_ownership(
    db: Session, *, user: User, extension_id: str, ownership_id: str
) -> SkillOwnership:
    extension = require_extension(db, user, extension_id)
    if skill_role(db, user, extension) != "owner":
        raise ApiProblem(
            403, "skill_owner_forbidden", "Skill Owner만 담당자를 변경할 수 있습니다."
        )
    ownership = db.get(SkillOwnership, ownership_id)
    if ownership is None or ownership.skill_id != extension.id:
        raise ApiProblem(
            404, "skill_ownership_not_found", "Skill 담당자 정보를 찾을 수 없습니다."
        )
    if (
        ownership.principal_type == "user"
        and ownership.principal_id == extension.owner_user_id
    ):
        raise ApiProblem(
            409,
            "primary_owner_transfer_required",
            "최초 Owner는 소유권 이전 후 제거할 수 있습니다.",
        )
    db.delete(ownership)
    db.flush()
    return ownership


def install_version(
    db: Session,
    *,
    user: User,
    version_id: str,
    scope_type: str,
    scope_id: str | None,
    enabled: bool,
    settings: dict[str, Any],
) -> ExtensionInstallation:
    _ensure_no_secrets(settings)
    version = db.get(ExtensionVersion, version_id)
    if version is None or version.status in {"revoked", "deprecated"}:
        raise ApiProblem(
            404, "version_not_installable", "설치할 수 없는 version입니다."
        )
    extension = require_extension(db, user, version.extension_id)
    if extension.owner_user_id != user.id and version.status != "published":
        raise ApiProblem(
            404, "version_not_installable", "설치할 수 없는 version입니다."
        )
    canonical_scope_id = authorize_scope(
        db, user=user, scope_type=scope_type, scope_id=scope_id, write=True
    )
    installation = db.scalar(
        select(ExtensionInstallation).where(
            ExtensionInstallation.extension_id == extension.id,
            ExtensionInstallation.scope_type == scope_type,
            ExtensionInstallation.scope_id == canonical_scope_id,
            ExtensionInstallation.removed_at.is_(None),
        )
    )
    if installation is None:
        installation = ExtensionInstallation(
            extension_id=extension.id,
            version_id=version.id,
            scope_type=scope_type,
            scope_id=canonical_scope_id,
            enabled=enabled,
            settings_json=settings,
            installed_by_user_id=user.id,
        )
        db.add(installation)
    else:
        installation.version_id = version.id
        installation.enabled = enabled
        installation.settings_json = settings
        installation.installed_by_user_id = user.id
        installation.installed_at = utc_now()
    db.flush()
    return installation


def require_installation(
    db: Session, user: User, installation_id: str, *, write: bool = False
) -> ExtensionInstallation:
    installation = db.get(ExtensionInstallation, installation_id)
    if installation is None or installation.removed_at is not None:
        raise ApiProblem(404, "installation_not_found", "설치를 찾을 수 없습니다.")
    authorize_scope(
        db,
        user=user,
        scope_type=installation.scope_type,
        scope_id=installation.scope_id,
        write=write,
    )
    return installation


def update_installation(
    db: Session,
    *,
    user: User,
    installation_id: str,
    enabled: bool | None,
    project_ids: list[str] | None,
    update_project_ids: bool,
) -> ExtensionInstallation:
    installation = require_installation(db, user, installation_id, write=True)
    if enabled is not None:
        installation.enabled = enabled
    if update_project_ids:
        if installation.scope_type != "user":
            raise ApiProblem(
                422,
                "installation_project_scope_unsupported",
                "사용자 범위 Skill 설치만 프로젝트별로 설정할 수 있습니다.",
            )
        normalized_project_ids = list(dict.fromkeys(project_ids or []))
        for project_id in normalized_project_ids:
            require_project(db, user, project_id)
        installation.project_ids_json = (
            normalized_project_ids if project_ids is not None else None
        )
    db.flush()
    return installation


def uninstall(
    db: Session, *, user: User, installation_id: str
) -> ExtensionInstallation:
    installation = require_installation(db, user, installation_id, write=True)
    installation.enabled = False
    installation.removed_at = utc_now()
    db.flush()
    return installation


def list_installations(
    db: Session,
    *,
    user: User,
    project_id: str | None = None,
) -> list[ExtensionInstallation]:
    scopes = [("user", user.id), ("organization", user.organization_id)]
    if project_id is not None:
        require_project(db, user, project_id)
        scopes.append(("project", project_id))
    scope_filters = [
        (ExtensionInstallation.scope_type == scope_type)
        & (ExtensionInstallation.scope_id == scope_id)
        for scope_type, scope_id in scopes
    ]
    installations = list(
        db.scalars(
            select(ExtensionInstallation)
            .where(
                ExtensionInstallation.removed_at.is_(None),
                or_(*scope_filters),
            )
            .order_by(ExtensionInstallation.installed_at.desc())
        )
    )
    if project_id is None:
        return installations
    return [
        installation
        for installation in installations
        if installation.scope_type != "user"
        or installation.project_ids_json is None
        or project_id in installation.project_ids_json
    ]


def list_extensions(
    db: Session, *, user: User, query: str | None = None
) -> list[Extension]:
    statement = extension_access_query(user)
    if query:
        normalized = f"%{' '.join(query.split()).casefold()}%"
        statement = statement.where(
            or_(
                func.lower(Extension.name).like(normalized),
                func.lower(Extension.slug).like(normalized),
            )
        )
    return list(
        db.scalars(statement.order_by(Extension.updated_at.desc(), Extension.id))
    )


def resolve_skill_snapshot(
    db: Session, *, user: User, project_id: str
) -> list[dict[str, Any]]:
    """Resolve exact executable Skill revisions for a future Run snapshot."""
    require_project(db, user, project_id)
    bindings = list(
        db.execute(
            select(ExtensionDraftBinding, ExtensionDraft, Extension)
            .join(ExtensionDraft, ExtensionDraft.id == ExtensionDraftBinding.draft_id)
            .join(Extension, Extension.id == ExtensionDraft.extension_id)
            .where(
                ExtensionDraftBinding.user_id == user.id,
                ExtensionDraftBinding.enabled.is_(True),
                or_(
                    ExtensionDraftBinding.project_id.is_(None),
                    ExtensionDraftBinding.project_id == project_id,
                ),
                ExtensionDraft.status == "active",
                Extension.kind == "skill",
                Extension.archived_at.is_(None),
                or_(
                    Extension.project_id.is_(None),
                    Extension.project_id == project_id,
                ),
            )
        )
    )
    resolved: dict[str, dict[str, Any]] = {}
    for binding, draft, extension in bindings:
        effective_project_id = binding.project_id or extension.project_id
        skill_document = _skill_document(
            draft.package_json,
            slug=extension.slug,
            fallback_description=extension.description,
        )
        allow_implicit_invocation = _skill_allows_implicit_invocation(
            draft.package_json
        )
        candidate = {
            "extension_id": extension.id,
            "kind": extension.kind,
            "slug": extension.slug,
            "name": extension.name,
            "description": skill_document.description,
            "source": "draft",
            "draft_id": draft.id,
            "draft_revision": draft.current_revision,
            "digest": draft.current_digest,
            "instructions": _skill_instructions(draft.package_json),
            "resources": skill_resource_paths(draft.package_json),
            "compatibility": skill_document.compatibility,
            "allow_implicit_invocation": allow_implicit_invocation,
            "scope_type": "project" if effective_project_id else "user",
            "scope_id": effective_project_id or user.id,
        }
        existing = resolved.get(extension.id)
        if existing is None or binding.project_id == project_id:
            resolved[extension.id] = candidate
    scope_pairs = {
        ("user", user.id),
        ("project", project_id),
        ("organization", user.organization_id),
    }
    for installation, version, extension in db.execute(
        select(ExtensionInstallation, ExtensionVersion, Extension)
        .join(ExtensionVersion, ExtensionVersion.id == ExtensionInstallation.version_id)
        .join(Extension, Extension.id == ExtensionInstallation.extension_id)
        .where(
            ExtensionInstallation.enabled.is_(True),
            ExtensionInstallation.removed_at.is_(None),
            ExtensionVersion.revoked_at.is_(None),
            ExtensionVersion.status != "revoked",
            Extension.kind == "skill",
            Extension.archived_at.is_(None),
            or_(Extension.project_id.is_(None), Extension.project_id == project_id),
        )
    ):
        if (installation.scope_type, installation.scope_id) not in scope_pairs:
            continue
        if (
            installation.scope_type == "user"
            and installation.project_ids_json is not None
            and project_id not in installation.project_ids_json
        ):
            continue
        if extension.id in resolved:
            continue
        skill_document = _skill_document(
            version.package_json,
            slug=extension.slug,
            fallback_description=extension.description,
        )
        allow_implicit_invocation = _skill_allows_implicit_invocation(
            version.package_json
        )
        resolved[extension.id] = {
            "extension_id": extension.id,
            "kind": extension.kind,
            "slug": extension.slug,
            "name": extension.name,
            "description": skill_document.description,
            "source": "version",
            "version_id": version.id,
            "version": version.version_number,
            "digest": version.package_digest,
            "instructions": _skill_instructions(version.package_json),
            "resources": skill_resource_paths(version.package_json),
            "compatibility": skill_document.compatibility,
            "allow_implicit_invocation": allow_implicit_invocation,
            "installation_id": installation.id,
            "scope_type": installation.scope_type,
            "scope_id": installation.scope_id,
        }
    return sorted(
        resolved.values(),
        key=lambda item: (str(item["name"]), str(item["extension_id"])),
    )


def _skill_instructions(package: dict[str, str]) -> str:
    for path, content in package.items():
        if path.casefold() == "skill.md":
            return content
    raise ApiProblem(
        409,
        "skill_instructions_missing",
        "Skill snapshot의 SKILL.md를 찾을 수 없습니다.",
    )


def _skill_document(
    package: dict[str, str],
    *,
    slug: str,
    fallback_description: str,
) -> AgentSkillDocument:
    content = _skill_instructions(package)
    try:
        return parse_agent_skill(content, expected_name=slug)
    except AgentSkillSpecError:
        _normalized, document = standardize_skill_package(
            package,
            expected_name=slug,
            fallback_description=fallback_description,
        )
        return document


def _skill_allows_implicit_invocation(package: dict[str, str]) -> bool:
    for path, content in package.items():
        if path.casefold() not in {"agents/openai.yaml", "agents/openai.yml"}:
            continue
        try:
            metadata = safe_load(content)
        except YAMLError:
            return True
        if not isinstance(metadata, dict):
            return True
        policy = metadata.get("policy")
        if not isinstance(policy, dict):
            return True
        value = policy.get("allow_implicit_invocation")
        return value if isinstance(value, bool) else True
    return True


def authorize_scope(
    db: Session,
    *,
    user: User,
    scope_type: str,
    scope_id: str | None,
    write: bool,
) -> str:
    if scope_type == "user":
        resolved = scope_id or user.id
        if resolved != user.id and user.role != "admin":
            raise ApiProblem(403, "scope_forbidden", "다른 사용자의 범위입니다.")
        return resolved
    if scope_type == "project":
        if scope_id is None:
            raise ApiProblem(422, "scope_id_required", "Project ID가 필요합니다.")
        require_project(db, user, scope_id, write=write)
        return scope_id
    if scope_type == "organization":
        resolved = scope_id or user.organization_id
        if resolved != user.organization_id or (write and user.role != "admin"):
            raise ApiProblem(403, "scope_forbidden", "Organization 권한이 없습니다.")
        return resolved
    raise ApiProblem(422, "invalid_scope", "지원하지 않는 설치 범위입니다.")


def normalize_folder_name(value: str) -> tuple[str, str]:
    name = " ".join(value.split())
    if not name:
        raise ApiProblem(422, "folder_name_required", "Folder 이름이 필요합니다.")
    return name, name.casefold()


def ensure_unclassified_folder(
    db: Session, *, user: User, scope_type: str, scope_id: str | None
) -> SkillFolder:
    canonical_scope_id = authorize_scope(
        db, user=user, scope_type=scope_type, scope_id=scope_id, write=True
    )
    folder = db.scalar(
        select(SkillFolder).where(
            SkillFolder.scope_type == scope_type,
            SkillFolder.scope_id == canonical_scope_id,
            SkillFolder.is_system.is_(True),
            SkillFolder.normalized_name == "미분류",
            SkillFolder.archived_at.is_(None),
        )
    )
    if folder is None:
        folder = SkillFolder(
            scope_type=scope_type,
            scope_id=canonical_scope_id,
            name="미분류",
            normalized_name="미분류",
            is_system=True,
            created_by_user_id=user.id,
        )
        db.add(folder)
        db.flush()
    return folder


def list_folders(
    db: Session,
    *,
    user: User,
    scope_type: str,
    scope_id: str | None,
) -> list[SkillFolder]:
    canonical_scope_id = authorize_scope(
        db, user=user, scope_type=scope_type, scope_id=scope_id, write=False
    )
    return list(
        db.scalars(
            select(SkillFolder)
            .where(
                SkillFolder.scope_type == scope_type,
                SkillFolder.scope_id == canonical_scope_id,
                SkillFolder.archived_at.is_(None),
            )
            .order_by(SkillFolder.sort_order, SkillFolder.name, SkillFolder.id)
        )
    )


def create_folder(
    db: Session,
    *,
    user: User,
    scope_type: str,
    scope_id: str | None,
    parent_folder_id: str | None,
    name: str,
    sort_order: int,
) -> SkillFolder:
    canonical_scope_id = authorize_scope(
        db, user=user, scope_type=scope_type, scope_id=scope_id, write=True
    )
    if parent_folder_id is not None:
        parent = require_folder(db, user, parent_folder_id, write=True)
        _require_same_scope(parent, scope_type, canonical_scope_id)
    clean_name, normalized_name = normalize_folder_name(name)
    _require_unique_folder_name(
        db,
        scope_type=scope_type,
        scope_id=canonical_scope_id,
        parent_folder_id=parent_folder_id,
        normalized_name=normalized_name,
    )
    folder = SkillFolder(
        scope_type=scope_type,
        scope_id=canonical_scope_id,
        parent_folder_id=parent_folder_id,
        name=clean_name,
        normalized_name=normalized_name,
        sort_order=sort_order,
        is_system=False,
        created_by_user_id=user.id,
    )
    db.add(folder)
    db.flush()
    return folder


def require_folder(
    db: Session, user: User, folder_id: str, *, write: bool = False
) -> SkillFolder:
    folder = db.get(SkillFolder, folder_id)
    if folder is None or folder.archived_at is not None:
        raise ApiProblem(404, "folder_not_found", "Skill Folder를 찾을 수 없습니다.")
    authorize_scope(
        db,
        user=user,
        scope_type=folder.scope_type,
        scope_id=folder.scope_id,
        write=write,
    )
    return folder


def _require_same_scope(folder: SkillFolder, scope_type: str, scope_id: str) -> None:
    if folder.scope_type != scope_type or folder.scope_id != scope_id:
        raise ApiProblem(
            409, "folder_scope_mismatch", "다른 범위의 Folder로 이동할 수 없습니다."
        )


def _require_unique_folder_name(
    db: Session,
    *,
    scope_type: str,
    scope_id: str,
    parent_folder_id: str | None,
    normalized_name: str,
    excluding_id: str | None = None,
) -> None:
    parent_filter = (
        SkillFolder.parent_folder_id.is_(None)
        if parent_folder_id is None
        else SkillFolder.parent_folder_id == parent_folder_id
    )
    query = select(SkillFolder).where(
        SkillFolder.scope_type == scope_type,
        SkillFolder.scope_id == scope_id,
        parent_filter,
        SkillFolder.normalized_name == normalized_name,
        SkillFolder.archived_at.is_(None),
    )
    if excluding_id is not None:
        query = query.where(SkillFolder.id != excluding_id)
    if db.scalar(query) is not None:
        raise ApiProblem(
            409, "folder_name_exists", "같은 위치에 동명 Folder가 있습니다."
        )


def update_folder(
    db: Session,
    *,
    user: User,
    folder_id: str,
    name: str | None,
    sort_order: int | None,
) -> SkillFolder:
    folder = require_folder(db, user, folder_id, write=True)
    if name is not None:
        if folder.is_system:
            raise ApiProblem(
                409, "system_folder_immutable", "시스템 Folder는 변경할 수 없습니다."
            )
        clean_name, normalized_name = normalize_folder_name(name)
        _require_unique_folder_name(
            db,
            scope_type=folder.scope_type,
            scope_id=folder.scope_id,
            parent_folder_id=folder.parent_folder_id,
            normalized_name=normalized_name,
            excluding_id=folder.id,
        )
        folder.name = clean_name
        folder.normalized_name = normalized_name
    if sort_order is not None:
        folder.sort_order = sort_order
    folder.updated_at = utc_now()
    db.flush()
    return folder


def move_folder(
    db: Session,
    *,
    user: User,
    folder_id: str,
    parent_folder_id: str | None,
) -> SkillFolder:
    folder = require_folder(db, user, folder_id, write=True)
    if folder.is_system:
        raise ApiProblem(
            409, "system_folder_immutable", "시스템 Folder는 이동할 수 없습니다."
        )
    if parent_folder_id == folder.id:
        raise ApiProblem(
            409, "folder_cycle", "Folder를 자기 아래로 이동할 수 없습니다."
        )
    if parent_folder_id is not None:
        parent = require_folder(db, user, parent_folder_id, write=True)
        _require_same_scope(parent, folder.scope_type, folder.scope_id)
        cursor: SkillFolder | None = parent
        while cursor is not None:
            if cursor.id == folder.id:
                raise ApiProblem(
                    409, "folder_cycle", "Folder cycle을 만들 수 없습니다."
                )
            cursor = (
                db.get(SkillFolder, cursor.parent_folder_id)
                if cursor.parent_folder_id
                else None
            )
    _require_unique_folder_name(
        db,
        scope_type=folder.scope_type,
        scope_id=folder.scope_id,
        parent_folder_id=parent_folder_id,
        normalized_name=folder.normalized_name,
        excluding_id=folder.id,
    )
    folder.parent_folder_id = parent_folder_id
    folder.updated_at = utc_now()
    db.flush()
    return folder


def move_skill_to_folder(
    db: Session,
    *,
    user: User,
    skill_id: str,
    folder_id: str,
    scope_type: str,
    scope_id: str | None,
) -> SkillFolderPlacement:
    extension = require_extension(db, user, skill_id)
    if extension.kind != "skill":
        raise ApiProblem(409, "not_a_skill", "Skill만 Folder에 배치할 수 있습니다.")
    canonical_scope_id = authorize_scope(
        db, user=user, scope_type=scope_type, scope_id=scope_id, write=True
    )
    folder = require_folder(db, user, folder_id, write=True)
    _require_same_scope(folder, scope_type, canonical_scope_id)
    placement = db.scalar(
        select(SkillFolderPlacement).where(
            SkillFolderPlacement.skill_id == skill_id,
            SkillFolderPlacement.scope_type == scope_type,
            SkillFolderPlacement.scope_id == canonical_scope_id,
        )
    )
    if placement is None:
        placement = SkillFolderPlacement(
            folder_id=folder.id,
            skill_id=skill_id,
            scope_type=scope_type,
            scope_id=canonical_scope_id,
            moved_by_user_id=user.id,
        )
        db.add(placement)
    else:
        placement.folder_id = folder.id
        placement.moved_by_user_id = user.id
        placement.moved_at = utc_now()
    db.flush()
    return placement


def _require_unique_children_at_destination(
    db: Session, folder: SkillFolder, destination: SkillFolder
) -> None:
    children = list(
        db.scalars(
            select(SkillFolder).where(
                SkillFolder.parent_folder_id == folder.id,
                SkillFolder.archived_at.is_(None),
            )
        )
    )
    for child in children:
        _require_unique_folder_name(
            db,
            scope_type=folder.scope_type,
            scope_id=folder.scope_id,
            parent_folder_id=destination.id,
            normalized_name=child.normalized_name,
            excluding_id=child.id,
        )


def delete_folder(
    db: Session,
    *,
    user: User,
    folder_id: str,
    destination_folder_id: str | None,
) -> SkillFolder:
    folder = require_folder(db, user, folder_id, write=True)
    if folder.is_system:
        raise ApiProblem(
            409, "system_folder_immutable", "시스템 Folder는 삭제할 수 없습니다."
        )
    destination = (
        require_folder(db, user, destination_folder_id, write=True)
        if destination_folder_id
        else ensure_unclassified_folder(
            db,
            user=user,
            scope_type=folder.scope_type,
            scope_id=folder.scope_id,
        )
    )
    _require_same_scope(destination, folder.scope_type, folder.scope_id)
    if destination.id == folder.id:
        raise ApiProblem(
            409,
            "invalid_folder_destination",
            "삭제 대상 Folder는 destination이 될 수 없습니다.",
        )
    _require_unique_children_at_destination(db, folder, destination)
    for child in db.scalars(
        select(SkillFolder).where(SkillFolder.parent_folder_id == folder.id)
    ):
        child.parent_folder_id = destination.id
        child.updated_at = utc_now()
    for placement in db.scalars(
        select(SkillFolderPlacement).where(SkillFolderPlacement.folder_id == folder.id)
    ):
        placement.folder_id = destination.id
        placement.moved_by_user_id = user.id
        placement.moved_at = utc_now()
    folder.archived_at = utc_now()
    folder.updated_at = utc_now()
    db.flush()
    return folder


def extension_payloads(
    db: Session,
    extensions: list[Extension],
    *,
    user: User,
    include_draft_package: bool = True,
) -> list[dict[str, Any]]:
    if not extensions:
        return []
    extension_ids = [extension.id for extension in extensions]
    role_by_extension_id = {
        skill_id: role
        for skill_id, role in db.execute(
            select(SkillOwnership.skill_id, SkillOwnership.role).where(
                SkillOwnership.skill_id.in_(extension_ids),
                SkillOwnership.principal_type == "user",
                SkillOwnership.principal_id == user.id,
            )
        )
    }
    draft_options: list[Any] = [
        ExtensionDraft.id,
        ExtensionDraft.extension_id,
        ExtensionDraft.owner_user_id,
        ExtensionDraft.base_version_id,
        ExtensionDraft.current_revision,
        ExtensionDraft.current_digest,
        ExtensionDraft.status,
        ExtensionDraft.updated_at,
    ]
    if include_draft_package:
        draft_options.append(ExtensionDraft.package_json)
    drafts = list(
        db.scalars(
            select(ExtensionDraft)
            .where(
                ExtensionDraft.extension_id.in_(extension_ids),
                ExtensionDraft.owner_user_id == user.id,
            )
            .options(load_only(*draft_options))
        )
    )
    draft_by_extension_id = {draft.extension_id: draft for draft in drafts}
    all_versions = list(
        db.scalars(
            select(ExtensionVersion)
            .where(ExtensionVersion.extension_id.in_(extension_ids))
            .options(
                load_only(
                    ExtensionVersion.id,
                    ExtensionVersion.extension_id,
                    ExtensionVersion.version_number,
                    ExtensionVersion.parent_version_id,
                    ExtensionVersion.package_digest,
                    ExtensionVersion.status,
                    ExtensionVersion.manifest_json,
                    ExtensionVersion.change_summary,
                    ExtensionVersion.change_type,
                    ExtensionVersion.restored_from_version_id,
                    ExtensionVersion.created_by_user_id,
                    ExtensionVersion.created_at,
                    ExtensionVersion.published_at,
                )
            )
            .order_by(ExtensionVersion.extension_id, ExtensionVersion.version_number)
        )
    )
    versions_by_extension_id: dict[str, list[ExtensionVersion]] = {}
    version_by_id: dict[str, ExtensionVersion] = {}
    for version in all_versions:
        versions_by_extension_id.setdefault(version.extension_id, []).append(version)
        version_by_id[version.id] = version
    all_ownerships = list(
        db.scalars(
            select(SkillOwnership)
            .where(SkillOwnership.skill_id.in_(extension_ids))
            .order_by(
                SkillOwnership.skill_id,
                SkillOwnership.created_at,
                SkillOwnership.id,
            )
        )
    )
    ownerships_by_extension_id: dict[str, list[SkillOwnership]] = {}
    for ownership in all_ownerships:
        ownerships_by_extension_id.setdefault(ownership.skill_id, []).append(ownership)
    principal_ids = {
        ownership.principal_id
        for ownership in all_ownerships
        if ownership.principal_type == "user"
    } | {version.created_by_user_id for version in all_versions}
    principal_users = {
        principal.id: principal
        for principal in db.scalars(
            select(User).where(User.id.in_(principal_ids))
        )
    } if principal_ids else {}
    project_ids = list(
        db.scalars(
            select(ProjectMembership.project_id).where(
                ProjectMembership.user_id == user.id,
                ProjectMembership.status == "active",
            )
        )
    )
    installed_extension_ids = set(
        db.scalars(
            select(ExtensionInstallation.extension_id).where(
                ExtensionInstallation.extension_id.in_(extension_ids),
                ExtensionInstallation.removed_at.is_(None),
                or_(
                    (
                        (ExtensionInstallation.scope_type == "user")
                        & (ExtensionInstallation.scope_id == user.id)
                    ),
                    (
                        (ExtensionInstallation.scope_type == "organization")
                        & (ExtensionInstallation.scope_id == user.organization_id)
                    ),
                    (
                        (ExtensionInstallation.scope_type == "project")
                        & (ExtensionInstallation.scope_id.in_(project_ids))
                    ),
                ),
            )
        )
    )
    payloads: list[dict[str, Any]] = []
    for extension in extensions:
        role = (
            "owner"
            if user.role == "admin" or extension.owner_user_id == user.id
            else role_by_extension_id.get(extension.id)
        )
        can_manage = role in {"owner", "maintainer"}
        versions = versions_by_extension_id.get(extension.id, [])
        if not can_manage:
            versions = [
                version
                for version in versions
                if version.status == "published"
                or version.created_by_user_id == user.id
            ]
        ownerships = ownerships_by_extension_id.get(extension.id, [])
        latest_manifest_tags: list[str] = []
        if versions:
            raw_tags = versions[-1].manifest_json.get("tags")
            if isinstance(raw_tags, list):
                latest_manifest_tags = _normalize_skill_tags(
                    [item for item in raw_tags if isinstance(item, str)]
                )
        payload: dict[str, Any] = {
            "id": extension.id,
            "kind": extension.kind,
            "slug": extension.slug,
            "name": extension.name,
            "description": extension.description,
            "tags": extension.tags_json
            if extension.tags_json is not None
            else latest_manifest_tags,
            "visibility": extension.visibility,
            "ownerUserId": extension.owner_user_id,
            "creatorUserId": extension.creator_user_id,
            "currentUserRole": role,
            "ownerships": [
                {
                    "id": item.id,
                    "principalType": item.principal_type,
                    "principalId": item.principal_id,
                    "role": item.role,
                    "displayName": (
                        principal_users[item.principal_id].display_name
                        or principal_users[item.principal_id].login_id
                        if item.principal_id in principal_users
                        else item.principal_id
                    ),
                    "createdAt": item.created_at,
                }
                for item in ownerships
            ],
            "latestPublishedVersionId": extension.latest_published_version_id,
            "versions": [
                version_payload(
                    version,
                    include_package=False,
                    created_by_display_name=(
                        principal_users[version.created_by_user_id].display_name
                        or principal_users[version.created_by_user_id].login_id
                        if version.created_by_user_id in principal_users
                        else None
                    ),
                )
                for version in versions
            ],
            "createdAt": extension.created_at,
            "updatedAt": extension.updated_at,
            "archivedAt": extension.archived_at,
            "purgesAt": (
                extension.archived_at + _SKILL_TRASH_RETENTION
                if extension.archived_at is not None
                else None
            ),
            "canEdit": can_manage,
            "canEditTags": can_manage,
            "canCreateDraft": can_manage or extension.id in installed_extension_ids,
            "canDelete": role == "owner",
        }
        draft = draft_by_extension_id.get(extension.id)
        if draft is not None:
            payload["draft"] = draft_payload(
                draft,
                base_version=version_by_id.get(draft.base_version_id or ""),
                include_package=include_draft_package,
            )
        payloads.append(payload)
    return payloads


def extension_payload(
    db: Session,
    extension: Extension,
    *,
    user: User,
    include_draft_package: bool = True,
) -> dict[str, Any]:
    return extension_payloads(
        db,
        [extension],
        user=user,
        include_draft_package=include_draft_package,
    )[0]


def draft_payload(
    draft: ExtensionDraft,
    *,
    base_version: ExtensionVersion | None,
    include_package: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": draft.id,
        "extensionId": draft.extension_id,
        "revision": draft.current_revision,
        "digest": draft.current_digest,
        "baseVersionId": draft.base_version_id,
        "baseVersion": base_version.version_number if base_version else None,
        "dirty": base_version is None
        or base_version.package_digest != draft.current_digest,
        "status": draft.status,
        "etag": draft_etag(draft),
        "updatedAt": draft.updated_at,
    }
    if include_package:
        result["package"] = {"files": draft.package_json}
    return result


def version_payload(
    version: ExtensionVersion,
    *,
    include_package: bool,
    created_by_display_name: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": version.id,
        "extensionId": version.extension_id,
        "version": version.version_number,
        "parentVersionId": version.parent_version_id,
        "restoredFromVersionId": version.restored_from_version_id,
        "digest": version.package_digest,
        "status": version.status,
        "changeType": version.change_type,
        "changeSummary": version.change_summary,
        "createdByUserId": version.created_by_user_id,
        "createdByDisplayName": created_by_display_name,
        "manifest": version.manifest_json,
        "createdAt": version.created_at,
        "publishedAt": version.published_at,
    }
    if include_package:
        result["package"] = {"files": version.package_json}
    return result


def installation_payload(
    installation: ExtensionInstallation,
) -> dict[str, Any]:
    return {
        "id": installation.id,
        "extensionId": installation.extension_id,
        "versionId": installation.version_id,
        "scopeType": installation.scope_type,
        "scopeId": installation.scope_id,
        "enabled": installation.enabled,
        "projectIds": installation.project_ids_json,
        "settings": installation.settings_json,
        "installedAt": installation.installed_at,
    }


def folder_payload(folder: SkillFolder) -> dict[str, Any]:
    return {
        "id": folder.id,
        "scopeType": folder.scope_type,
        "scopeId": folder.scope_id,
        "parentFolderId": folder.parent_folder_id,
        "name": folder.name,
        "sortOrder": folder.sort_order,
        "isSystem": folder.is_system,
        "createdAt": folder.created_at,
        "updatedAt": folder.updated_at,
    }
