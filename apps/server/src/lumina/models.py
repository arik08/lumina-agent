from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .db import Base


EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def new_uuid() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Store timestamps in UTC and return timezone-aware values on SQLite too."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, _dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime values must include timezone information")
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, _dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class UUIDPrimaryKeyMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    marketplace_permission_mode: Mapped[str] = mapped_column(
        String(24), default="admin_review", nullable=False
    )
    policy_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    policy_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    policy_digest: Mapped[str] = mapped_column(
        String(64), default=EMPTY_SHA256, nullable=False
    )
    policy_revision_labels: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    policy_revision_contents: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    run_safety_settings_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    initial_execution_settings_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )


class RuntimePromptOverride(TimestampMixin, Base):
    __tablename__ = "runtime_prompt_overrides"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    prompt_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    is_overridden: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class HelpItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "help_items"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "parent_scope_key",
            "title_key",
            name="uq_help_items_sibling_title",
        ),
        Index("ix_help_items_tree", "organization_id", "parent_id", "sort_order"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("help_items.id", ondelete="CASCADE"), index=True
    )
    parent_scope_key: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    title_key: Mapped[str] = mapped_column(String(160), nullable=False)
    markdown_content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    login_name: Mapped[str] = mapped_column(String(120), nullable=False)
    login_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    login_id: Mapped[str] = mapped_column(
        String(380), unique=True, index=True, nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(String(200))
    affiliation: Mapped[str | None] = mapped_column(String(200))
    personal_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    personal_instruction_revision: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    personal_instruction_digest: Mapped[str] = mapped_column(
        String(64), default=EMPTY_SHA256, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="active", index=True, nullable=False
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AuthSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_sessions"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), index=True, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index(
            "uq_projects_default_owner",
            "owner_user_id",
            unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default"),
        ),
        Index("ix_projects_owner_activity", "owner_user_id", "updated_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    concept: Mapped[str] = mapped_column(Text, default="", nullable=False)
    concept_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    concept_hash: Mapped[str] = mapped_column(
        String(64),
        default=EMPTY_SHA256,
        nullable=False,
    )
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    instruction_revision: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    instruction_digest: Mapped[str] = mapped_column(
        String(64), default=EMPTY_SHA256, nullable=False
    )
    project_type: Mapped[str] = mapped_column(
        String(24), default="personal", nullable=False
    )
    visibility: Mapped[str] = mapped_column(
        String(24), default="private", nullable=False
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ProjectMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_owner_activity", "owner_user_id", "last_activity_at"),
        Index("ix_conversations_project_activity", "project_id", "last_activity_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), default="제목 없음", nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(24), default="private", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default="active", index=True, nullable=False
    )
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_liked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(80), default="general", nullable=False)
    agent_version: Mapped[str] = mapped_column(String(40), default="1", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    branch_message_id: Mapped[str | None] = mapped_column(String(36))
    last_activity_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Run(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_conversation_status", "conversation_id", "status"),
        Index("ix_runs_user_status", "user_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(32), default="queued", index=True, nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(80), nullable=False)
    model_key: Mapped[str] = mapped_column(String(160), nullable=False)
    runtime_model_id: Mapped[str] = mapped_column(String(240), nullable=False)
    model_display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    effort: Mapped[str | None] = mapped_column(String(32))
    approval_mode: Mapped[str] = mapped_column(
        String(24), default="on_risk", nullable=False
    )
    environment_type: Mapped[str] = mapped_column(
        String(32), default="local_worker", nullable=False
    )
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    usage_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    assistant_draft: Mapped[str] = mapped_column(Text, default="", nullable=False)
    current_turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Legacy storage column. Zero means unlimited; runtime safety is enforced by
    # deadline, token and cost policies plus context compaction.
    max_turns: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class Plan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("run_id", name="uq_plans_run_id"),)

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="active", index=True, nullable=False
    )


class PlanStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plan_steps"
    __table_args__ = (
        UniqueConstraint("plan_id", "step_key", name="uq_plan_steps_plan_id_step_key"),
        UniqueConstraint("plan_id", "position", name="uq_plan_steps_plan_id_position"),
        Index("ix_plan_steps_timeline", "plan_id", "position"),
    )

    plan_id: Mapped[str] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(48), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="queued", index=True, nullable=False
    )
    depends_on_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    artifact_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    effect: Mapped[str] = mapped_column(String(32), default="read_only", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PlanSubtask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plan_subtasks"
    __table_args__ = (
        UniqueConstraint(
            "plan_step_id", "tool_call_id", name="uq_plan_subtasks_step_tool_call"
        ),
        UniqueConstraint(
            "plan_step_id", "position", name="uq_plan_subtasks_step_position"
        ),
        Index("ix_plan_subtasks_timeline", "plan_step_id", "position"),
    )

    plan_step_id: Mapped[str] = mapped_column(
        ForeignKey("plan_steps.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tool_execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_executions.id", ondelete="SET NULL"), unique=True
    )
    tool_call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="queued", index=True, nullable=False
    )
    depends_on_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    artifact_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    effect: Mapped[str] = mapped_column(
        String(32), default="side_effect", nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    author_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    canonical_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )


class MessageReference(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "message_references"
    __table_args__ = (
        UniqueConstraint("message_id", "kind", "reference_id", "token_start"),
        Index("ix_message_references_target", "kind", "reference_id"),
    )

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version_or_digest: Mapped[str | None] = mapped_column(String(160))
    token_start: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    token_end: Mapped[int | None] = mapped_column(Integer)
    display_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    validation_status: Mapped[str] = mapped_column(
        String(24), default="valid", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class CompactedContextEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "compacted_context_entries"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "version",
            name="uq_compacted_context_entries_conversation_version",
        ),
        Index(
            "ix_compacted_context_entries_history",
            "conversation_id",
            "compacted_at",
        ),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    parent_compaction_id: Mapped[str | None] = mapped_column(
        ForeignKey("compacted_context_entries.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="active", index=True, nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    source_message_range_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    source_event_range_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    estimated_tokens_before: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_tokens_after: Mapped[int] = mapped_column(Integer, nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_input_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_model: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    retrieval_policy: Mapped[str] = mapped_column(
        String(80), default="source_messages_by_id", nullable=False
    )
    access_scope: Mapped[str] = mapped_column(
        String(40), default="private_user", nullable=False
    )
    cooldown_until: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ineffective_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    compacted_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class MessageFeedback(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "message_feedback"
    __table_args__ = (
        Index(
            "uq_message_feedback_active_rating",
            "user_id",
            "message_id",
            unique=True,
            sqlite_where=text("kind = 'rating' AND deleted_at IS NULL"),
            postgresql_where=text("kind = 'rating' AND deleted_at IS NULL"),
        ),
        Index("ix_message_feedback_reports", "message_id", "kind", "status"),
    )

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    rating_value: Mapped[str | None] = mapped_column(String(16))
    report_category: Mapped[str | None] = mapped_column(String(64))
    report_description: Mapped[str | None] = mapped_column(Text)
    diagnostic_scope_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default="active", index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class MessageSelectionComment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "message_selection_comments"
    __table_args__ = (
        Index("ix_message_comments_owner", "author_user_id", "status", "created_at"),
    )

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_message_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    block_id: Mapped[str] = mapped_column(String(160), nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_text: Mapped[str] = mapped_column(Text, nullable=False)
    prefix_context: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    suffix_context: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_status: Mapped[str] = mapped_column(
        String(24), default="exact", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default="submitted", index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class RunEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence"),
        Index("ix_run_events_replay", "run_id", "sequence"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class RunCommand(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "run_commands"
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key"),)

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    command_type: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ToolApproval(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "tool_approvals"
    __table_args__ = (
        UniqueConstraint("run_id", "tool_call_id"),
        Index("ix_tool_approvals_run_status", "run_id", "status"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    effect: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(24), nullable=False)
    argument_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default="pending", index=True, nullable=False
    )
    resolved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolution_note: Mapped[str | None] = mapped_column(String(2000))
    requested_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class QueuedMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "queued_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "idempotency_key"),
        Index("ix_queued_messages_order", "conversation_id", "status", "position"),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_references_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    attachment_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    execution_options_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    promoted_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    promoted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ToolExecution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "tool_executions"
    __table_args__ = (UniqueConstraint("run_id", "tool_call_id"),)

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    validated_input_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_summary: Mapped[str | None] = mapped_column(Text)
    artifact_id: Mapped[str | None] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class Attachment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "attachments"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    sniffed_mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    storage_backend: Mapped[str] = mapped_column(
        String(40), default="local", nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    extraction_status: Mapped[str | None] = mapped_column(String(40))
    extraction_version: Mapped[str | None] = mapped_column(String(80))
    locator_map_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ProjectFile(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "project_files"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "active_path_key", name="uq_project_files_active_path"
        ),
        Index("ix_project_files_listing", "project_id", "status", "updated_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    logical_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    active_path_key: Mapped[str | None] = mapped_column(String(1000))
    current_version_number: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="active", index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)


class ProjectFolder(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "project_folders"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "active_path_key", name="uq_project_folders_active_path"
        ),
        Index("ix_project_folders_listing", "project_id", "status", "logical_path"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    logical_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    active_path_key: Mapped[str | None] = mapped_column(String(1000))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="active", index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)


class ProjectFileVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "project_file_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_file_id",
            "version_number",
            name="uq_project_file_versions_number",
        ),
        Index("ix_project_file_versions_digest", "project_file_id", "content_hash"),
    )

    project_file_id: Mapped[str] = mapped_column(
        ForeignKey("project_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_backend: Mapped[str] = mapped_column(
        String(40), default="local", nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_file_versions.id", ondelete="SET NULL")
    )
    source_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    extraction_status: Mapped[str] = mapped_column(String(40), nullable=False)
    extraction_version: Mapped[str | None] = mapped_column(String(80))
    locator_map_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class Artifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "artifacts"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    source_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(24), default="private", nullable=False
    )
    current_version_number: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ArtifactVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version_number"),)

    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_backend: Mapped[str] = mapped_column(
        String(40), default="local", nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="SET NULL")
    )
    source_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="SET NULL")
    )
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    change_prompt_summary: Mapped[str | None] = mapped_column(Text)
    renderer_manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    asset_manifest_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    validation_status: Mapped[str] = mapped_column(
        String(40), default="pending", nullable=False
    )
    validation_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class ArtifactDraft(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "artifact_drafts"
    __table_args__ = (UniqueConstraint("artifact_id", "user_id"),)

    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    base_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_backend: Mapped[str] = mapped_column(
        String(40), default="local", nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    etag: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class UserSetting(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id", "key"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class UserMemory(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_memories"
    __table_args__ = (
        Index("ix_user_memories_listing", "user_id", "status", "updated_at"),
        Index("ix_user_memories_fact", "user_id", "normalized_fact"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_fact: Mapped[str] = mapped_column(String(1000), nullable=False)
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    conflict_key: Mapped[str | None] = mapped_column(String(160), index=True)
    source_message_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    source_run_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="active", index=True, nullable=False
    )
    supersedes_memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_memories.id", ondelete="SET NULL")
    )
    extractor_version: Mapped[str] = mapped_column(
        String(80), default="manual-v1", nullable=False
    )
    first_learned_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    last_confirmed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ProjectLearningProposal(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "project_learning_proposals"
    __table_args__ = (
        Index(
            "ix_project_learning_proposals_listing",
            "project_id",
            "status",
            "created_at",
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_run_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), index=True)
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    base_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_patch_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    evidence_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    expected_scope: Mapped[str] = mapped_column(
        String(40), default="project", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default="proposed", index=True, nullable=False
    )
    proposed_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    applied_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    rejected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    rolled_back_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ProjectMemory(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "project_memories"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "memory_key",
            "revision",
            name="uq_project_memories_revision",
        ),
        Index(
            "uq_project_memories_active",
            "project_id",
            "memory_key",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_project_memories_listing", "project_id", "status", "created_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    memory_key: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_fact: Mapped[str] = mapped_column(String(1000), nullable=False)
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="active", index=True, nullable=False
    )
    parent_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_memories.id", ondelete="SET NULL")
    )
    source_proposal_id: Mapped[str] = mapped_column(
        ForeignKey("project_learning_proposals.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    source_run_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class ProjectSetting(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "project_settings"
    __table_args__ = (UniqueConstraint("project_id", "key"),)

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class ProviderModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_key"),
        Index(
            "uq_provider_models_default",
            "provider_id",
            unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default"),
        ),
        Index("ix_provider_models_listing", "provider_id", "enabled", "sort_order"),
    )

    provider_id: Mapped[str] = mapped_column(String(80), nullable=False)
    model_key: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    runtime_model_id: Mapped[str] = mapped_column(String(240), nullable=False)
    aliases_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    source: Mapped[str] = mapped_column(String(240), nullable=False)
    catalog_revision: Mapped[str] = mapped_column(String(120), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_target", "target_type", "target_id", "created_at"),
    )

    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(100))
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(120), index=True)
    reason: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class ConversationShareGrant(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conversation_share_grants"
    __table_args__ = (
        Index(
            "ix_conversation_share_recipient",
            "recipient_user_id",
            "revoked_at",
            "expires_at",
        ),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recipient_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    scope: Mapped[str] = mapped_column(
        String(40), default="conversation_snapshot", nullable=False
    )
    anchor_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    snapshot_through_message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False
    )
    permission: Mapped[str] = mapped_column(String(24), default="view", nullable=False)
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Extension(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extensions"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "slug"),
        Index("ix_extensions_catalog", "organization_id", "kind", "visibility"),
    )

    kind: Mapped[str] = mapped_column(String(24), default="skill", nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    creator_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(24), default="private", index=True, nullable=False
    )
    publisher_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Version pointers are validated by the service. Keeping them as opaque IDs
    # avoids a circular DDL dependency between extensions and extension_versions.
    latest_published_version_id: Mapped[str | None] = mapped_column(String(36))
    forked_from_extension_id: Mapped[str | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    forked_from_version_id: Mapped[str | None] = mapped_column(String(36))
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ExtensionDraft(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "extension_drafts"
    __table_args__ = (UniqueConstraint("extension_id", "owner_user_id"),)

    extension_id: Mapped[str] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    base_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("extension_versions.id", ondelete="SET NULL"), index=True
    )
    current_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    package_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="active", index=True, nullable=False
    )
    source_conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class SkillOwnership(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "skill_ownerships"
    __table_args__ = (
        UniqueConstraint("skill_id", "principal_type", "principal_id"),
        Index(
            "ix_skill_ownerships_principal", "principal_type", "principal_id", "role"
        ),
    )

    skill_id: Mapped[str] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    principal_type: Mapped[str] = mapped_column(String(24), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class ExtensionDraftRevision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "extension_draft_revisions"
    __table_args__ = (UniqueConstraint("draft_id", "revision_number"),)

    draft_id: Mapped[str] = mapped_column(
        ForeignKey("extension_drafts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    package_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    package_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    change_summary: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class ExtensionVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "extension_versions"
    __table_args__ = (
        UniqueConstraint("extension_id", "version_number"),
        Index("ix_extension_versions_status", "extension_id", "status"),
    )

    extension_id: Mapped[str] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("extension_versions.id", ondelete="SET NULL")
    )
    package_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    package_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="private", nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ExtensionInstallation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "extension_installations"
    __table_args__ = (
        Index(
            "ix_extension_installations_active",
            "scope_type",
            "scope_id",
            "enabled",
            "removed_at",
        ),
    )

    extension_id: Mapped[str] = mapped_column(
        ForeignKey("extensions.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    version_id: Mapped[str] = mapped_column(
        ForeignKey("extension_versions.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    installed_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    installed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ExtensionDraftBinding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "extension_draft_bindings"
    __table_args__ = (UniqueConstraint("draft_id", "user_id", "project_id"),)

    draft_id: Mapped[str] = mapped_column(
        ForeignKey("extension_drafts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    bound_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class SkillFolder(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "skill_folders"
    __table_args__ = (
        UniqueConstraint(
            "scope_type", "scope_id", "parent_folder_id", "normalized_name"
        ),
        Index("ix_skill_folders_tree", "scope_type", "scope_id", "parent_folder_id"),
    )

    scope_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parent_folder_id: Mapped[str | None] = mapped_column(
        ForeignKey("skill_folders.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class SkillFolderPlacement(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "skill_folder_placements"
    __table_args__ = (UniqueConstraint("skill_id", "scope_type", "scope_id"),)

    folder_id: Mapped[str] = mapped_column(
        ForeignKey("skill_folders.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    moved_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    moved_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class McpDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_definitions"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug"),
        Index("ix_mcp_definitions_catalog", "organization_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="draft", index=True, nullable=False
    )
    # Validated by the service. Keeping the active pointer opaque avoids a
    # circular DDL dependency with mcp_configuration_revisions.
    current_revision_id: Mapped[str | None] = mapped_column(String(36))
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    disabled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class McpConfigurationRevision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "mcp_configuration_revisions"
    __table_args__ = (
        UniqueConstraint(
            "definition_id",
            "revision_number",
            name="uq_mcp_configuration_revision_number",
        ),
        UniqueConstraint(
            "definition_id",
            "config_digest",
            name="uq_mcp_configuration_revision_digest",
        ),
    )

    definition_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_definitions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    transport: Mapped[str] = mapped_column(String(32), nullable=False)
    command_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    url_template: Mapped[str | None] = mapped_column(Text)
    allowed_hosts_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    allowed_ip_ranges_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    header_templates_json: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    tool_schemas_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    required_secret_names_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    config_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(
        String(32), default="validated", nullable=False
    )
    health_status: Mapped[str] = mapped_column(
        String(32), default="not_connected", nullable=False
    )
    schema_status: Mapped[str] = mapped_column(
        String(32), default="declared", nullable=False
    )
    approval_status: Mapped[str] = mapped_column(
        String(24), default="draft", index=True, nullable=False
    )
    validation_summary: Mapped[str] = mapped_column(
        String(500), default="", nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    validated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    approved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class McpInstallation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "mcp_installations"
    __table_args__ = (
        Index(
            "ix_mcp_installations_active",
            "scope_type",
            "scope_id",
            "enabled",
            "removed_at",
        ),
    )

    definition_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_definitions.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    configuration_revision_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_configuration_revisions.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tool_allowlist_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    installed_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    installed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class McpSecretBinding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "mcp_secret_bindings"
    __table_args__ = (
        UniqueConstraint("installation_id", "user_id", "secret_name"),
        Index("ix_mcp_secret_bindings_owner", "user_id", "installation_id"),
    )

    installation_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_installations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    secret_name: Mapped[str] = mapped_column(String(80), nullable=False)
    # This is an opaque pointer into a Secret Store, never the credential value.
    secret_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class ScheduledTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        Index("ix_scheduled_tasks_due", "enabled", "next_run_at"),
        Index("ix_scheduled_tasks_project", "project_id", "archived_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    schedule_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    timezone: Mapped[str] = mapped_column(
        String(80), default="Asia/Seoul", nullable=False
    )
    context_mode: Mapped[str] = mapped_column(
        String(32), default="new_session_per_run", nullable=False
    )
    source_conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    provider_id: Mapped[str] = mapped_column(String(80), default="mock", nullable=False)
    model_key: Mapped[str] = mapped_column(
        String(160), default="mock-agent", nullable=False
    )
    effort: Mapped[str | None] = mapped_column(String(32))
    extension_policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    delivery_policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ScheduledRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "scheduled_runs"
    __table_args__ = (
        UniqueConstraint(
            "scheduled_task_id",
            "scheduled_for",
            name="uq_scheduled_runs_task_scheduled_for",
        ),
        UniqueConstraint(
            "scheduled_task_id",
            "idempotency_key",
            name="uq_scheduled_runs_task_idempotency",
        ),
        Index("ix_scheduled_runs_history", "scheduled_task_id", "created_at"),
    )

    scheduled_task_id: Mapped[str] = mapped_column(
        ForeignKey("scheduled_tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    trigger_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="queued", index=True, nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    output_artifact_ids_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Notification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_notifications_user_idempotency",
        ),
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_unread", "user_id", "read_at", "created_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    scheduled_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("scheduled_tasks.id", ondelete="SET NULL"), index=True
    )
    scheduled_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("scheduled_runs.id", ondelete="SET NULL"), index=True
    )
    deep_link_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class Announcement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "announcements"
    __table_args__ = (
        Index("ix_announcements_organization_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    creator_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


__all__ = [
    "Announcement",
    "Artifact",
    "ArtifactDraft",
    "ArtifactVersion",
    "Attachment",
    "AuditEvent",
    "AuthSession",
    "Conversation",
    "CompactedContextEntry",
    "ConversationShareGrant",
    "Extension",
    "ExtensionDraft",
    "ExtensionDraftBinding",
    "ExtensionDraftRevision",
    "ExtensionInstallation",
    "ExtensionVersion",
    "HelpItem",
    "Message",
    "MessageFeedback",
    "MessageReference",
    "MessageSelectionComment",
    "McpConfigurationRevision",
    "McpDefinition",
    "McpInstallation",
    "McpSecretBinding",
    "Notification",
    "Organization",
    "Plan",
    "PlanStep",
    "PlanSubtask",
    "Project",
    "ProjectFile",
    "ProjectFolder",
    "ProjectFileVersion",
    "ProjectLearningProposal",
    "ProjectMemory",
    "ProjectMembership",
    "ProjectSetting",
    "ProviderModel",
    "QueuedMessage",
    "Run",
    "RunCommand",
    "RunEvent",
    "ScheduledRun",
    "ScheduledTask",
    "SkillFolder",
    "SkillFolderPlacement",
    "ToolExecution",
    "User",
    "UserMemory",
    "UserSetting",
    "new_uuid",
    "utc_now",
]
