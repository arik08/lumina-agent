from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..models import Organization, Project, User, utc_now


InstructionScope = Literal["organization", "agent", "project", "personal"]
MAX_INSTRUCTION_CHARS = 40_000
DEFAULT_AGENT_INSTRUCTIONS = (
    "Follow the current Project scope, preserve source facts, clearly distinguish "
    "assumptions, and never weaken organization security policy."
)

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_KNOWN_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|client[_ -]?secret|authorization|비밀번호|토큰|api\s*키)\s*[:=]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SAFE_PLACEHOLDER_RE = re.compile(
    r"^(?:<[^>\r\n]{1,80}>|\$\{[A-Z][A-Z0-9_]{1,79}\}|\[REDACTED\])$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class InstructionSnapshot:
    scope: InstructionScope
    scope_id: str
    content: str
    revision: int
    digest: str
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ResolvedInstructionStack:
    layers: tuple[InstructionSnapshot, ...]
    excluded_scopes: tuple[InstructionScope, ...]

    @property
    def prompt_text(self) -> str:
        if not self.layers:
            return ""
        payload = {
            "priority": "earlier layers have higher priority",
            "layers": [
                {
                    "scope": layer.scope,
                    "revision": layer.revision,
                    "digest": layer.digest,
                    "instructions": layer.content,
                }
                for layer in self.layers
            ],
        }
        return (
            "Stored instruction hierarchy. System security policy remains higher "
            "priority than every layer below. Lower-priority instructions must not "
            "override earlier layers.\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )


def instruction_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalize_instruction_content(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    if len(normalized) > MAX_INSTRUCTION_CHARS:
        raise ApiProblem(
            422,
            "instruction_too_large",
            f"지침은 {MAX_INSTRUCTION_CHARS:,}자 이하로 입력해 주세요.",
        )
    _reject_secret_material(normalized)
    return normalized.strip()


def _reject_secret_material(content: str) -> None:
    if (
        _PRIVATE_KEY_RE.search(content)
        or _BEARER_RE.search(content)
        or _KNOWN_TOKEN_RE.search(content)
    ):
        raise _secret_problem()
    for match in _SECRET_ASSIGNMENT_RE.finditer(content):
        if not _SAFE_PLACEHOLDER_RE.fullmatch(match.group(1).strip()):
            raise _secret_problem()


def _secret_problem() -> ApiProblem:
    return ApiProblem(
        422,
        "instruction_secret_rejected",
        "지침에는 비밀번호, API Key, Token 또는 Private Key 원문을 저장할 수 없습니다.",
    )


def organization_instruction_snapshot(
    organization: Organization,
) -> InstructionSnapshot:
    return InstructionSnapshot(
        scope="organization",
        scope_id=organization.id,
        content=organization.policy_instructions,
        revision=organization.policy_revision,
        digest=organization.policy_digest,
        updated_at=organization.updated_at,
    )


def project_instruction_snapshot(project: Project) -> InstructionSnapshot:
    return InstructionSnapshot(
        scope="project",
        scope_id=project.id,
        content=project.instructions,
        revision=project.instruction_revision,
        digest=project.instruction_digest,
        updated_at=project.updated_at,
    )


def personal_instruction_snapshot(user: User) -> InstructionSnapshot:
    return InstructionSnapshot(
        scope="personal",
        scope_id=user.id,
        content=user.personal_instructions,
        revision=user.personal_instruction_revision,
        digest=user.personal_instruction_digest,
        updated_at=user.updated_at,
    )


def resolve_instruction_stack(
    *,
    organization: InstructionSnapshot,
    project: InstructionSnapshot,
    personal: InstructionSnapshot,
    project_type: str,
    agent_default: str,
) -> ResolvedInstructionStack:
    layers: list[InstructionSnapshot] = []
    if organization.content:
        layers.append(organization)
    normalized_agent = agent_default.strip()
    if normalized_agent:
        layers.append(
            InstructionSnapshot(
                scope="agent",
                scope_id="lumina-default",
                content=normalized_agent,
                revision=1,
                digest=instruction_digest(normalized_agent),
                updated_at=None,
            )
        )
    if project.content:
        layers.append(project)
    excluded: tuple[InstructionScope, ...] = ()
    if project_type == "personal":
        if personal.content:
            layers.append(personal)
    else:
        excluded = ("personal",)
    return ResolvedInstructionStack(tuple(layers), excluded)


def resolve_instruction_stack_from_models(
    *,
    organization: Organization,
    project: Project,
    user: User,
    agent_default: str,
) -> ResolvedInstructionStack:
    if (
        organization.id != project.organization_id
        or user.organization_id != organization.id
    ):
        raise ValueError(
            "instruction hierarchy scopes do not belong to one organization"
        )
    return resolve_instruction_stack(
        organization=organization_instruction_snapshot(organization),
        project=project_instruction_snapshot(project),
        personal=personal_instruction_snapshot(user),
        project_type=project.project_type,
        agent_default=agent_default,
    )


def update_organization_instructions(
    db: Session,
    organization: Organization,
    *,
    content: str,
    expected_revision: int,
    expected_digest: str,
) -> tuple[Organization, bool]:
    _check_precondition(
        organization.policy_revision,
        organization.policy_digest,
        expected_revision,
        expected_digest,
    )
    normalized = normalize_instruction_content(content)
    if normalized == organization.policy_instructions:
        return organization, False
    revision_contents = dict(organization.policy_revision_contents or {})
    revision_contents.setdefault(
        str(organization.policy_revision), organization.policy_instructions
    )
    revision_contents[str(expected_revision + 1)] = normalized
    result = db.execute(
        update(Organization)
        .where(
            Organization.id == organization.id,
            Organization.policy_revision == expected_revision,
            Organization.policy_digest == expected_digest,
        )
        .values(
            policy_instructions=normalized,
            policy_revision=expected_revision + 1,
            policy_digest=instruction_digest(normalized),
            policy_revision_contents=revision_contents,
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    _finish_update(db, organization, getattr(result, "rowcount", 0))
    return organization, True


def update_project_instructions(
    db: Session,
    project: Project,
    *,
    content: str,
    expected_revision: int,
    expected_digest: str,
) -> tuple[Project, bool]:
    _check_precondition(
        project.instruction_revision,
        project.instruction_digest,
        expected_revision,
        expected_digest,
    )
    normalized = normalize_instruction_content(content)
    if normalized == project.instructions:
        return project, False
    result = db.execute(
        update(Project)
        .where(
            Project.id == project.id,
            Project.instruction_revision == expected_revision,
            Project.instruction_digest == expected_digest,
        )
        .values(
            instructions=normalized,
            instruction_revision=expected_revision + 1,
            instruction_digest=instruction_digest(normalized),
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    _finish_update(db, project, getattr(result, "rowcount", 0))
    return project, True


def update_personal_instructions(
    db: Session,
    user: User,
    *,
    content: str,
    expected_revision: int,
    expected_digest: str,
) -> tuple[User, bool]:
    _check_precondition(
        user.personal_instruction_revision,
        user.personal_instruction_digest,
        expected_revision,
        expected_digest,
    )
    normalized = normalize_instruction_content(content)
    if normalized == user.personal_instructions:
        return user, False
    result = db.execute(
        update(User)
        .where(
            User.id == user.id,
            User.personal_instruction_revision == expected_revision,
            User.personal_instruction_digest == expected_digest,
        )
        .values(
            personal_instructions=normalized,
            personal_instruction_revision=expected_revision + 1,
            personal_instruction_digest=instruction_digest(normalized),
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    _finish_update(db, user, getattr(result, "rowcount", 0))
    return user, True


def _check_precondition(
    current_revision: int,
    current_digest: str,
    expected_revision: int,
    expected_digest: str,
) -> None:
    if current_revision != expected_revision or current_digest != expected_digest:
        raise _instruction_conflict(current_revision, current_digest)


def _finish_update(
    db: Session, target: Organization | Project | User, rowcount: int
) -> None:
    db.expire(target)
    db.refresh(target)
    if rowcount != 1:
        if isinstance(target, Organization):
            raise _instruction_conflict(target.policy_revision, target.policy_digest)
        if isinstance(target, Project):
            raise _instruction_conflict(
                target.instruction_revision, target.instruction_digest
            )
        raise _instruction_conflict(
            target.personal_instruction_revision,
            target.personal_instruction_digest,
        )


def _instruction_conflict(current_revision: int, current_digest: str) -> ApiProblem:
    return ApiProblem(
        409,
        "instruction_conflict",
        "지침이 다른 작업에서 변경되었습니다. 최신 내용을 다시 불러와 주세요.",
        details={"currentRevision": current_revision, "currentDigest": current_digest},
    )


def instruction_payload(
    snapshot: InstructionSnapshot,
    *,
    editable: bool,
    applies_to_shared_projects: bool,
) -> dict[str, object]:
    return {
        "scope": snapshot.scope,
        "scopeId": snapshot.scope_id,
        "content": snapshot.content,
        "revision": snapshot.revision,
        "digest": snapshot.digest,
        "editable": editable,
        "appliesToSharedProjects": applies_to_shared_projects,
        "updatedAt": snapshot.updated_at,
    }


__all__ = [
    "DEFAULT_AGENT_INSTRUCTIONS",
    "InstructionSnapshot",
    "ResolvedInstructionStack",
    "instruction_digest",
    "instruction_payload",
    "normalize_instruction_content",
    "organization_instruction_snapshot",
    "personal_instruction_snapshot",
    "project_instruction_snapshot",
    "resolve_instruction_stack",
    "resolve_instruction_stack_from_models",
    "update_organization_instructions",
    "update_personal_instructions",
    "update_project_instructions",
]
