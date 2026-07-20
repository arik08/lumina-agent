from __future__ import annotations

from pydantic import Field, model_validator

from ..api.schemas import ApiModel


class KnowledgeSpaceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=240)
    purpose: str = Field(default="", max_length=10_000)
    visibility: str = Field(default="private", pattern=r"^(private|organization)$")


class KnowledgeSpaceUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    purpose: str | None = Field(default=None, max_length=10_000)
    project_ids: list[str] | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_change(self) -> "KnowledgeSpaceUpdate":
        if self.name is None and self.purpose is None and self.project_ids is None:
            raise ValueError("at least one field is required")
        if self.project_ids is not None and len(set(self.project_ids)) != len(self.project_ids):
            raise ValueError("projectIds must not contain duplicates")
        return self


class KnowledgeDocumentListQuery(ApiModel):
    space_id: str | None = None
    project_id: str | None = None
    query: str = Field(default="", max_length=500)


class KnowledgeBatchTagRequest(ApiModel):
    space_id: str
    provider_id: str = Field(min_length=1, max_length=120)
    model_key: str = Field(min_length=1, max_length=240)


class KnowledgeTagCreate(ApiModel):
    space_id: str
    namespace: str = Field(default="topic", pattern=r"^[a-z][a-z0-9_-]{0,79}$")
    canonical_name: str = Field(min_length=1, max_length=160)
    definition: str = Field(default="", max_length=1_000)
    scope_note: str = Field(default="", max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=8)
    parent_tag_id: str | None = None


class KnowledgeTagUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    namespace: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_-]{0,79}$"
    )
    canonical_name: str | None = Field(default=None, min_length=1, max_length=160)
    definition: str | None = Field(default=None, max_length=1_000)
    scope_note: str | None = Field(default=None, max_length=40)
    aliases: list[str] | None = Field(default=None, max_length=8)
    parent_tag_id: str | None = None

    @model_validator(mode="after")
    def require_change(self) -> "KnowledgeTagUpdate":
        if not (self.model_fields_set - {"expected_revision"}):
            raise ValueError("at least one field is required")
        return self


__all__ = [
    "KnowledgeDocumentListQuery",
    "KnowledgeBatchTagRequest",
    "KnowledgeSpaceCreate",
    "KnowledgeSpaceUpdate",
    "KnowledgeTagCreate",
    "KnowledgeTagUpdate",
]
