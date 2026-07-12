from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..api.schemas import ApiModel


class RatingPut(ApiModel):
    value: Literal["like", "dislike"]


class ReportDiagnosticScope(ApiModel):
    include_run_state: bool = True
    include_tool_summaries: bool = True
    include_conversation: bool = False
    include_attachments: bool = False


class ReportCreate(ApiModel):
    category: Literal[
        "inaccurate",
        "source_issue",
        "harmful",
        "privacy",
        "ui_tool_error",
        "other",
    ]
    description: str = Field(default="", max_length=4000)
    diagnostic_scope: ReportDiagnosticScope = Field(
        default_factory=ReportDiagnosticScope
    )


class CommentCreate(ApiModel):
    block_id: str = Field(min_length=1, max_length=160)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    selected_text: str = Field(min_length=1, max_length=20_000)
    prefix_context: str = Field(default="", max_length=500)
    suffix_context: str = Field(default="", max_length=500)
    instruction: str = Field(min_length=1, max_length=20_000)
    status: Literal["draft", "submitted"] = "submitted"

    @model_validator(mode="after")
    def validate_offsets(self) -> "CommentCreate":
        if self.end_offset < self.start_offset:
            raise ValueError("end_offset must be greater than or equal to start_offset")
        return self


class CommentPatch(ApiModel):
    instruction: str | None = Field(default=None, min_length=1, max_length=20_000)
    status: Literal["draft", "submitted", "resolved"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "CommentPatch":
        if self.instruction is None and self.status is None:
            raise ValueError("at least one field is required")
        return self
