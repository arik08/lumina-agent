from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..api.schemas import ApiModel


class SkillPackage(ApiModel):
    files: dict[str, str] = Field(min_length=1)


class ExtensionCreate(ApiModel):
    kind: Literal["skill"] = "skill"
    name: str = Field(min_length=1, max_length=240)
    slug: str | None = Field(default=None, min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    project_id: str | None = None
    package: SkillPackage
    source_conversation_id: str | None = None


class ExtensionPatch(ApiModel):
    name: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    tags: list[str] | None = Field(default=None, max_length=8)


class DraftUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    expected_digest: str = Field(min_length=64, max_length=64)
    package: SkillPackage
    change_summary: str = Field(default="", max_length=500)


class DraftActivation(ApiModel):
    project_id: str | None = None
    enabled: bool = True


class DraftSaveVersion(ApiModel):
    expected_revision: int = Field(ge=1)
    expected_digest: str = Field(min_length=64, max_length=64)
    base_version_id: str | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)


class InstallationCreate(ApiModel):
    version_id: str
    scope_type: Literal["user", "project", "organization"] = "user"
    scope_id: str | None = None
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class InstallationPatch(ApiModel):
    enabled: bool | None = None
    project_ids: list[str] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "InstallationPatch":
        if not self.model_fields_set:
            raise ValueError("enabled or projectIds is required")
        return self


class FolderCreate(ApiModel):
    scope_type: Literal["user", "project", "organization"] = "user"
    scope_id: str | None = None
    parent_folder_id: str | None = None
    name: str = Field(min_length=1, max_length=160)
    sort_order: int = Field(default=0, ge=-1_000_000, le=1_000_000)


class FolderPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    sort_order: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)

    @model_validator(mode="after")
    def require_change(self) -> "FolderPatch":
        if not self.model_fields_set or (self.name is None and self.sort_order is None):
            raise ValueError("name or sortOrder is required")
        return self


class FolderMove(ApiModel):
    parent_folder_id: str | None = None


class SkillFolderMove(ApiModel):
    folder_id: str
    scope_type: Literal["user", "project", "organization"]
    scope_id: str | None = None


class SkillOwnershipCreate(ApiModel):
    user_id: str
    role: Literal["owner", "maintainer"] = "owner"


class PublishVersion(ApiModel):
    visibility: Literal["organization"] = "organization"


class SkillVersionRollback(ApiModel):
    target_version_id: str
    expected_current_version_id: str
    change_summary: str = Field(default="", max_length=500)


class ExtensionQuery(ApiModel):
    kind: Literal["skill"] | None = None
    query: str | None = Field(default=None, max_length=200)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None
