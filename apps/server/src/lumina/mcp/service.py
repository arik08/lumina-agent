from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..authorization import require_admin, require_project
from ..models import (
    Extension,
    ExtensionVersion,
    McpConfigurationRevision,
    McpDefinition,
    McpInstallation,
    McpSecretBinding,
    User,
    utc_now,
)
from .policy import APPROVABLE_PRIVATE_NETWORKS, SECRET_NAME_PATTERN


ALLOWED_STDIO_EXECUTABLES = frozenset(
    {"bun", "deno", "node", "npx", "python", "python3", "uvx"}
)
ALLOWED_SECRET_HEADER_NAMES = {
    "authorization": "Authorization",
    "x-api-key": "X-API-Key",
    "x-auth-token": "X-Auth-Token",
    "x-mcp-token": "X-MCP-Token",
}
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_SECRET_REF_RE = re.compile(r"^(?:env|secret|vault)://[A-Za-z0-9_./:@-]{1,470}$")
_SECRET_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_INLINE_SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|authorization|password|secret|token)\s*=(?!\s*\$\{)"
)
_SECRET_LITERAL_RE = re.compile(
    r"(?i)(?:\bbearer\s+|\bsk-[a-z0-9_-]{12,}|\bghp_[a-z0-9]{12,}|"
    r"\bgithub_pat_[a-z0-9_]{12,}|\bxox[baprs]-[a-z0-9-]{12,}|"
    r"\beyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,})"
)


def create_definition(
    db: Session,
    *,
    user: User,
    name: str,
    slug: str | None,
    description: str,
    configuration: dict[str, Any],
) -> tuple[McpDefinition, McpConfigurationRevision]:
    require_admin(user)
    clean_name = " ".join(name.split())
    if not clean_name:
        raise ApiProblem(422, "mcp_name_required", "MCP 이름이 필요합니다.")
    clean_slug = normalize_slug(slug or clean_name)
    existing = db.scalar(
        select(McpDefinition.id).where(
            McpDefinition.organization_id == user.organization_id,
            McpDefinition.slug == clean_slug,
        )
    )
    if existing is not None:
        raise ApiProblem(409, "mcp_slug_conflict", "같은 이름의 MCP 정의가 있습니다.")
    definition = McpDefinition(
        organization_id=user.organization_id,
        slug=clean_slug,
        name=clean_name,
        description=description.strip(),
        status="draft",
        created_by_user_id=user.id,
    )
    db.add(definition)
    db.flush()
    revision = _create_revision(
        db,
        user=user,
        definition=definition,
        configuration=configuration,
        revision_number=1,
    )
    return definition, revision


def add_configuration_revision(
    db: Session,
    *,
    user: User,
    definition_id: str,
    configuration: dict[str, Any],
) -> McpConfigurationRevision:
    definition = require_admin_definition(db, user, definition_id)
    if definition.status == "revoked":
        raise ApiProblem(
            409, "mcp_revoked", "폐기된 MCP 정의에는 revision을 추가할 수 없습니다."
        )
    next_number = (
        db.scalar(
            select(func.max(McpConfigurationRevision.revision_number)).where(
                McpConfigurationRevision.definition_id == definition.id
            )
        )
        or 0
    ) + 1
    return _create_revision(
        db,
        user=user,
        definition=definition,
        configuration=configuration,
        revision_number=next_number,
    )


def _create_revision(
    db: Session,
    *,
    user: User,
    definition: McpDefinition,
    configuration: dict[str, Any],
    revision_number: int,
) -> McpConfigurationRevision:
    normalized, digest = validate_configuration(configuration)
    duplicate = db.scalar(
        select(McpConfigurationRevision).where(
            McpConfigurationRevision.definition_id == definition.id,
            McpConfigurationRevision.config_digest == digest,
        )
    )
    if duplicate is not None:
        raise ApiProblem(
            409,
            "mcp_configuration_unchanged",
            "동일한 MCP configuration revision이 이미 있습니다.",
        )
    revision = McpConfigurationRevision(
        definition_id=definition.id,
        revision_number=revision_number,
        transport=normalized["transport"],
        command_json=normalized["command"],
        url_template=normalized["url_template"],
        allowed_hosts_json=normalized["allowed_hosts"],
        allowed_ip_ranges_json=normalized["allowed_ip_ranges"],
        header_templates_json=normalized["header_templates"],
        tool_schemas_json=normalized["tools"],
        required_secret_names_json=normalized["required_secret_names"],
        timeout_seconds=normalized["timeout_seconds"],
        config_digest=digest,
        validation_status="validated",
        health_status="not_connected",
        schema_status="declared",
        approval_status="draft",
        validation_summary=(
            "정적 transport, endpoint, Tool schema와 Secret slot 검증을 통과했습니다. "
            "외부 연결 health check는 실행 환경 승인 후 수행합니다."
        ),
        created_by_user_id=user.id,
        validated_at=utc_now(),
    )
    db.add(revision)
    db.flush()
    return revision


