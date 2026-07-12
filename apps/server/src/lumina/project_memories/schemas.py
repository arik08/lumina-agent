from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..api.schemas import ApiModel


class ProjectLearningEvidence(ApiModel):
    kind: Literal["message", "run", "file", "artifact"]
    reference_id: str = Field(min_length=1, max_length=80)
    version_or_digest: str | None = Field(default=None, max_length=160)
    note: str = Field(default="", max_length=1000)


class ProjectLearningProposalCreate(ApiModel):
    source_run_ids: list[str] = Field(min_length=1, max_length=20)
    target_type: Literal["project_memory", "project_concept"]
    target_id: str | None = Field(default=None, max_length=36)
    base_revision: int = Field(ge=0)
    base_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_patch: dict[str, object]
    rationale: str = Field(min_length=1, max_length=4000)
    evidence_refs: list[ProjectLearningEvidence] = Field(
        default_factory=list, max_length=20
    )
    expected_scope: Literal["project"] = "project"

    @model_validator(mode="after")
    def validate_target(self) -> "ProjectLearningProposalCreate":
        if self.target_type == "project_concept" and self.target_id is not None:
            raise ValueError("project_concept target_id must be omitted")
        return self


class ProjectLearningReview(ApiModel):
    note: str = Field(default="", max_length=1000)
