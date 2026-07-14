from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...db import get_db
from ...extensions.repository_catalog import (
    repository_catalog_admin,
    repository_catalog_revision,
    sync_repository_catalog,
)
from ...extensions.catalog import list_skill_catalog, set_skill_catalog_like
from ...extensions.schemas import (
    DraftActivation,
    DraftSaveVersion,
    DraftUpdate,
    ExtensionCreate,
    ExtensionPatch,
    FolderCreate,
    FolderMove,
    FolderPatch,
    InstallationCreate,
    InstallationPatch,
    PublishVersion,
    SkillFolderMove,
    SkillOwnershipCreate,
)
from ...extensions.service import (
    activate_draft,
    add_skill_ownership,
    can_view_skill_package,
    can_manage_skill,
    create_folder,
    create_skill,
    checkout_draft,
    delete_folder,
    delete_skill,
    draft_etag,
    draft_payload,
    extension_payload,
    folder_payload,
    install_version,
    installation_payload,
    list_extensions,
    list_folders,
    list_installations,
    list_trashed_extensions,
    move_folder,
    move_skill_to_folder,
    purge_expired_trashed_skills,
    publish_version,
    require_extension,
    remove_skill_ownership,
    restore_skill,
    save_draft_version,
    set_installation_enabled,
    uninstall,
    update_draft,
    update_extension_metadata,
    update_folder,
    version_payload,
)
from ...models import ExtensionDraft, ExtensionVersion, User
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem


