from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ..api.schemas import ApiModel


class MemoryCreate(ApiModel):
    category: str = Field(min_length=1, max_length=80)
    fact: str = Field(min_length=1, max_length=1000)
    display_text: str = Field(min_length=1, max_length=4000)
    source_message_ids: list[str] = Field(min_length=1, max_length=20)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expires_at: datetime | None = None


class MemoryPatch(ApiModel):
    category: str | None = Field(default=None, min_length=1, max_length=80)
    fact: str | None = Field(default=None, min_length=1, max_length=1000)
    display_text: str | None = Field(default=None, min_length=1, max_length=4000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: Literal["active", "dismissed"] | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def require_change(self) -> "MemoryPatch":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        null_fields = sorted(
            field_name
            for field_name in self.model_fields_set - {"expires_at"}
            if getattr(self, field_name) is None
        )
        if null_fields:
            raise ValueError(f"memory fields cannot be null: {', '.join(null_fields)}")
        return self


class MemorySettingsPatch(ApiModel):
    mode: Literal["auto", "confirm", "off"] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_setting(self) -> "MemorySettingsPatch":
        if self.mode is None and self.enabled is None:
            raise ValueError("mode or enabled is required")
        if self.mode == "off" and self.enabled is True:
            raise ValueError("enabled=true conflicts with mode=off")
        if self.mode in {"auto", "confirm"} and self.enabled is False:
            raise ValueError("enabled=false conflicts with active mode")
        return self
