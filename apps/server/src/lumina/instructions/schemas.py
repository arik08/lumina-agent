from __future__ import annotations

from pydantic import Field

from ..api.schemas import ApiModel


class InstructionUpdate(ApiModel):
    content: str = Field(max_length=40_000)
    expected_revision: int = Field(ge=1)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class InstructionRevisionLabelUpdate(ApiModel):
    label: str = Field(max_length=80)


class InstructionRevisionContentUpdate(ApiModel):
    content: str = Field(max_length=40_000)


class RuntimePromptUpdate(ApiModel):
    content: str = Field(min_length=1, max_length=40_000)
    expected_revision: int = Field(ge=1)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


__all__ = [
    "InstructionRevisionContentUpdate",
    "InstructionRevisionLabelUpdate",
    "InstructionUpdate",
    "RuntimePromptUpdate",
]
