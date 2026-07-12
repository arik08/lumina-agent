from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ToolApproval


_READ_ACTIONS = frozenset(
    {
        "fetch",
        "find",
        "get",
        "inspect",
        "list",
        "lookup",
        "query",
        "read",
        "search",
        "show",
        "view",
    }
)
_DESTRUCTIVE_ACTIONS = frozenset(
    {"delete", "destroy", "drop", "erase", "purge", "remove", "revoke"}
)
_EXTERNAL_WRITE_ACTIONS = frozenset(
    {
        "approve",
        "buy",
        "command",
        "create",
        "execute",
        "install",
        "invite",
        "modify",
        "pay",
        "post",
        "publish",
        "purchase",
        "send",
        "submit",
        "transfer",
        "uninstall",
        "update",
        "upload",
        "write",
    }
)
_SENSITIVE_ARGUMENT_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authentication",
        "authorization",
        "client_secret",
        "cookie",
        "credential",
        "csrf_token",
        "passphrase",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
        "token",
    }
)


@dataclass(frozen=True, slots=True)
class ToolRisk:
    effect: str
    risk_level: str
    approval_required: bool


def classify_tool_risk(
    tool_name: str,
    *,
    approval_mode: str,
    mcp_original_name: str | None = None,
) -> ToolRisk:
    if tool_name in {
        "web_search",
        "web_fetch",
        "glob",
        "grep",
        "read_file",
        "list_dir",
    }:
        return ToolRisk("read_only", "low", False)
    if tool_name in {"create_report", "generate_image", "write_file"}:
        return ToolRisk("workspace_write", "low", approval_mode == "confirm_all")
    candidate = mcp_original_name or tool_name
    word_source = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", candidate)
    words = set(filter(None, re.split(r"[^a-z0-9]+", word_source.casefold())))
    if words & _DESTRUCTIVE_ACTIONS:
        risk = ToolRisk("destructive", "high", True)
    elif words & _EXTERNAL_WRITE_ACTIONS:
        risk = ToolRisk("external_write", "high", True)
    elif words & _READ_ACTIONS:
        risk = ToolRisk("external_read", "low", False)
    else:
        risk = ToolRisk("external_write", "high", True)
    if approval_mode == "yolo":
        return ToolRisk(risk.effect, risk.risk_level, False)
    if approval_mode == "confirm_all" and risk.effect != "read_only":
        return ToolRisk(risk.effect, risk.risk_level, True)
    return risk


def normalized_tool_arguments(raw: Any) -> tuple[dict[str, Any], str, str]:
    try:
        parsed = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    canonical = json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return parsed, canonical, digest


def has_sensitive_tool_arguments(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if _sensitive_argument_key(str(key)):
                return True
            if has_sensitive_tool_arguments(item):
                return True
    elif isinstance(value, list):
        return any(has_sensitive_tool_arguments(item) for item in value)
    return False


def safe_argument_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    safe_fields: list[str] = []
    sensitive_count = 0
    for key in sorted(str(item) for item in arguments)[:64]:
        if _sensitive_argument_key(key):
            sensitive_count += 1
        else:
            safe_fields.append(key[:120])
    return {
        "argumentCount": len(arguments),
        "argumentFields": safe_fields,
        "sensitiveFieldCount": sensitive_count,
    }


def _sensitive_argument_key(key: str) -> bool:
    camel_spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key.strip())
    normalized = re.sub(r"[^a-z0-9]+", "_", camel_spaced.casefold()).strip("_")
    if normalized in _SENSITIVE_ARGUMENT_KEYS:
        return True
    parts = tuple(filter(None, normalized.split("_")))
    return bool(
        parts
        and parts[-1] in {"credential", "password", "passphrase", "secret", "token"}
    )


def approval_payload(approval: ToolApproval) -> dict[str, Any]:
    return {
        "id": approval.id,
        "runId": approval.run_id,
        "toolCallId": approval.tool_call_id,
        "toolName": approval.tool_name,
        "effect": approval.effect,
        "riskLevel": approval.risk_level,
        "argumentDigest": approval.argument_digest,
        "summary": approval.summary_json,
        "status": approval.status,
        "requestedAt": approval.requested_at,
        "resolvedAt": approval.resolved_at,
    }


def pending_approval_payloads(db: Session, run_id: str) -> list[dict[str, Any]]:
    return [
        approval_payload(item)
        for item in db.scalars(
            select(ToolApproval)
            .where(ToolApproval.run_id == run_id, ToolApproval.status == "pending")
            .order_by(ToolApproval.requested_at, ToolApproval.id)
        )
    ]


__all__ = [
    "ToolRisk",
    "approval_payload",
    "classify_tool_risk",
    "has_sensitive_tool_arguments",
    "normalized_tool_arguments",
    "pending_approval_payloads",
    "safe_argument_summary",
]
