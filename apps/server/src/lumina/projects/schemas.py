from __future__ import annotations

from typing import Literal, get_args

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from ..api.schemas import ApiModel


ProjectRole = Literal["owner", "admin", "member", "viewer"]
ProjectMembershipStatus = Literal["active", "revoked"]
PROJECT_ROLES = frozenset(get_args(ProjectRole))
MEMBERSHIP_STATUSES = frozenset(get_args(ProjectMembershipStatus))


class ProjectMembershipCreate(ApiModel):
    user_id: str | None = Field(default=None, max_length=36)
    login_id: str | None = Field(default=None, max_length=380)
    role: ProjectRole = "member"

    @model_validator(mode="after")
    def require_one_identity(self) -> "ProjectMembershipCreate":
        if (self.user_id is None) == (self.login_id is None):
            raise PydanticCustomError(
                "project_membership_identity",
                "exactly one of userId or loginId is required",
            )
        return self


class ProjectMembershipPatch(ApiModel):
    role: ProjectRole | None = None
    status: ProjectMembershipStatus | None = None
    expected_role: ProjectRole
    expected_status: ProjectMembershipStatus

    @model_validator(mode="after")
    def require_change(self) -> "ProjectMembershipPatch":
        if self.role is None and self.status is None:
            raise PydanticCustomError(
                "project_membership_change", "role or status is required"
            )
        return self
