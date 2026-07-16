from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

MessageRole = Literal["system", "user", "assistant", "tool"]
ProviderEventType = Literal[
    "text_delta",
    "tool_call_started",
    "tool_call_delta",
    "tool_call_completed",
    "usage",
    "completed",
]


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    text: bool = True
    streaming: bool = True
    tools: bool = False
    structured_output: bool = False
    image_input: bool = False
    image_generation: bool = False
    document_input: bool = False
    reasoning_effort: bool = False
    server_side_conversation: bool = False
    allowed_image_mime_types: tuple[str, ...] = ()
    allowed_document_mime_types: tuple[str, ...] = ()
    max_input_bytes: int | None = None
    max_document_pages: int | None = None
    context_window: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderImage:
    mime_type: str
    data_base64: str


@dataclass(frozen=True, slots=True)
class ProviderMessage:
    role: MessageRole
    content: str | None = None
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    images: tuple[ProviderImage, ...] = ()
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    model: str
    messages: tuple[ProviderMessage, ...]
    tools: tuple[Mapping[str, Any], ...] = ()
    effort: str | None = None
    response_format: Mapping[str, Any] | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    uncached_input_tokens: int = 0
    output_tokens: int = 0
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    type: ProviderEventType
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str | None = None
    arguments_json: str | None = None
    usage: ProviderUsage | None = None
    stop_reason: str | None = None
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class ProviderAdapter(Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]: ...
