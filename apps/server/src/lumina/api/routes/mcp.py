from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...authorization import require_admin
from ...config import Settings, get_settings
from ...db import get_db
from ...mcp.runtime import (
    McpRuntime,
    McpRuntimeError,
    load_installation_server_config,
)
from ...mcp.schemas import (
    McpApproval,
    McpDefinitionCreate,
    McpDefinitionStatusPatch,
    McpInstallationCreate,
    McpInstallationPatch,
    McpRevisionCreate,
    McpSecretBindingInput,
)
from ...mcp.service import (
    add_configuration_revision,
    approve_revision,
    bind_secret_reference,
    create_definition,
    definition_payload,
    install_definition,
    installation_payload,
    list_admin_definitions,
    list_catalog,
    list_installations,
    mcp_skill_wrappers,
    require_installation,
    set_definition_status,
    update_installation,
    unbind_secret_reference,
    uninstall,
)
from ...models import McpInstallation, User
from ..dependencies import AuthContext, get_current_user, require_csrf


router = APIRouter(tags=["mcp"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/admin/mcp-definitions")
def get_admin_mcp_definitions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_admin(user)
    wrappers = mcp_skill_wrappers(db, organization_id=user.organization_id)
    return [
        definition_payload(
            db,
            definition,
            include_all_revisions=True,
            include_configuration=True,
            skill_wrappers=wrappers,
        )
        for definition in list_admin_definitions(db, user=user)
    ]


@router.post("/admin/mcp-definitions", status_code=201)
def post_admin_mcp_definition(
    payload: McpDefinitionCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(context.user)
    definition, revision = create_definition(
        db,
        user=context.user,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        configuration=payload.configuration.model_dump(mode="json"),
    )
    record_audit(
        db,
        action="mcp_definition_created",
        target_type="mcp_definition",
        target_id=definition.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "revision_id": revision.id,
            "revision": revision.revision_number,
            "digest": revision.config_digest,
            "transport": revision.transport,
            "validation_status": revision.validation_status,
        },
    )
    db.commit()
    return definition_payload(
        db,
        definition,
        include_all_revisions=True,
        include_configuration=True,
    )


@router.post("/admin/mcp-definitions/{definition_id}/revisions", status_code=201)
def post_admin_mcp_revision(
    definition_id: str,
    payload: McpRevisionCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(context.user)
    revision = add_configuration_revision(
        db,
        user=context.user,
        definition_id=definition_id,
        configuration=payload.configuration.model_dump(mode="json"),
    )
    record_audit(
        db,
        action="mcp_configuration_revision_created",
        target_type="mcp_configuration_revision",
        target_id=revision.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "definition_id": definition_id,
            "revision": revision.revision_number,
            "digest": revision.config_digest,
            "validation_status": revision.validation_status,
            "health_status": revision.health_status,
            "schema_status": revision.schema_status,
        },
    )
    db.commit()
    definition = next(
        item
        for item in list_admin_definitions(db, user=context.user)
        if item.id == definition_id
    )
    return definition_payload(
        db,
        definition,
        include_all_revisions=True,
        include_configuration=True,
    )


@router.post("/admin/mcp-definitions/{definition_id}/approve")
def post_admin_mcp_approval(
    definition_id: str,
    payload: McpApproval,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(context.user)
    definition, revision = approve_revision(
        db,
        user=context.user,
        definition_id=definition_id,
        revision_id=payload.configuration_revision_id,
    )
    record_audit(
        db,
        action="mcp_definition_approved",
        target_type="mcp_definition",
        target_id=definition.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "revision_id": revision.id,
            "revision": revision.revision_number,
            "digest": revision.config_digest,
        },
    )
    db.commit()
    return definition_payload(
        db,
        definition,
        include_all_revisions=True,
        include_configuration=True,
    )


@router.patch("/admin/mcp-definitions/{definition_id}/status")
def patch_admin_mcp_status(
    definition_id: str,
    payload: McpDefinitionStatusPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(context.user)
    definition = set_definition_status(
        db,
        user=context.user,
        definition_id=definition_id,
        status=payload.status,
    )
    record_audit(
        db,
        action=f"mcp_definition_{payload.status}",
        target_type="mcp_definition",
        target_id=definition.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        reason=payload.reason or None,
        metadata={"status": payload.status},
    )
    db.commit()
    return definition_payload(
        db,
        definition,
        include_all_revisions=True,
        include_configuration=True,
    )


@router.get("/mcp/catalog")
def get_mcp_catalog(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    wrappers = mcp_skill_wrappers(db, organization_id=user.organization_id)
    return [
        definition_payload(
            db,
            definition,
            include_all_revisions=False,
            include_configuration=False,
            skill_wrappers=wrappers,
        )
        for definition in list_catalog(db, user=user)
    ]


@router.get("/mcp/installations")
def get_mcp_installations(
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        installation_payload(db, installation, user=user)
        for installation in list_installations(db, user=user, project_id=project_id)
    ]


@router.post("/mcp/installations/{installation_id}/verify")
async def verify_mcp_installation(
    installation_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    installation = require_installation(
        db, user=context.user, installation_id=installation_id, write=False
    )
    payload = installation_payload(db, installation, user=context.user)
    if (
        not installation.enabled
        or payload["secretResolutionStatus"] not in {"ready", "not_required"}
    ):
        payload["healthStatus"] = "not_connected"
        payload["schemaStatus"] = "pending"
        return payload

    runtime = McpRuntime(settings)
    try:
        config = load_installation_server_config(
            db, installation, user=context.user
        )
        await runtime.prepare_servers((config,))
    except McpRuntimeError as exc:
        payload["healthStatus"] = "failed"
        payload["schemaStatus"] = "invalid" if exc.stage == "schema" else "pending"
        payload["connectionErrorCode"] = exc.code
        return payload
    except Exception:
        payload["healthStatus"] = "failed"
        payload["schemaStatus"] = "pending"
        payload["connectionErrorCode"] = "mcp_verification_failed"
        return payload
    finally:
        await runtime.close()

    payload["healthStatus"] = "connected"
    payload["schemaStatus"] = "valid"
    payload["ready"] = True
    return payload


@router.post("/mcp/installations", status_code=201)
def post_mcp_installation(
    payload: McpInstallationCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    installation = install_definition(
        db,
        user=context.user,
        definition_id=payload.definition_id,
        revision_id=payload.configuration_revision_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        enabled=payload.enabled,
        tool_allowlist=payload.tool_allowlist,
    )
    record_audit(
        db,
        action="mcp_installed",
        target_type="mcp_installation",
        target_id=installation.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "definition_id": installation.definition_id,
            "configuration_revision_id": installation.configuration_revision_id,
            "scope_type": installation.scope_type,
            "scope_id": installation.scope_id,
            "tool_allowlist": installation.tool_allowlist_json,
        },
    )
    db.commit()
    return installation_payload(db, installation, user=context.user)


@router.patch("/mcp/installations/{installation_id}")
def patch_mcp_installation(
    installation_id: str,
    payload: McpInstallationPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    installation = update_installation(
        db,
        user=context.user,
        installation_id=installation_id,
        enabled=payload.enabled,
        project_ids=payload.project_ids,
        update_project_ids="project_ids" in payload.model_fields_set,
    )
    record_audit(
        db,
        action="mcp_installation_changed",
        target_type="mcp_installation",
        target_id=installation.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "enabled": installation.enabled,
            "project_ids": installation.project_ids_json,
        },
    )
    db.commit()
    return installation_payload(db, installation, user=context.user)


@router.delete("/mcp/installations/{installation_id}", status_code=204)
def delete_mcp_installation(
    installation_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    installation = uninstall(db, user=context.user, installation_id=installation_id)
    record_audit(
        db,
        action="mcp_uninstalled",
        target_type="mcp_installation",
        target_id=installation.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return Response(status_code=204)


@router.put("/mcp/installations/{installation_id}/secrets/{secret_name}")
def put_mcp_secret_binding(
    installation_id: str,
    secret_name: str,
    payload: McpSecretBindingInput,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    binding = bind_secret_reference(
        db,
        user=context.user,
        installation_id=installation_id,
        secret_name=secret_name,
        secret_ref=payload.secret_ref,
    )
    record_audit(
        db,
        action="mcp_secret_binding_changed",
        target_type="mcp_secret_binding",
        target_id=binding.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"installation_id": installation_id, "secret_name": secret_name},
    )
    db.commit()
    installation = db.get(McpInstallation, binding.installation_id)
    assert installation is not None
    return installation_payload(db, installation, user=context.user)


@router.delete(
    "/mcp/installations/{installation_id}/secrets/{secret_name}", status_code=204
)
def delete_mcp_secret_binding(
    installation_id: str,
    secret_name: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    unbind_secret_reference(
        db,
        user=context.user,
        installation_id=installation_id,
        secret_name=secret_name,
    )
    record_audit(
        db,
        action="mcp_secret_binding_removed",
        target_type="mcp_installation",
        target_id=installation_id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"secret_name": secret_name},
    )
    db.commit()
    return Response(status_code=204)
