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


__all__ = [
    "KnowledgeDocumentListQuery",
    "KnowledgeSpaceCreate",
    "KnowledgeSpaceUpdate",
]
