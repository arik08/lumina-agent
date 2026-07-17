from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class LoginRequest(ApiModel):
    login_name: str = Field(min_length=1, max_length=80)
    login_domain: str = Field(default="posco.com", min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class RegistrationRequest(ApiModel):
    email: str = Field(min_length=3, max_length=336)
    display_name: str = Field(min_length=1, max_length=200)
    affiliation: str = Field(min_length=1, max_length=200)
    role: Literal["user", "admin"] = "user"
    password: str = Field(min_length=8, max_length=1024)


class UserSummary(ApiModel):
    id: str
    login_id: str
    display_name: str | None
    affiliation: str | None = None
    role: str
    status: str


class AuthSessionResponse(ApiModel):
    user: UserSummary
    expires_at: datetime
    csrf_token: str


class ProjectCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class ProjectPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    concept: str | None = Field(default=None, max_length=20_000)
    archived: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ProjectPatch":
        if all(
            value is None
            for value in (self.name, self.description, self.concept, self.archived)
        ):
            raise ValueError("at least one project field is required")
        return self


class ProjectResponse(ApiModel):
    id: str
    name: str
    description: str
    project_type: str
    is_default: bool
    concept: str
    concept_revision: int
    concept_hash: str
    created_at: datetime
    updated_at: datetime


class ProjectFileVersionResponse(ApiModel):
    id: str
    version: int
    content_hash: str
    mime_type: str
    size: int
    original_filename: str
    extraction_status: str
    extraction_version: str | None
    locator_map: dict[str, Any]
    source_run_id: str | None
    change_reason: str | None
    created_by_user_id: str
    created_at: datetime


class ProjectFileResponse(ApiModel):
    id: str
    project_id: str
    logical_path: str
    display_name: str
    status: Literal["active", "deleted"]
    revision: int
    current_version: int
    content_hash: str
    mime_type: str
    size: int
    extraction_status: str
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class ProjectFileDetailResponse(ProjectFileResponse):
    versions: list[ProjectFileVersionResponse]


class ProjectFileMove(ApiModel):
    logical_path: str = Field(min_length=1, max_length=1000)
    expected_revision: int = Field(ge=1)


class ProjectFolderResponse(ApiModel):
    id: str
    project_id: str
    logical_path: str
    revision: int
    created_at: datetime
    updated_at: datetime


class ProjectFolderCreate(ApiModel):
    logical_path: str = Field(min_length=1, max_length=1000)


class ProjectFolderMove(ApiModel):
    source_path: str = Field(min_length=1, max_length=1000)
    target_path: str = Field(min_length=1, max_length=1000)


class ConversationCreate(ApiModel):
    project_id: str | None = None
    title: str = Field(default="제목 없음", min_length=1, max_length=200)


class ConversationPatch(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_favorite: bool | None = None
    is_liked: bool | None = None
    archived: bool | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_change(self) -> "ConversationPatch":
        if all(
            value is None
            for value in (self.title, self.is_favorite, self.is_liked, self.archived)
        ):
            raise ValueError("at least one conversation field is required")
        return self


class ConversationMove(ApiModel):
    project_id: str
    idempotency_key: str = Field(min_length=8, max_length=200)


class ConversationBranch(ApiModel):
    anchor_message_id: str
    title: str | None = Field(default=None, min_length=1, max_length=200)


class AgentFrontendReference(ApiModel):
    id: str
    version: str
    frontend_module: str
    frontend_contract: str
    fallback: bool = False


class ConversationListItem(ApiModel):
    id: str
    project_id: str
    title: str
    is_favorite: bool
    is_liked: bool
    last_run_status: str | None
    active_run_id: str | None
    last_sequence: int = 0
    agent: AgentFrontendReference
    revision: int
    created_at: datetime
    updated_at: datetime


class CursorPage(ApiModel):
    items: list[Any]
    next_cursor: str | None = None


class MessageReferenceInput(ApiModel):
    kind: Literal["file", "folder", "artifact", "skill", "mcp"]
    reference_id: str
    version_or_digest: str | None = None
    display_snapshot: dict[str, Any] = Field(default_factory=dict)
    token_start: int | None = Field(default=None, ge=0)
    token_end: int | None = Field(default=None, ge=0)


class ExecutionSelection(ApiModel):
    provider_id: str = "mock"
    model_key: str = "mock-agent"
    effort_id: str | None = "auto"


class RunMessageInput(ApiModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    attachment_ids: list[str] = Field(default_factory=list)
    prompt_references: list[MessageReferenceInput] = Field(default_factory=list)
    output_mode: Literal["auto", "chat", "file"] = "auto"
    analysis_depth: Literal["auto", "brief", "standard", "deep"] = "auto"
    answer_length: Literal["auto", "brief", "standard", "detailed"] = "auto"
    target_output_tokens: int | None = Field(default=None, ge=1, le=40_000)


class RunCreate(ApiModel):
    message: RunMessageInput
    execution: ExecutionSelection | None = None


class UserInputAnswer(ApiModel):
    question_id: str = Field(min_length=1, max_length=80)
    option_id: str | None = Field(default=None, min_length=1, max_length=80)
    custom_text: str | None = Field(default=None, max_length=2000)
    use_ai_judgment: bool = False


class RunActionRequest(ApiModel):
    type: Literal[
        "steer",
        "queue_next",
        "pause",
        "resume",
        "cancel",
        "steer_queued",
        "cancel_command",
        "retry_step",
        "approve",
        "reject",
        "submit_user_input",
    ]
    message: RunMessageInput | None = None
    step_id: str | None = None
    approval_id: str | None = None
    command_id: str | None = None
    input_request_id: str | None = None
    answers: list[UserInputAnswer] = Field(default_factory=list, max_length=4)
    note: str | None = Field(default=None, max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)


class RunAccepted(ApiModel):
    run_id: str
    conversation_id: str
    status: str
    queue_position: int | None = None
    user_message_id: str | None = None


class RunEventResponse(ApiModel):
    run_id: str
    conversation_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class ToolExecutionResponse(ApiModel):
    id: str
    tool_call_id: str
    tool_name: str
    status: str
    input: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None


class ArtifactSummary(ApiModel):
    id: str
    display_name: str
    kind: str
    mime_type: str
    current_version: int
    validation_status: str
    created_at: datetime
    updated_at: datetime


class RunSnapshotResponse(ApiModel):
    run_id: str
    conversation_id: str
    status: str
    last_sequence: int
    assistant_draft: str
    started_at: datetime | None
    finished_at: datetime | None
    execution: dict[str, Any]
    limits: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    activities: list[dict[str, Any]] = Field(default_factory=list)
    tool_executions: list[ToolExecutionResponse]
    artifacts: list[ArtifactSummary]
    pending_commands: list[dict[str, Any]]
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    input_requests: list[dict[str, Any]] = Field(default_factory=list)


class MessageResponse(ApiModel):
    id: str
    conversation_id: str
    run_id: str | None
    role: str
    content: str
    status: str
    metadata: dict[str, Any]
    created_at: datetime


class TurnSetResponse(ApiModel):
    turn_id: str
    messages: list[MessageResponse]
    run: RunSnapshotResponse | None = None


class TurnSetPage(ApiModel):
    turn_sets: list[TurnSetResponse]
    before_cursor: str | None = None
    has_more_before: bool = False


class ProviderModelResponse(ApiModel):
    provider_id: str
    model_key: str
    display_name: str
    runtime_model_id: str
    enabled: bool
    is_default: bool
    sort_order: int
    capabilities: dict[str, Any]
    catalog_revision: str


class ProviderResponse(ApiModel):
    id: str
    display_name: str
    available: bool
    configuration_status: str
    models: list[ProviderModelResponse]


class SettingsPatch(ApiModel):
    theme: Literal["light", "dark"] | None = None
    conversation_width: int | None = Field(default=None, ge=600, le=1400)
    conversation_font_size: int | None = Field(default=None, ge=14, le=24)
    output_mode: Literal["auto", "chat", "file"] | None = None
    clarification_mode: Literal["autonomous", "balanced", "confirming"] | None = None
    execution: ExecutionSelection | None = None
    model_candidates: dict[str, list[str]] | None = None
    expected_revision: str

    @model_validator(mode="after")
    def validate_changes(self) -> "SettingsPatch":
        setting_fields = self.model_fields_set - {"expected_revision"}
        if not setting_fields:
            raise ValueError("at least one setting field is required")
        null_fields = sorted(
            field_name
            for field_name in setting_fields
            if getattr(self, field_name) is None
        )
        if null_fields:
            raise ValueError(f"setting fields cannot be null: {', '.join(null_fields)}")
        return self


class SettingsResponse(ApiModel):
    theme: Literal["light", "dark"]
    output_mode: Literal["auto", "chat", "file"]
    clarification_mode: Literal["autonomous", "balanced", "confirming"]
    execution: ExecutionSelection
    model_candidates: dict[str, list[str]]
    scope: Literal["user", "project"]
    fallback_messages: list[str] = Field(default_factory=list)


class ArtifactVersionResponse(ApiModel):
    artifact_id: str
    version: int
    content: str
    content_hash: str
    mime_type: str
    size: int
    etag: str
    validation_status: str
    created_at: datetime


class ArtifactResponse(ArtifactSummary):
    project_id: str
    conversation_id: str | None
    versions: list[int]


class ArtifactVersionCreate(ApiModel):
    base_version: int = Field(ge=1)
    source_text: str = Field(max_length=5_000_000)
    change_type: Literal["manual_edit"] = "manual_edit"
    change_summary: str = Field(default="", max_length=500)


class ArtifactRestoreRequest(ApiModel):
    source_version: int = Field(ge=1)
    change_summary: str = Field(default="", max_length=500)


class ArtifactDraftSave(ApiModel):
    base_version: int = Field(ge=1)
    content: str = Field(max_length=5_000_000)


class ArtifactDraftResponse(ApiModel):
    artifact_id: str
    base_version: int
    content: str
    etag: str
    updated_at: datetime
    stale: bool


class NotificationResponse(ApiModel):
    id: str
    kind: str
    title: str
    body: str
    deep_link: dict[str, str]
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(ApiModel):
    items: list[NotificationResponse]
    unread_count: int
    next_offset: int | None
    has_more: bool


class AnnouncementAuthorResponse(ApiModel):
    id: str
    login_id: str
    display_name: str | None


class AnnouncementResponse(ApiModel):
    id: str
    title: str
    body: str
    author: AnnouncementAuthorResponse | None
    read_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AnnouncementListResponse(ApiModel):
    items: list[AnnouncementResponse]
    total: int
    unread_count: int = 0


class NotificationUnreadCountResponse(ApiModel):
    unread_count: int


class NotificationReadAllResponse(ApiModel):
    updated_count: int
    read_at: datetime


class ShareCreate(ApiModel):
    conversation_id: str
    anchor_message_id: str | None = None


class ShareCreated(ApiModel):
    id: str
    url_token: str
    expires_at: datetime | None


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    database: str
    executor: str
