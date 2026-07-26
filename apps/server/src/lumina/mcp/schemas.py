from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..api.schemas import ApiModel
from .policy import MAX_MCP_TIMEOUT_SECONDS


class McpToolSchemaInput(ApiModel):
    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    )
    description: str = Field(default="", max_length=2000)
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})


class McpConfigurationInput(ApiModel):
    transport: Literal["stdio", "streamable_http"]
    command: list[str] = Field(default_factory=list, max_length=64)
    url_template: str | None = Field(default=None, max_length=2000)
    allowed_hosts: list[str] = Field(default_factory=list, max_length=32)
    allowed_ip_ranges: list[str] = Field(default_factory=list, max_length=64)
    header_templates: dict[str, str] = Field(default_factory=dict, max_length=16)
    tools: list[McpToolSchemaInput] = Field(min_length=1, max_length=256)
    required_secret_names: list[str] = Field(default_factory=list, max_length=32)
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=MAX_MCP_TIMEOUT_SECONDS,
    )


class McpDefinitionCreate(ApiModel):
    name: str = Field(min_length=1, max_length=240)
    slug: str | None = Field(default=None, min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    configuration: McpConfigurationInput


class McpRevisionCreate(ApiModel):
    configuration: McpConfigurationInput


class McpApproval(ApiModel):
    configuration_revision_id: str = Field(min_length=1, max_length=80)


class McpDefinitionStatusPatch(ApiModel):
    status: Literal["disabled", "revoked"]
    reason: str = Field(default="", max_length=1000)


class McpInstallationCreate(ApiModel):
    definition_id: str = Field(min_length=1, max_length=80)
    configuration_revision_id: str | None = Field(
        default=None, min_length=1, max_length=80
    )
    scope_type: Literal["user", "project"] = "user"
    scope_id: str | None = Field(default=None, max_length=80)
    enabled: bool = True
    tool_allowlist: list[str] = Field(default_factory=list, max_length=256)


class McpInstallationPatch(ApiModel):
    enabled: bool | None = None
    project_ids: list[str] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "McpInstallationPatch":
        if not self.model_fields_set:
            raise ValueError("enabled or projectIds is required")
        return self


class McpAnswerTestInput(ApiModel):
    project_id: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=1000)


class McpSecretBindingInput(ApiModel):
    secret_ref: str = Field(min_length=8, max_length=500)
