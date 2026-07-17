from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import Field, model_validator

from ..api.schemas import ApiModel, ExecutionSelection


ScheduleKind = Literal["hourly", "daily", "weekly", "weekdays", "manual"]
ContextMode = Literal["continue_session", "new_session_per_run"]
ExtensionSnapshotPolicy = Literal["pinned", "latest_allowed"]
SCHEDULE_KINDS = frozenset(get_args(ScheduleKind))
CONTEXT_MODES = frozenset(get_args(ContextMode))
EXTENSION_SNAPSHOT_POLICIES = frozenset(get_args(ExtensionSnapshotPolicy))


class ScheduledTaskCreate(ApiModel):
    project_id: str
    name: str = Field(min_length=1, max_length=240)
    instructions: str = Field(min_length=1, max_length=200_000)
    schedule_kind: ScheduleKind
    schedule_config: dict[str, Any] = Field(default_factory=dict)
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=80)
    context_mode: ContextMode = "new_session_per_run"
    source_conversation_id: str | None = None
    execution: ExecutionSelection = Field(default_factory=ExecutionSelection)
    extension_snapshot_policy: ExtensionSnapshotPolicy = "pinned"
    delivery_policy: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    max_attempts: int = Field(default=1, ge=1, le=10)
    timeout_seconds: int = Field(default=900, ge=30, le=86_400)


class ScheduledTaskPatch(ApiModel):
    project_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=240)
    instructions: str | None = Field(default=None, min_length=1, max_length=200_000)
    schedule_kind: ScheduleKind | None = None
    schedule_config: dict[str, Any] | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    context_mode: ContextMode | None = None
    source_conversation_id: str | None = None
    execution: ExecutionSelection | None = None
    extension_snapshot_policy: ExtensionSnapshotPolicy | None = None
    delivery_policy: dict[str, Any] | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    timeout_seconds: int | None = Field(default=None, ge=30, le=86_400)

    @model_validator(mode="after")
    def validate_changes(self) -> "ScheduledTaskPatch":
        if not self.model_fields_set:
            raise ValueError("at least one scheduled task field is required")
        null_fields = sorted(
            field_name
            for field_name in self.model_fields_set - {"source_conversation_id"}
            if getattr(self, field_name) is None
        )
        if null_fields:
            raise ValueError(f"fields cannot be null: {', '.join(null_fields)}")
        return self
