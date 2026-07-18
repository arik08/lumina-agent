from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from ..api.schemas import ApiModel


ContentDigest = str
SourceType = Literal["file", "url", "conversation", "text", "connector"]
StatementStatus = Literal["proposed", "approved"]
StatementRank = Literal["preferred", "normal", "deprecated"]
ObjectKind = Literal["entity", "text", "number", "date", "boolean", "json"]


class KnowledgeSpaceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=10_000)
    purpose: str = Field(default="", max_length=20_000)


class KnowledgeSpaceUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    purpose: str | None = Field(default=None, max_length=20_000)


class KnowledgeAutoCaptureUpdate(ApiModel):
    enabled: bool
    space_id: str | None = None


class KnowledgePageUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    manual_markdown: str = Field(default="", max_length=200_000)


class KnowledgeProjectBindingCreate(ApiModel):
    project_id: str
    knowledge_revision_id: str


class KnowledgeProjectBindingUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    knowledge_revision_id: str


class KnowledgeReviewDecision(ApiModel):
    decision: Literal["approved", "rejected"]
    reason: str = Field(default="", max_length=10_000)


class EvidenceSegmentCreate(ApiModel):
    text: str = Field(min_length=1, max_length=200_000)
    locator: dict[str, Any] = Field(default_factory=dict)
    language: str | None = Field(default=None, max_length=40)
    token_count: int = Field(default=0, ge=0, le=10_000_000)


class KnowledgeSourceCreate(ApiModel):
    source_type: SourceType
    title: str = Field(min_length=1, max_length=500)
    canonical_locator: str | None = Field(default=None, max_length=10_000)
    content_digest: ContentDigest = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(min_length=1, max_length=200)
    byte_size: int = Field(default=0, ge=0)
    storage_reference: str | None = Field(default=None, max_length=10_000)
    captured_text: str | None = Field(default=None, max_length=2_000_000)
    parser_name: str | None = Field(default=None, max_length=120)
    parser_version: str | None = Field(default=None, max_length=80)
    parse_digest: ContentDigest | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_segments: list[EvidenceSegmentCreate] = Field(
        default_factory=list, max_length=10_000
    )


class KnowledgeEntityCreate(ApiModel):
    entity_type: str = Field(min_length=1, max_length=80)
    canonical_name: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=20_000)


class KnowledgeStatementCreate(ApiModel):
    subject_entity_id: str
    predicate_key: str = Field(min_length=1, max_length=160)
    object_kind: ObjectKind
    object_entity_id: str | None = None
    object_value: Any = None
    evidence_segment_ids: list[str] = Field(default_factory=list, max_length=100)
    status: StatementStatus = "proposed"
    rank: StatementRank = "normal"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    change_summary: str = Field(default="", max_length=10_000)

    @model_validator(mode="after")
    def validate_object_and_evidence(self) -> "KnowledgeStatementCreate":
        if self.object_kind == "entity":
            if self.object_entity_id is None or self.object_value is not None:
                raise ValueError(
                    "entity objects require objectEntityId and forbid objectValue"
                )
        elif self.object_entity_id is not None or self.object_value is None:
            raise ValueError(
                "literal objects require objectValue and forbid objectEntityId"
            )
        if self.status == "approved" and not self.evidence_segment_ids:
            raise ValueError(
                "approved statements require at least one evidence segment"
            )
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("validFrom must not be after validTo")
        return self