router = APIRouter(tags=["extensions"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/extensions")
def get_extensions(
    query: str | None = Query(default=None, max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    if purge_expired_trashed_skills(db):
        db.commit()
    return [
        extension_payload(
            db,
            extension,
            user=user,
        )
        for extension in list_extensions(db, user=user, query=query)
    ]


@router.get("/extensions/catalog")
def get_skill_catalog(
    query: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=80),
    tag: str | None = Query(default=None, max_length=40),
    sort: Literal["popular", "runs", "likes", "recent", "name"] = "popular",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return list_skill_catalog(
        db,
        user=user,
        query=query,
        category=category,
        tag=tag,
        sort=sort,
        offset=offset,
        limit=limit,
    )


@router.put("/extensions/{extension_id}/like")
def put_skill_catalog_like(
    extension_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = set_skill_catalog_like(
        db, user=context.user, extension_id=extension_id, liked=True
    )
    db.commit()
    return result


@router.delete("/extensions/{extension_id}/like")
def delete_skill_catalog_like(
    extension_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = set_skill_catalog_like(
        db, user=context.user, extension_id=extension_id, liked=False
    )
    db.commit()
    return result


@router.post("/extensions/repository-sync")
def post_extension_repository_sync(
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    admin = repository_catalog_admin(db, organization_id=context.user.organization_id)
    if admin is None:
        raise ApiProblem(
            409,
            "repository_catalog_owner_unavailable",
            "Repository 확장을 등록할 활성 관리자 계정을 찾을 수 없습니다.",
        )
    skills_changed, mcp_changed = sync_repository_catalog(db, admin=admin)
    db.commit()
    return {
        "skillsChanged": skills_changed,
        "mcpChanged": mcp_changed,
        "revision": repository_catalog_revision(
            db, organization_id=context.user.organization_id
        ),
    }


@router.get("/extensions/repository-state")
def get_extension_repository_state(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    return {
        "revision": repository_catalog_revision(
            db, organization_id=user.organization_id
        )
    }


@router.get("/extensions/trash")
def get_trashed_extensions(
    query: str | None = Query(default=None, max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    if purge_expired_trashed_skills(db):
        db.commit()
    return [
        extension_payload(db, extension, user=user)
        for extension in list_trashed_extensions(db, user=user, query=query)
    ]


@router.get("/extensions/{extension_id}")
def get_extension(
    extension_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    extension = require_extension(db, user, extension_id)
    return extension_payload(db, extension, user=user)


@router.post("/extensions", status_code=201)
def post_extension(
    payload: ExtensionCreate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    extension, draft = create_skill(
        db,
        user=context.user,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        package_files=payload.package.files,
        project_id=payload.project_id,
        source_conversation_id=payload.source_conversation_id,
    )
    record_audit(
        db,
        action="extension_created",
        target_type="extension",
        target_id=extension.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"kind": "skill", "visibility": "private"},
    )
    db.commit()
    response.headers["ETag"] = draft_etag(draft)
    return extension_payload(db, extension, user=context.user)


@router.patch("/extensions/{extension_id}")
def patch_extension(
    extension_id: str,
    payload: ExtensionPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    extension = update_extension_metadata(
        db,
        user=context.user,
        extension_id=extension_id,
        name=payload.name,
        description=payload.description,
    )
    record_audit(
        db,
        action="extension_metadata_updated",
        target_type="extension",
        target_id=extension.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return extension_payload(db, extension, user=context.user)


@router.delete("/extensions/{extension_id}", status_code=204)
def delete_extension(
    extension_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    extension = delete_skill(db, user=context.user, extension_id=extension_id)
    record_audit(
        db,
        action="extension_trashed",
        target_type="extension",
        target_id=extension.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"kind": extension.kind},
    )
    db.commit()
    return Response(status_code=204)


@router.post("/extensions/{extension_id}/restore")
def post_extension_restore(
    extension_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    extension = restore_skill(db, user=context.user, extension_id=extension_id)
    record_audit(
        db,
        action="extension_restored",
        target_type="extension",
        target_id=extension.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"kind": extension.kind},
    )
    db.commit()
    return extension_payload(db, extension, user=context.user)


@router.post("/extensions/{extension_id}/draft")
def post_extension_draft_checkout(
    extension_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    draft = checkout_draft(db, user=context.user, extension_id=extension_id)
    record_audit(
        db,
        action="skill_draft_checked_out",
        target_type="extension_draft",
        target_id=draft.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "extension_id": extension_id,
            "base_version_id": draft.base_version_id,
        },
    )
    db.commit()
    base = (
        db.get(ExtensionVersion, draft.base_version_id)
        if draft.base_version_id
        else None
    )
    return draft_payload(draft, base_version=base, include_package=True)


@router.post("/skills/{skill_id}/ownerships", status_code=201)
def post_skill_ownership(
    skill_id: str,
    payload: SkillOwnershipCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ownership = add_skill_ownership(
        db,
        user=context.user,
        extension_id=skill_id,
        principal_user_id=payload.user_id,
        role=payload.role,
    )
    record_audit(
        db,
        action="skill_ownership_added",
        target_type="skill_ownership",
        target_id=ownership.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "skill_id": skill_id,
            "principal_type": ownership.principal_type,
            "principal_id": ownership.principal_id,
            "role": ownership.role,
        },
    )
    db.commit()
    return extension_payload(
        db, require_extension(db, context.user, skill_id), user=context.user
    )


@router.delete("/skills/{skill_id}/ownerships/{ownership_id}", status_code=204)
def delete_skill_ownership(
    skill_id: str,
    ownership_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    ownership = remove_skill_ownership(
        db,
        user=context.user,
        extension_id=skill_id,
        ownership_id=ownership_id,
    )
    record_audit(
        db,
        action="skill_ownership_removed",
        target_type="skill_ownership",
        target_id=ownership.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"skill_id": skill_id},
    )
    db.commit()
    return Response(status_code=204)


@router.patch("/skill-drafts/{draft_id}")
def patch_skill_draft(
    draft_id: str,
    payload: DraftUpdate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    draft, changed = update_draft(
        db,
        user=context.user,
        draft_id=draft_id,
        expected_revision=payload.expected_revision,
        expected_digest=payload.expected_digest,
        package_files=payload.package.files,
        change_summary=payload.change_summary,
    )
    record_audit(
        db,
        action="skill_draft_updated" if changed else "skill_draft_unchanged",
        target_type="extension_draft",
        target_id=draft.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"revision": draft.current_revision, "digest": draft.current_digest},
    )
    db.commit()
    response.headers["ETag"] = draft_etag(draft)
    base = (
        db.get(ExtensionVersion, draft.base_version_id)
        if draft.base_version_id
        else None
    )
    return draft_payload(draft, base_version=base, include_package=True)


@router.post("/skill-drafts/{draft_id}/activate")
def post_skill_draft_activation(
    draft_id: str,
    payload: DraftActivation,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    binding = activate_draft(
        db,
        user=context.user,
        draft_id=draft_id,
        project_id=payload.project_id,
        enabled=payload.enabled,
    )
    record_audit(
        db,
        action="skill_draft_binding_changed",
        target_type="extension_draft_binding",
        target_id=binding.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"enabled": binding.enabled, "project_id": binding.project_id},
    )
    db.commit()
    return {
        "id": binding.id,
        "draftId": binding.draft_id,
        "projectId": binding.project_id,
        "enabled": binding.enabled,
        "boundAt": binding.bound_at,
    }


@router.post("/skill-drafts/{draft_id}/save-version", status_code=201)
def post_skill_version(
    draft_id: str,
    payload: DraftSaveVersion,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    version = save_draft_version(
        db,
        user=context.user,
        draft_id=draft_id,
        expected_revision=payload.expected_revision,
        expected_digest=payload.expected_digest,
        base_version_id=payload.base_version_id,
        manifest=payload.manifest,
    )
    record_audit(
        db,
        action="skill_version_saved",
        target_type="extension_version",
        target_id=version.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"version": version.version_number, "digest": version.package_digest},
    )
    db.commit()
    return version_payload(version, include_package=True)


@router.get("/extension-versions/{version_id}")
def get_extension_version(
    version_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    version = db.get(ExtensionVersion, version_id)
    if version is None:
        raise ApiProblem(404, "version_not_found", "Skill version을 찾을 수 없습니다.")
    extension = require_extension(db, user, version.extension_id)
    if not can_manage_skill(db, user, extension) and (
        version.status != "published" and version.created_by_user_id != user.id
    ):
        raise ApiProblem(404, "version_not_found", "Skill version을 찾을 수 없습니다.")
    if not can_view_skill_package(db, user, extension):
        raise ApiProblem(
            404,
            "version_not_found",
            "설치된 Skill version만 열 수 있습니다.",
        )
    return version_payload(version, include_package=True)


@router.post("/extension-versions/{version_id}/publish")
def post_extension_version_publish(
    version_id: str,
    _payload: PublishVersion,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    extension, version = publish_version(db, user=context.user, version_id=version_id)
    record_audit(
        db,
        action="extension_published",
        target_type="extension_version",
        target_id=version.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"extension_id": extension.id, "version": version.version_number},
    )
    db.commit()
    return version_payload(version, include_package=False)


@router.get("/extension-installations")
def get_extension_installations(
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        installation_payload(item)
        for item in list_installations(db, user=user, project_id=project_id)
    ]


@router.post("/extension-installations", status_code=201)
def post_extension_installation(
    payload: InstallationCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    installation = install_version(
        db,
        user=context.user,
        version_id=payload.version_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        enabled=payload.enabled,
        settings=payload.settings,
    )
    record_audit(
        db,
        action="extension_installed",
        target_type="extension_installation",
        target_id=installation.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "extension_id": installation.extension_id,
            "version_id": installation.version_id,
            "scope_type": installation.scope_type,
            "scope_id": installation.scope_id,
        },
    )
    db.commit()
    return installation_payload(installation)


@router.patch("/extension-installations/{installation_id}")
def patch_extension_installation(
    installation_id: str,
    payload: InstallationPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    installation = set_installation_enabled(
        db,
        user=context.user,
        installation_id=installation_id,
        enabled=payload.enabled,
    )
    record_audit(
        db,
        action="extension_installation_changed",
        target_type="extension_installation",
        target_id=installation.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"enabled": installation.enabled},
    )
    db.commit()
    return installation_payload(installation)


@router.delete("/extension-installations/{installation_id}", status_code=204)
def delete_extension_installation(
    installation_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    installation = uninstall(db, user=context.user, installation_id=installation_id)
    record_audit(
        db,
        action="extension_uninstalled",
        target_type="extension_installation",
        target_id=installation.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return Response(status_code=204)


@router.get("/skill-folders")
def get_skill_folders(
    scope_type: Literal["user", "project", "organization"] = "user",
    scope_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        folder_payload(folder)
        for folder in list_folders(
            db,
            user=user,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    ]


@router.post("/skill-folders", status_code=201)
def post_skill_folder(
    payload: FolderCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    folder = create_folder(
        db,
        user=context.user,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        parent_folder_id=payload.parent_folder_id,
        name=payload.name,
        sort_order=payload.sort_order,
    )
    record_audit(
        db,
        action="skill_folder_created",
        target_type="skill_folder",
        target_id=folder.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return folder_payload(folder)


@router.patch("/skill-folders/{folder_id}")
def patch_skill_folder(
    folder_id: str,
    payload: FolderPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    folder = update_folder(
        db,
        user=context.user,
        folder_id=folder_id,
        name=payload.name,
        sort_order=payload.sort_order,
    )
    record_audit(
        db,
        action="skill_folder_changed",
        target_type="skill_folder",
        target_id=folder.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return folder_payload(folder)


@router.post("/skill-folders/{folder_id}/move")
def post_skill_folder_move(
    folder_id: str,
    payload: FolderMove,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    folder = move_folder(
        db,
        user=context.user,
        folder_id=folder_id,
        parent_folder_id=payload.parent_folder_id,
    )
    record_audit(
        db,
        action="skill_folder_moved",
        target_type="skill_folder",
        target_id=folder.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"parent_folder_id": folder.parent_folder_id},
    )
    db.commit()
    return folder_payload(folder)


@router.delete("/skill-folders/{folder_id}", status_code=204)
def delete_skill_folder(
    folder_id: str,
    request: Request,
    destination_folder_id: str | None = Query(default=None),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    folder = delete_folder(
        db,
        user=context.user,
        folder_id=folder_id,
        destination_folder_id=destination_folder_id,
    )
    record_audit(
        db,
        action="skill_folder_deleted",
        target_type="skill_folder",
        target_id=folder.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return Response(status_code=204)


@router.post("/skills/{skill_id}/move-folder")
def post_skill_move_folder(
    skill_id: str,
    payload: SkillFolderMove,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    before = db.scalar(
        select(ExtensionVersion.package_digest)
        .where(ExtensionVersion.extension_id == skill_id)
        .order_by(ExtensionVersion.version_number.desc())
        .limit(1)
    )
    draft = db.scalar(
        select(ExtensionDraft).where(
            ExtensionDraft.extension_id == skill_id,
            ExtensionDraft.owner_user_id == context.user.id,
        )
    )
    placement = move_skill_to_folder(
        db,
        user=context.user,
        skill_id=skill_id,
        folder_id=payload.folder_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
    )
    record_audit(
        db,
        action="skill_folder_placement_changed",
        target_type="extension",
        target_id=skill_id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "folder_id": placement.folder_id,
            "scope_type": placement.scope_type,
            "scope_id": placement.scope_id,
            "version_digest": before,
            "draft_digest": draft.current_digest if draft else None,
        },
    )
    db.commit()
    return {
        "id": placement.id,
        "skillId": placement.skill_id,
        "folderId": placement.folder_id,
        "scopeType": placement.scope_type,
        "scopeId": placement.scope_id,
        "movedAt": placement.moved_at,
    }