def validate_configuration(
    configuration: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    transport = str(configuration.get("transport", ""))
    command = [str(item) for item in configuration.get("command", [])]
    url_template_value = configuration.get("url_template")
    url_template = str(url_template_value).strip() if url_template_value else None
    allowed_hosts = _normalize_hosts(configuration.get("allowed_hosts", []))
    allowed_ip_ranges = _normalize_allowed_ip_ranges(
        configuration.get("allowed_ip_ranges", [])
    )
    header_templates = _normalize_header_templates(
        configuration.get("header_templates", {})
    )
    tools = _normalize_tools(configuration.get("tools", []))
    required_secret_names = _normalize_secret_names(
        configuration.get("required_secret_names", [])
    )
    timeout_seconds = int(configuration.get("timeout_seconds", 30))
    if not 1 <= timeout_seconds <= 300:
        raise ApiProblem(
            422, "mcp_timeout_invalid", "MCP timeout은 1초에서 300초 사이여야 합니다."
        )

    if transport == "stdio":
        _validate_stdio_command(command)
        if (
            url_template is not None
            or allowed_hosts
            or allowed_ip_ranges
            or header_templates
        ):
            raise ApiProblem(
                422,
                "mcp_transport_invalid",
                "stdio transport에는 URL, header 또는 host allowlist를 지정할 수 없습니다.",
            )
    elif transport == "streamable_http":
        if command:
            raise ApiProblem(
                422,
                "mcp_transport_invalid",
                "streamable_http transport에는 command를 지정할 수 없습니다.",
            )
        _validate_http_target(url_template, allowed_hosts, allowed_ip_ranges)
    else:
        raise ApiProblem(
            422, "mcp_transport_invalid", "지원하지 않는 MCP transport입니다."
        )

    joined_targets = "\n".join([*command, url_template or ""])
    if _SECRET_PLACEHOLDER_RE.search(joined_targets):
        raise ApiProblem(
            422,
            "mcp_secret_in_target_forbidden",
            "MCP Secret은 URL, query 또는 process argument에 넣을 수 없습니다.",
        )
    placeholders = {
        placeholder
        for template in header_templates.values()
        for placeholder in _SECRET_PLACEHOLDER_RE.findall(template)
    }
    undeclared = placeholders.difference(required_secret_names)
    if undeclared:
        raise ApiProblem(
            422,
            "mcp_secret_slot_invalid",
            "선언되지 않은 MCP Secret slot이 있습니다.",
            details={"secretNames": sorted(undeclared)},
        )
    unused = set(required_secret_names).difference(placeholders)
    if transport == "streamable_http" and unused:
        raise ApiProblem(
            422,
            "mcp_secret_slot_invalid",
            "HTTP MCP Secret slot은 승인된 header template에서만 사용할 수 있습니다.",
            details={"secretNames": sorted(unused)},
        )
    if _INLINE_SECRET_RE.search(joined_targets) or _SECRET_LITERAL_RE.search(
        joined_targets
    ):
        raise ApiProblem(
            422,
            "mcp_inline_secret_forbidden",
            "MCP configuration에 credential 값을 직접 넣을 수 없습니다.",
        )

    normalized = {
        "transport": transport,
        "command": command,
        "url_template": url_template,
        "allowed_hosts": allowed_hosts,
        "allowed_ip_ranges": allowed_ip_ranges,
        "header_templates": header_templates,
        "tools": tools,
        "required_secret_names": required_secret_names,
        "timeout_seconds": timeout_seconds,
    }
    digest = hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return normalized, digest


def _validate_stdio_command(command: list[str]) -> None:
    if not command:
        raise ApiProblem(422, "mcp_command_required", "stdio command가 필요합니다.")
    executable = command[0].casefold()
    if "/" in executable or "\\" in executable:
        raise ApiProblem(
            422,
            "mcp_command_not_allowed",
            "MCP executable은 승인된 command 이름으로 지정해야 합니다.",
        )
    if executable.endswith(".exe"):
        executable = executable[:-4]
    if executable not in ALLOWED_STDIO_EXECUTABLES:
        raise ApiProblem(
            422,
            "mcp_command_not_allowed",
            "승인되지 않은 MCP executable입니다.",
            details={"allowedCommands": sorted(ALLOWED_STDIO_EXECUTABLES)},
        )
    for part in command:
        if (
            not part
            or len(part) > 500
            or "\x00" in part
            or "\n" in part
            or "\r" in part
        ):
            raise ApiProblem(
                422, "mcp_command_invalid", "MCP command 인자가 올바르지 않습니다."
            )


def _validate_http_target(
    url_template: str | None,
    allowed_hosts: list[str],
    allowed_ip_ranges: list[str],
) -> None:
    if url_template is None:
        raise ApiProblem(422, "mcp_url_required", "MCP HTTPS URL이 필요합니다.")
    parsed = urlsplit(url_template)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ApiProblem(
            422, "mcp_url_invalid", "MCP HTTPS URL이 올바르지 않습니다."
        ) from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ord(character) < 32 for character in url_template)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ApiProblem(
            422,
            "mcp_url_invalid",
            "MCP URL은 credential, query와 fragment가 없는 HTTPS 주소여야 합니다.",
        )
    host = parsed.hostname.casefold().rstrip(".")
    if host not in allowed_hosts:
        raise ApiProblem(
            422,
            "mcp_host_not_allowed",
            "MCP URL host가 명시적 allowlist에 없습니다.",
        )
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ApiProblem(
            422, "mcp_host_not_allowed", "로컬 MCP URL은 등록할 수 없습니다."
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not _address_allowed(address, allowed_ip_ranges):
        raise ApiProblem(
            422,
            "mcp_host_not_allowed",
            "명시적으로 승인되지 않은 private, loopback 또는 reserved IP입니다.",
        )


def _normalize_hosts(values: Any) -> list[str]:
    if not isinstance(values, list):
        raise ApiProblem(422, "mcp_host_invalid", "host allowlist가 올바르지 않습니다.")
    hosts: list[str] = []
    for value in values:
        host = str(value).strip().casefold().rstrip(".")
        if not host or "*" in host or not _HOST_RE.fullmatch(host):
            raise ApiProblem(
                422,
                "mcp_host_invalid",
                "MCP host allowlist에는 정확한 hostname만 사용할 수 있습니다.",
            )
        if host not in hosts:
            hosts.append(host)
    return sorted(hosts)


def _normalize_allowed_ip_ranges(values: Any) -> list[str]:
    if not isinstance(values, list):
        raise ApiProblem(
            422,
            "mcp_ip_range_invalid",
            "MCP private IP allowlist가 올바르지 않습니다.",
        )
    ranges: list[str] = []
    for value in values:
        try:
            network = ipaddress.ip_network(str(value).strip(), strict=True)
        except ValueError as exc:
            raise ApiProblem(
                422,
                "mcp_ip_range_invalid",
                "MCP private IP allowlist에는 정확한 CIDR만 사용할 수 있습니다.",
            ) from exc
        if not _network_is_approvable(network) or _network_is_forbidden(network):
            raise ApiProblem(
                422,
                "mcp_ip_range_invalid",
                "private 또는 loopback CIDR만 명시적으로 승인할 수 있습니다.",
            )
        normalized = str(network)
        if normalized not in ranges:
            ranges.append(normalized)
    return sorted(ranges)


def _address_allowed(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allowed_ip_ranges: list[str],
) -> bool:
    if (
        address.is_unspecified
        or address.is_link_local
        or address.is_multicast
        or (address.is_reserved and not address.is_loopback)
    ):
        return False
    if address.is_global:
        return True
    if not (address.is_private or address.is_loopback):
        return False
    return any(
        address.version == network.version and address in network
        for network in (
            ipaddress.ip_network(value, strict=True) for value in allowed_ip_ranges
        )
    )


def _network_is_forbidden(
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> bool:
    forbidden = (
        (
            ipaddress.ip_network("0.0.0.0/8"),
            ipaddress.ip_network("169.254.0.0/16"),
            ipaddress.ip_network("224.0.0.0/4"),
        )
        if network.version == 4
        else (
            ipaddress.ip_network("::/128"),
            ipaddress.ip_network("fe80::/10"),
            ipaddress.ip_network("ff00::/8"),
        )
    )
    return any(network.overlaps(blocked) for blocked in forbidden)


def _network_is_approvable(
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> bool:
    if isinstance(network, ipaddress.IPv4Network):
        return any(
            isinstance(parent, ipaddress.IPv4Network) and network.subnet_of(parent)
            for parent in APPROVABLE_PRIVATE_NETWORKS
        )
    return any(
        isinstance(parent, ipaddress.IPv6Network) and network.subnet_of(parent)
        for parent in APPROVABLE_PRIVATE_NETWORKS
    )


def _normalize_header_templates(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        raise ApiProblem(
            422,
            "mcp_header_template_invalid",
            "MCP header template가 올바르지 않습니다.",
        )
    normalized: dict[str, str] = {}
    for raw_name, raw_template in values.items():
        name = str(raw_name).strip().casefold()
        canonical_name = ALLOWED_SECRET_HEADER_NAMES.get(name)
        template = str(raw_template)
        if canonical_name is None:
            raise ApiProblem(
                422,
                "mcp_header_not_allowed",
                "승인되지 않은 MCP credential header입니다.",
                details={
                    "allowedHeaders": sorted(ALLOWED_SECRET_HEADER_NAMES.values())
                },
            )
        if (
            not template
            or len(template) > 1000
            or "\r" in template
            or "\n" in template
            or "\x00" in template
        ):
            raise ApiProblem(
                422,
                "mcp_header_template_invalid",
                "MCP header template에 허용되지 않은 문자가 있습니다.",
            )
        if canonical_name == "Authorization":
            match = re.fullmatch(r"(?:Bearer )?\$\{([A-Z][A-Z0-9_]*)\}", template)
        else:
            match = re.fullmatch(r"\$\{([A-Z][A-Z0-9_]*)\}", template)
        if match is None:
            raise ApiProblem(
                422,
                "mcp_header_template_invalid",
                "MCP credential header에는 선언된 Secret placeholder 하나만 사용할 수 있습니다.",
            )
        normalized[canonical_name] = template
    return dict(sorted(normalized.items()))


def _normalize_tools(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not values:
        raise ApiProblem(422, "mcp_tools_required", "MCP Tool schema가 필요합니다.")
    tools: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise ApiProblem(
                422, "mcp_tool_invalid", "MCP Tool schema가 올바르지 않습니다."
            )
        name = str(value.get("name", ""))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", name):
            raise ApiProblem(
                422, "mcp_tool_invalid", "MCP Tool 이름이 올바르지 않습니다."
            )
        if name in seen:
            raise ApiProblem(422, "mcp_tool_duplicate", "MCP Tool 이름이 중복됩니다.")
        input_schema = value.get("input_schema", value.get("inputSchema", {}))
        if (
            not isinstance(input_schema, dict)
            or input_schema.get("type", "object") != "object"
        ):
            raise ApiProblem(
                422,
                "mcp_tool_schema_invalid",
                "MCP Tool input schema의 최상위 type은 object여야 합니다.",
            )
        seen.add(name)
        tools.append(
            {
                "name": name,
                "description": str(value.get("description", ""))[:2000],
                "inputSchema": input_schema,
            }
        )
    return tools


def _normalize_secret_names(values: Any) -> list[str]:
    if not isinstance(values, list):
        raise ApiProblem(
            422, "mcp_secret_slot_invalid", "Secret slot이 올바르지 않습니다."
        )
    names: list[str] = []
    for value in values:
        name = str(value).strip()
        if not SECRET_NAME_PATTERN.fullmatch(name):
            raise ApiProblem(
                422,
                "mcp_secret_slot_invalid",
                "Secret slot은 대문자 영문과 숫자, 밑줄만 사용할 수 있습니다.",
            )
        if name not in names:
            names.append(name)
    return sorted(names)


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        slug = f"mcp-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"
    if not slug or len(slug) > 160 or not _SLUG_RE.fullmatch(slug):
        raise ApiProblem(422, "mcp_slug_invalid", "MCP slug가 올바르지 않습니다.")
    return slug


def require_admin_definition(
    db: Session, user: User, definition_id: str
) -> McpDefinition:
    require_admin(user)
    definition = db.get(McpDefinition, definition_id)
    if definition is None or definition.organization_id != user.organization_id:
        raise ApiProblem(404, "mcp_not_found", "MCP 정의를 찾을 수 없습니다.")
    return definition


def approve_revision(
    db: Session,
    *,
    user: User,
    definition_id: str,
    revision_id: str,
) -> tuple[McpDefinition, McpConfigurationRevision]:
    definition = require_admin_definition(db, user, definition_id)
    if definition.status == "revoked":
        raise ApiProblem(409, "mcp_revoked", "폐기된 MCP 정의는 승인할 수 없습니다.")
    revision = db.get(McpConfigurationRevision, revision_id)
    if revision is None or revision.definition_id != definition.id:
        raise ApiProblem(
            404, "mcp_revision_not_found", "MCP revision을 찾을 수 없습니다."
        )
    if (
        revision.validation_status != "validated"
        or revision.schema_status != "declared"
    ):
        raise ApiProblem(
            409,
            "mcp_validation_required",
            "검증을 통과한 MCP revision만 승인할 수 있습니다.",
        )
    now = utc_now()
    revision.approval_status = "approved"
    revision.approved_by_user_id = user.id
    revision.approved_at = now
    definition.current_revision_id = revision.id
    definition.status = "approved"
    definition.approved_by_user_id = user.id
    definition.approved_at = now
    definition.disabled_at = None
    db.flush()
    return definition, revision


def set_definition_status(
    db: Session,
    *,
    user: User,
    definition_id: str,
    status: str,
) -> McpDefinition:
    definition = require_admin_definition(db, user, definition_id)
    now = utc_now()
    if status == "disabled":
        if definition.status == "revoked":
            raise ApiProblem(
                409, "mcp_revoked", "폐기된 MCP 정의는 변경할 수 없습니다."
            )
        definition.status = "disabled"
        definition.disabled_at = now
    elif status == "revoked":
        definition.status = "revoked"
        definition.revoked_at = now
        definition.disabled_at = now
    else:
        raise ApiProblem(422, "mcp_status_invalid", "지원하지 않는 MCP 상태입니다.")
    db.flush()
    return definition


def list_admin_definitions(db: Session, *, user: User) -> list[McpDefinition]:
    require_admin(user)
    return list(
        db.scalars(
            select(McpDefinition)
            .where(McpDefinition.organization_id == user.organization_id)
            .order_by(McpDefinition.updated_at.desc(), McpDefinition.id)
        )
    )


def list_catalog(db: Session, *, user: User) -> list[McpDefinition]:
    return list(
        db.scalars(
            select(McpDefinition)
            .where(
                McpDefinition.organization_id == user.organization_id,
                McpDefinition.status == "approved",
                McpDefinition.current_revision_id.is_not(None),
            )
            .order_by(McpDefinition.name, McpDefinition.id)
        )
    )


def definition_payload(
    db: Session,
    definition: McpDefinition,
    *,
    include_all_revisions: bool,
    include_configuration: bool,
    skill_wrappers: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    wrappers = (
        skill_wrappers
        if skill_wrappers is not None
        else mcp_skill_wrappers(db, organization_id=definition.organization_id)
    )
    skill_wrapper = wrappers.get(definition.slug)
    statement = select(McpConfigurationRevision).where(
        McpConfigurationRevision.definition_id == definition.id
    )
    if not include_all_revisions:
        statement = statement.where(
            McpConfigurationRevision.id == definition.current_revision_id
        )
    revisions = list(
        db.scalars(statement.order_by(McpConfigurationRevision.revision_number))
    )
    return {
        "id": definition.id,
        "slug": definition.slug,
        "name": definition.name,
        "description": definition.description,
        "status": definition.status,
        "skillWrapper": {
            "wrapped": skill_wrapper is not None,
            "name": skill_wrapper["name"] if skill_wrapper is not None else None,
        },
        "currentRevisionId": definition.current_revision_id,
        "revisions": [
            revision_payload(revision, include_configuration=include_configuration)
            for revision in revisions
        ],
        "approvedAt": definition.approved_at,
        "disabledAt": definition.disabled_at,
        "revokedAt": definition.revoked_at,
        "createdAt": definition.created_at,
        "updatedAt": definition.updated_at,
    }


def revision_payload(
    revision: McpConfigurationRevision, *, include_configuration: bool
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": revision.id,
        "revision": revision.revision_number,
        "transport": revision.transport,
        "digest": revision.config_digest,
        "validationStatus": revision.validation_status,
        "healthStatus": revision.health_status,
        "schemaStatus": revision.schema_status,
        "approvalStatus": revision.approval_status,
        "validationSummary": revision.validation_summary,
        "tools": [
            {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "inputSchema": tool.get("inputSchema", {}),
            }
            for tool in revision.tool_schemas_json
            if isinstance(tool, dict)
        ],
        "requiredSecretNames": revision.required_secret_names_json,
        "timeoutSeconds": revision.timeout_seconds,
        "createdAt": revision.created_at,
        "validatedAt": revision.validated_at,
        "approvedAt": revision.approved_at,
    }
    if include_configuration:
        payload["configuration"] = {
            "transport": revision.transport,
            "command": revision.command_json,
            "urlTemplate": revision.url_template,
            "allowedHosts": revision.allowed_hosts_json,
            "allowedIpRanges": revision.allowed_ip_ranges_json,
            "headerTemplates": revision.header_templates_json,
            "tools": revision.tool_schemas_json,
            "requiredSecretNames": revision.required_secret_names_json,
            "timeoutSeconds": revision.timeout_seconds,
        }
    else:
        payload["target"] = (
            revision.command_json[0]
            if revision.transport == "stdio" and revision.command_json
            else urlsplit(revision.url_template or "").hostname
        )
    return payload


def install_definition(
    db: Session,
    *,
    user: User,
    definition_id: str,
    revision_id: str | None,
    scope_type: str,
    scope_id: str | None,
    enabled: bool,
    tool_allowlist: list[str],
) -> McpInstallation:
    definition = db.get(McpDefinition, definition_id)
    if (
        definition is None
        or definition.organization_id != user.organization_id
        or definition.status != "approved"
        or definition.current_revision_id is None
    ):
        raise ApiProblem(
            404, "mcp_not_available", "설치 가능한 MCP 정의를 찾을 수 없습니다."
        )
    resolved_scope_id = _authorize_installation_scope(
        db,
        user=user,
        scope_type=scope_type,
        scope_id=scope_id,
        write=True,
    )
    selected_revision_id = revision_id or definition.current_revision_id
    revision = db.get(McpConfigurationRevision, selected_revision_id)
    if (
        revision is None
        or revision.definition_id != definition.id
        or revision.approval_status != "approved"
    ):
        raise ApiProblem(
            409, "mcp_revision_not_approved", "승인된 MCP revision이 아닙니다."
        )
    existing = db.scalar(
        select(McpInstallation).where(
            McpInstallation.definition_id == definition.id,
            McpInstallation.scope_type == scope_type,
            McpInstallation.scope_id == resolved_scope_id,
            McpInstallation.removed_at.is_(None),
        )
    )
    if existing is not None:
        raise ApiProblem(
            409, "mcp_already_installed", "이 범위에 MCP가 이미 설치되어 있습니다."
        )
    allowed_tools = [
        str(tool.get("name"))
        for tool in revision.tool_schemas_json
        if isinstance(tool, dict) and tool.get("name")
    ]
    selected_tools = list(dict.fromkeys(tool_allowlist or allowed_tools))
    if not selected_tools or not set(selected_tools).issubset(allowed_tools):
        raise ApiProblem(
            422, "mcp_tool_not_allowed", "MCP 설치 Tool allowlist가 올바르지 않습니다."
        )
    installation = McpInstallation(
        definition_id=definition.id,
        configuration_revision_id=revision.id,
        scope_type=scope_type,
        scope_id=resolved_scope_id,
        enabled=enabled,
        tool_allowlist_json=selected_tools,
        installed_by_user_id=user.id,
    )
    db.add(installation)
    db.flush()
    return installation


def list_installations(
    db: Session, *, user: User, project_id: str | None
) -> list[McpInstallation]:
    filters = [
        (McpInstallation.scope_type == "user") & (McpInstallation.scope_id == user.id)
    ]
    if project_id is not None:
        require_project(db, user, project_id)
        filters.append(
            (McpInstallation.scope_type == "project")
            & (McpInstallation.scope_id == project_id)
        )
    installations = list(
        db.scalars(
            select(McpInstallation)
            .where(McpInstallation.removed_at.is_(None), or_(*filters))
            .order_by(McpInstallation.installed_at.desc(), McpInstallation.id)
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


def require_installation(
    db: Session,
    *,
    user: User,
    installation_id: str,
    write: bool,
) -> McpInstallation:
    installation = db.get(McpInstallation, installation_id)
    if installation is None or installation.removed_at is not None:
        raise ApiProblem(
            404, "mcp_installation_not_found", "MCP 설치를 찾을 수 없습니다."
        )
    _authorize_installation_scope(
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
) -> McpInstallation:
    installation = require_installation(
        db, user=user, installation_id=installation_id, write=True
    )
    if enabled is not None:
        installation.enabled = enabled
    if update_project_ids:
        if installation.scope_type != "user":
            raise ApiProblem(
                422,
                "mcp_installation_project_scope_unsupported",
                "사용자 범위 MCP 설치만 프로젝트별로 설정할 수 있습니다.",
            )
        normalized_project_ids = list(dict.fromkeys(project_ids or []))
        for project_id in normalized_project_ids:
            require_project(db, user, project_id)
        installation.project_ids_json = (
            normalized_project_ids if project_ids is not None else None
        )
    db.flush()
    return installation


def uninstall(db: Session, *, user: User, installation_id: str) -> McpInstallation:
    installation = require_installation(
        db, user=user, installation_id=installation_id, write=True
    )
    installation.enabled = False
    installation.removed_at = utc_now()
    for binding in db.scalars(
        select(McpSecretBinding).where(
            McpSecretBinding.installation_id == installation.id
        )
    ):
        db.delete(binding)
    db.flush()
    return installation


def bind_secret_reference(
    db: Session,
    *,
    user: User,
    installation_id: str,
    secret_name: str,
    secret_ref: str,
) -> McpSecretBinding:
    installation = require_installation(
        db, user=user, installation_id=installation_id, write=False
    )
    if installation.scope_type == "user" and installation.scope_id != user.id:
        raise ApiProblem(
            403,
            "mcp_binding_forbidden",
            "자신의 MCP 설치에만 Secret을 연결할 수 있습니다.",
        )
    revision = db.get(McpConfigurationRevision, installation.configuration_revision_id)
    if revision is None or secret_name not in revision.required_secret_names_json:
        raise ApiProblem(
            404, "mcp_secret_slot_not_found", "MCP Secret slot을 찾을 수 없습니다."
        )
    if (
        not _SECRET_REF_RE.fullmatch(secret_ref)
        or "?" in secret_ref
        or "#" in secret_ref
    ):
        raise ApiProblem(
            422,
            "mcp_secret_ref_invalid",
            "Secret Store reference 형식이 올바르지 않습니다.",
        )
    if secret_ref.startswith("env://") and user.role != "admin":
        raise ApiProblem(
            403,
            "mcp_environment_secret_admin_required",
            "Server environment Secret reference는 관리자만 연결할 수 있습니다.",
        )
    binding = db.scalar(
        select(McpSecretBinding).where(
            McpSecretBinding.installation_id == installation.id,
            McpSecretBinding.user_id == user.id,
            McpSecretBinding.secret_name == secret_name,
        )
    )
    if binding is None:
        binding = McpSecretBinding(
            installation_id=installation.id,
            user_id=user.id,
            secret_name=secret_name,
            secret_ref=secret_ref,
        )
        db.add(binding)
    else:
        binding.secret_ref = secret_ref
        binding.updated_at = utc_now()
    db.flush()
    return binding


def unbind_secret_reference(
    db: Session,
    *,
    user: User,
    installation_id: str,
    secret_name: str,
) -> None:
    installation = require_installation(
        db, user=user, installation_id=installation_id, write=False
    )
    if installation.scope_type == "user" and installation.scope_id != user.id:
        raise ApiProblem(
            403, "mcp_binding_forbidden", "자신의 MCP 설치만 변경할 수 있습니다."
        )
    binding = db.scalar(
        select(McpSecretBinding).where(
            McpSecretBinding.installation_id == installation.id,
            McpSecretBinding.user_id == user.id,
            McpSecretBinding.secret_name == secret_name,
        )
    )
    if binding is None:
        raise ApiProblem(
            404, "mcp_secret_binding_not_found", "MCP Secret 연결을 찾을 수 없습니다."
        )
    db.delete(binding)
    db.flush()


def installation_payload(
    db: Session, installation: McpInstallation, *, user: User
) -> dict[str, Any]:
    definition = db.get(McpDefinition, installation.definition_id)
    revision = db.get(McpConfigurationRevision, installation.configuration_revision_id)
    if definition is None or revision is None:
        raise ApiProblem(
            409, "mcp_installation_invalid", "MCP 설치 정보가 손상되었습니다."
        )
    bindings = {
        binding.secret_name: binding.secret_ref
        for binding in db.scalars(
            select(McpSecretBinding).where(
                McpSecretBinding.installation_id == installation.id,
                McpSecretBinding.user_id == user.id,
            )
        )
    }
    secret_resolution_status, secret_slots = _secret_resolution_status(
        revision.required_secret_names_json,
        bindings,
        user=user,
    )
    return {
        "id": installation.id,
        "definitionId": definition.id,
        "name": definition.name,
        "slug": definition.slug,
        "definitionStatus": definition.status,
        "configurationRevisionId": revision.id,
        "configurationRevision": revision.revision_number,
        "configurationDigest": revision.config_digest,
        "healthStatus": revision.health_status,
        "schemaStatus": revision.schema_status,
        "scopeType": installation.scope_type,
        "scopeId": installation.scope_id,
        "enabled": installation.enabled,
        "projectIds": installation.project_ids_json,
        "toolAllowlist": installation.tool_allowlist_json,
        "boundSecrets": secret_slots,
        "secretResolutionStatus": secret_resolution_status,
        "supportedSecretSchemes": ["env"],
        "secretBindingRole": "admin",
        # Installation and Secret configuration are prerequisites, not proof that
        # the MCP process can initialize and return the approved Tool schemas.
        # The explicit runtime probe is the only path that may return ready=True.
        "ready": False,
        "connectionErrorCode": None,
        "installedAt": installation.installed_at,
    }


def resolve_mcp_snapshot(
    db: Session, *, user: User, project_id: str
) -> list[dict[str, Any]]:
    require_project(db, user, project_id)
    wrappers = mcp_skill_wrappers(db, organization_id=user.organization_id)
    rows = list(
        db.execute(
            select(McpInstallation, McpConfigurationRevision, McpDefinition)
            .join(
                McpConfigurationRevision,
                McpConfigurationRevision.id
                == McpInstallation.configuration_revision_id,
            )
            .join(McpDefinition, McpDefinition.id == McpInstallation.definition_id)
            .where(
                McpInstallation.enabled.is_(True),
                McpInstallation.removed_at.is_(None),
                McpDefinition.organization_id == user.organization_id,
                McpDefinition.status == "approved",
                McpConfigurationRevision.approval_status == "approved",
                or_(
                    (McpInstallation.scope_type == "user")
                    & (McpInstallation.scope_id == user.id),
                    (McpInstallation.scope_type == "project")
                    & (McpInstallation.scope_id == project_id),
                ),
            )
        )
    )
    resolved: dict[str, dict[str, Any]] = {}
    priorities: dict[str, int] = {}
    for installation, revision, definition in rows:
        if (
            installation.scope_type == "user"
            and installation.project_ids_json is not None
            and project_id not in installation.project_ids_json
        ):
            continue
        bindings = {
            binding.secret_name: binding.secret_ref
            for binding in db.scalars(
                select(McpSecretBinding).where(
                    McpSecretBinding.installation_id == installation.id,
                    McpSecretBinding.user_id == user.id,
                )
            )
        }
        secret_resolution_status, _secret_slots = _secret_resolution_status(
            revision.required_secret_names_json,
            bindings,
            user=user,
        )
        required = set(revision.required_secret_names_json)
        if secret_resolution_status not in {"ready", "not_required"}:
            continue
        priority = 2 if installation.scope_type == "project" else 1
        if priorities.get(definition.id, 0) >= priority:
            continue
        priorities[definition.id] = priority
        resolved[definition.id] = {
            "definition_id": definition.id,
            "kind": "mcp",
            "slug": definition.slug,
            "name": definition.name,
            "description": definition.description,
            "installation_id": installation.id,
            "configuration_revision_id": revision.id,
            "configuration_revision": revision.revision_number,
            "digest": revision.config_digest,
            "transport": revision.transport,
            "allowed_ip_ranges": list(revision.allowed_ip_ranges_json),
            "tool_allowlist": list(installation.tool_allowlist_json),
            "required_secret_names": list(revision.required_secret_names_json),
            "bound_secret_names": sorted(set(bindings).intersection(required)),
            "secret_resolution_status": secret_resolution_status,
            "health_status": revision.health_status,
            "schema_status": revision.schema_status,
            "scope_type": installation.scope_type,
            "scope_id": installation.scope_id,
            **(
                {"skill_wrapper": wrappers[definition.slug]}
                if definition.slug in wrappers
                else {}
            ),
        }
    return sorted(
        resolved.values(),
        key=lambda item: (str(item["name"]), str(item["definition_id"])),
    )


def mcp_skill_wrappers(
    db: Session, *, organization_id: str
) -> dict[str, dict[str, Any]]:
    wrappers: dict[str, dict[str, Any]] = {}
    for extension, version in db.execute(
        select(Extension, ExtensionVersion)
        .join(
            ExtensionVersion,
            ExtensionVersion.id == Extension.latest_published_version_id,
        )
        .where(
            Extension.organization_id == organization_id,
            Extension.kind == "mcp",
            Extension.archived_at.is_(None),
            ExtensionVersion.status == "published",
            ExtensionVersion.revoked_at.is_(None),
        )
    ):
        mcp_slug = str(version.manifest_json.get("mcpSlug", "")).strip()
        if not mcp_slug:
            continue
        instructions = next(
            (
                content
                for path, content in version.package_json.items()
                if path.casefold() == "skill.md"
            ),
            "",
        ).strip()
        if not instructions:
            continue
        wrappers[mcp_slug] = {
            "extension_id": extension.id,
            "name": extension.name,
            "digest": version.package_digest,
            "instructions": instructions,
        }
    return wrappers


def _secret_resolution_status(
    required_secret_names: list[str],
    bindings: dict[str, str],
    *,
    user: User,
) -> tuple[str, list[dict[str, Any]]]:
    if not required_secret_names:
        return "not_required", []
    statuses: list[str] = []
    slots: list[dict[str, Any]] = []
    can_bind = user.role == "admin"
    for name in required_secret_names:
        secret_ref = bindings.get(name)
        if not secret_ref:
            status = "binding_required" if can_bind else "administrator_required"
            bound = False
            resolvable = False
        elif secret_ref.startswith("env://"):
            status = "ready"
            bound = True
            resolvable = True
        else:
            status = "resolver_unavailable"
            bound = True
            resolvable = False
        statuses.append(status)
        slots.append(
            {
                "name": name,
                "bound": bound,
                "resolvable": resolvable,
                "resolverStatus": status,
                "canBind": can_bind,
            }
        )
    for status in (
        "resolver_unavailable",
        "administrator_required",
        "binding_required",
    ):
        if status in statuses:
            return status, slots
    return "ready", slots


def _authorize_installation_scope(
    db: Session,
    *,
    user: User,
    scope_type: str,
    scope_id: str | None,
    write: bool,
) -> str:
    if scope_type == "user":
        resolved = scope_id or user.id
        if resolved != user.id:
            raise ApiProblem(
                403, "mcp_scope_forbidden", "다른 사용자의 MCP 범위입니다."
            )
        return resolved
    if scope_type == "project":
        if scope_id is None:
            raise ApiProblem(422, "project_id_required", "Project ID가 필요합니다.")
        require_project(db, user, scope_id, write=write)
        return scope_id
    raise ApiProblem(
        422, "mcp_scope_invalid", "MCP는 user 또는 project 범위에 설치해야 합니다."
    )


__all__ = [
    "add_configuration_revision",
    "approve_revision",
    "bind_secret_reference",
    "create_definition",
    "definition_payload",
    "install_definition",
    "installation_payload",
    "list_admin_definitions",
    "list_catalog",
    "list_installations",
    "resolve_mcp_snapshot",
    "set_definition_status",
    "update_installation",
    "unbind_secret_reference",
    "uninstall",
    "validate_configuration",
]
