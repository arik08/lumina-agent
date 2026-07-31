from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import inspect
import json
import os
import re
import shutil
import socket
import time
import weakref
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import httpcore
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import SessionLocal
from ..http_client import TrustManager, TrustProfile, redact_sensitive_text
from ..models import (
    McpConfigurationRevision,
    McpDefinition,
    McpInstallation,
    McpSecretBinding,
    Run,
    User,
)
from .service import ALLOWED_SECRET_HEADER_NAMES, ALLOWED_STDIO_EXECUTABLES
from .policy import APPROVABLE_PRIVATE_NETWORKS, SECRET_NAME_PATTERN


PROTOCOL_VERSION = "2025-11-25"
_MAX_MESSAGE_BYTES = 1024 * 1024
_MAX_TOOL_PAGES = 20
_MAX_TOOLS = 1024
_MAX_SESSION_ID_BYTES = 1024
_MAX_CACHED_CONNECTIONS = 32
_MAX_RETIRED_CONNECTION_RETRIES = 2
_SAFE_ENV_NAMES = (
    "PATH",
    "PATHEXT",
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
)
_TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_ENV_SECRET_REF_RE = re.compile(r"^env://([A-Za-z_][A-Za-z0-9_]*)$")


class McpRuntimeError(RuntimeError):
    """A deliberately sanitized MCP runtime failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    definition_id: str
    installation_id: str
    configuration_revision_id: str
    digest: str
    slug: str
    transport: str
    command: tuple[str, ...]
    url: str | None
    allowed_hosts: tuple[str, ...]
    allowed_ip_ranges: tuple[str, ...]
    header_templates: Mapping[str, str]
    declared_tools: tuple[Mapping[str, Any], ...]
    tool_allowlist: tuple[str, ...]
    required_secret_names: tuple[str, ...]
    secret_refs: Mapping[str, str] = field(repr=False)
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class PreparedMcpTool:
    provider_name: str
    server_slug: str
    original_name: str
    description: str
    input_schema: Mapping[str, Any]
    config: McpServerConfig = field(repr=False)

    @property
    def provider_schema(self) -> Mapping[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.provider_name,
                "description": self.description,
                "parameters": dict(self.input_schema),
            },
        }


@dataclass(slots=True)
class _CachedMcpConnection:
    connection: "_McpConnection"
    negotiated_tools: tuple[dict[str, Any], ...]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active_users: int = 0
    last_used_at: float = field(default_factory=time.monotonic)
    retired: bool = False


class DnsResolver(Protocol):
    def __call__(self, host: str, port: int) -> Awaitable[set[str]] | set[str]: ...


def load_pinned_server_configs(db: Session, run: Run) -> tuple[McpServerConfig, ...]:
    snapshots = run.snapshot_json.get("mcp_servers", [])
    if not isinstance(snapshots, list):
        raise _runtime_error("mcp_snapshot_invalid", "snapshot")
    configs: list[McpServerConfig] = []
    for raw_snapshot in snapshots:
        if not isinstance(raw_snapshot, dict):
            raise _runtime_error("mcp_snapshot_invalid", "snapshot")
        installation_id = str(raw_snapshot.get("installation_id", ""))
        revision_id = str(raw_snapshot.get("configuration_revision_id", ""))
        definition_id = str(raw_snapshot.get("definition_id", ""))
        digest = str(raw_snapshot.get("digest", ""))
        installation = db.get(McpInstallation, installation_id)
        revision = db.get(McpConfigurationRevision, revision_id)
        definition = db.get(McpDefinition, definition_id)
        if (
            installation is None
            or revision is None
            or definition is None
            or installation.definition_id != definition.id
            or installation.configuration_revision_id != revision.id
            or revision.definition_id != definition.id
            or revision.config_digest != digest
        ):
            raise _runtime_error("mcp_snapshot_mismatch", "snapshot")

        snapshot_allowlist = _string_tuple(raw_snapshot.get("tool_allowlist"))
        if snapshot_allowlist != tuple(installation.tool_allowlist_json):
            raise _runtime_error("mcp_snapshot_mismatch", "snapshot")
        snapshot_ip_ranges = _string_tuple(raw_snapshot.get("allowed_ip_ranges", []))
        if snapshot_ip_ranges != tuple(revision.allowed_ip_ranges_json):
            raise _runtime_error("mcp_snapshot_mismatch", "snapshot")
        bindings = {
            binding.secret_name: binding.secret_ref
            for binding in db.scalars(
                select(McpSecretBinding).where(
                    McpSecretBinding.installation_id == installation.id,
                    McpSecretBinding.user_id == run.user_id,
                )
            )
        }
        required = tuple(revision.required_secret_names_json)
        if set(required) != set(bindings):
            raise _runtime_error("mcp_secret_binding_missing", "credential")
        configs.append(
            McpServerConfig(
                definition_id=definition.id,
                installation_id=installation.id,
                configuration_revision_id=revision.id,
                digest=revision.config_digest,
                slug=definition.slug,
                transport=revision.transport,
                command=tuple(revision.command_json),
                url=revision.url_template,
                allowed_hosts=tuple(revision.allowed_hosts_json),
                allowed_ip_ranges=snapshot_ip_ranges,
                header_templates=dict(revision.header_templates_json),
                declared_tools=tuple(revision.tool_schemas_json),
                tool_allowlist=snapshot_allowlist,
                required_secret_names=required,
                secret_refs=bindings,
                timeout_seconds=float(revision.timeout_seconds),
            )
        )
    return tuple(configs)


def load_installation_server_config(
    db: Session, installation: McpInstallation, *, user: User
) -> McpServerConfig:
    revision = db.get(McpConfigurationRevision, installation.configuration_revision_id)
    definition = db.get(McpDefinition, installation.definition_id)
    if (
        revision is None
        or definition is None
        or revision.definition_id != definition.id
    ):
        raise _runtime_error("mcp_snapshot_invalid", "snapshot")
    bindings = {
        binding.secret_name: binding.secret_ref
        for binding in db.scalars(
            select(McpSecretBinding).where(
                McpSecretBinding.installation_id == installation.id,
                McpSecretBinding.user_id == user.id,
            )
        )
    }
    required = tuple(revision.required_secret_names_json)
    if set(required) != set(bindings):
        raise _runtime_error("mcp_secret_binding_missing", "credential")
    return McpServerConfig(
        definition_id=definition.id,
        installation_id=installation.id,
        configuration_revision_id=revision.id,
        digest=revision.config_digest,
        slug=definition.slug,
        transport=revision.transport,
        command=tuple(revision.command_json),
        url=revision.url_template,
        allowed_hosts=tuple(revision.allowed_hosts_json),
        allowed_ip_ranges=tuple(revision.allowed_ip_ranges_json),
        header_templates=dict(revision.header_templates_json),
        declared_tools=tuple(revision.tool_schemas_json),
        tool_allowlist=tuple(installation.tool_allowlist_json),
        required_secret_names=required,
        secret_refs=bindings,
        timeout_seconds=float(revision.timeout_seconds),
    )


class McpRuntime:
    def __init__(
        self,
        settings: Settings,
        *,
        trust_profile: TrustProfile | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        dns_resolver: DnsResolver | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self._trust_profile = trust_profile
        self._http_transport = http_transport
        self._dns_resolver = dns_resolver or _resolve_host
        self._environment = dict(os.environ if environment is None else environment)
        self._connections: dict[str, _CachedMcpConnection] = {}
        self._connection_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._closing = False
        self._lifecycle_revision = 0

    @property
    def connection_statistics(self) -> dict[str, int]:
        return {
            "cached": len(self._connections),
            "activeUsers": sum(
                cached.active_users for cached in self._connections.values()
            ),
            "limit": _MAX_CACHED_CONNECTIONS,
        }

    async def prepare_run(self, run_id: str) -> tuple[PreparedMcpTool, ...]:
        configs = await asyncio.to_thread(self._pinned_server_configs, run_id)
        return await self.prepare_servers(configs)

    def _pinned_server_configs(self, run_id: str) -> tuple[McpServerConfig, ...]:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if run is None:
                raise _runtime_error("mcp_snapshot_invalid", "snapshot")
            return load_pinned_server_configs(db, run)

    async def prepare_servers(
        self, configs: Sequence[McpServerConfig]
    ) -> tuple[PreparedMcpTool, ...]:
        prepared: list[PreparedMcpTool] = []
        names: set[str] = set()
        server_tools = await asyncio.gather(
            *(self._prepare_server(config) for config in configs)
        )
        for config, tools in zip(configs, server_tools, strict=True):
            for tool in tools:
                provider_name = _provider_tool_name(config, str(tool["name"]))
                if provider_name in names:
                    raise _runtime_error("mcp_tool_name_collision", "schema")
                names.add(provider_name)
                prepared.append(
                    PreparedMcpTool(
                        provider_name=provider_name,
                        server_slug=config.slug,
                        original_name=str(tool["name"]),
                        description=str(tool.get("description", ""))[:2000],
                        input_schema=cast(Mapping[str, Any], tool["inputSchema"]),
                        config=config,
                    )
                )
        return tuple(prepared)

    async def call_tool(
        self, tool: PreparedMcpTool, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        secrets = self._resolve_secrets(tool.config)
        retired_retries = 0
        while True:
            cache_key, cached = await self._ready_connection(tool.config, secrets)
            try:
                current = {
                    str(item["name"]): item
                    for item in _intersect_tools(tool.config, cached.negotiated_tools)
                }
                current_tool = current.get(tool.original_name)
                if current_tool is None or current_tool.get("inputSchema") != dict(
                    tool.input_schema
                ):
                    raise _runtime_error("mcp_tool_schema_drift", "schema")
                async with cached.lock:
                    if cached.retired:
                        retired_retries += 1
                        if retired_retries > _MAX_RETIRED_CONNECTION_RETRIES:
                            raise _runtime_error(
                                "mcp_connection_unstable", "network", retryable=True
                            )
                        continue
                    try:
                        raw_result = await cached.connection.call_tool(
                            tool.original_name, dict(arguments)
                        )
                    except asyncio.CancelledError:
                        cached.retired = True
                        raise
                    except McpRuntimeError as exc:
                        if exc.retryable or exc.stage in {"network", "transport"}:
                            cached.retired = True
                        raise
            except asyncio.CancelledError:
                await asyncio.shield(self._discard_connection(cache_key, cached))
                raise
            except McpRuntimeError as exc:
                if exc.retryable or exc.stage in {"network", "transport"}:
                    await self._discard_connection(cache_key, cached)
                raise
            finally:
                await asyncio.shield(self._release_connection(cache_key, cached))
            break
        safe_result = _redact_value(raw_result, tuple(secrets.values()))
        if not isinstance(safe_result, dict):
            raise _runtime_error("mcp_response_invalid", "result")
        if safe_result.get("isError") is True:
            raise _runtime_error(
                "mcp_tool_error",
                "tool",
                detail=_mcp_error_detail(safe_result),
            )
        return {
            "server": tool.server_slug,
            "tool": tool.original_name,
            "content": safe_result.get("content", []),
            **(
                {"structuredContent": safe_result["structuredContent"]}
                if "structuredContent" in safe_result
                else {}
            ),
            "isError": False,
        }

    async def close(self) -> None:
        self._closing = True
        self._lifecycle_revision += 1
        try:
            cached_connections = list(self._connections.values())
            self._connections.clear()
            self._connection_locks.clear()

            async def close_cached(cached: _CachedMcpConnection) -> None:
                async with cached.lock:
                    await cached.connection.__aexit__(None, None, None)

            results = await asyncio.gather(
                *(close_cached(cached) for cached in cached_connections),
                return_exceptions=True,
            )
            failure = next(
                (result for result in results if isinstance(result, BaseException)),
                None,
            )
            if failure is not None:
                raise failure
        finally:
            self._closing = False

    async def _prepare_server(
        self, config: McpServerConfig
    ) -> tuple[dict[str, Any], ...]:
        secrets = self._resolve_secrets(config)
        cache_key, cached = await self._ready_connection(config, secrets)
        try:
            return tuple(_intersect_tools(config, cached.negotiated_tools))
        except BaseException:
            await self._discard_connection(cache_key, cached)
            raise
        finally:
            await asyncio.shield(self._release_connection(cache_key, cached))

    async def _ready_connection(
        self, config: McpServerConfig, secrets: Mapping[str, str]
    ) -> tuple[str, _CachedMcpConnection]:
        if self._closing:
            raise _runtime_error("mcp_runtime_closing", "transport", retryable=True)
        lifecycle_revision = self._lifecycle_revision
        cache_key = _connection_cache_key(config, secrets)
        cached = self._connections.get(cache_key)
        if cached is not None:
            cached.active_users += 1
            cached.last_used_at = time.monotonic()
            return cache_key, cached
        lock = self._connection_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            if self._closing:
                raise _runtime_error("mcp_runtime_closing", "transport", retryable=True)
            cached = self._connections.get(cache_key)
            if cached is not None:
                cached.active_users += 1
                cached.last_used_at = time.monotonic()
                return cache_key, cached
            connection = self._connection(config, secrets)
            await connection.__aenter__()
            try:
                negotiated = await connection.initialize_and_list_tools()
                if self._closing or lifecycle_revision != self._lifecycle_revision:
                    raise _runtime_error(
                        "mcp_runtime_closing", "transport", retryable=True
                    )
            except BaseException:
                await connection.__aexit__(None, None, None)
                raise
            cached = _CachedMcpConnection(
                connection=connection,
                negotiated_tools=tuple(negotiated),
                active_users=1,
            )
            self._connections[cache_key] = cached
            await self._evict_idle_connections(exclude_key=cache_key)
            return cache_key, cached

    async def _release_connection(
        self, cache_key: str, cached: _CachedMcpConnection
    ) -> None:
        cached.active_users = max(0, cached.active_users - 1)
        cached.last_used_at = time.monotonic()
        await self._evict_idle_connections(exclude_key=cache_key)

    async def _evict_idle_connections(self, *, exclude_key: str) -> None:
        overflow = len(self._connections) - _MAX_CACHED_CONNECTIONS
        if overflow <= 0:
            return
        candidates = sorted(
            (
                (cache_key, cached)
                for cache_key, cached in self._connections.items()
                if cache_key != exclude_key
                and cached.active_users == 0
                and not cached.lock.locked()
            ),
            key=lambda item: item[1].last_used_at,
        )
        evicted: list[_CachedMcpConnection] = []
        for cache_key, cached in candidates[:overflow]:
            if self._connections.get(cache_key) is cached:
                self._connections.pop(cache_key, None)
                evicted.append(cached)

        async def close_evicted(cached: _CachedMcpConnection) -> None:
            async with cached.lock:
                await cached.connection.__aexit__(None, None, None)

        results = await asyncio.gather(
            *(close_evicted(cached) for cached in evicted),
            return_exceptions=True,
        )
        failure = next(
            (result for result in results if isinstance(result, BaseException)), None
        )
        if failure is not None:
            raise failure

    async def _discard_connection(
        self, cache_key: str, cached: _CachedMcpConnection
    ) -> None:
        if self._connections.get(cache_key) is not cached:
            return
        cached.retired = True
        self._connections.pop(cache_key, None)
        async with cached.lock:
            await cached.connection.__aexit__(None, None, None)

    def _resolve_secrets(self, config: McpServerConfig) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for secret_name in config.required_secret_names:
            if not SECRET_NAME_PATTERN.fullmatch(secret_name):
                raise _runtime_error("mcp_secret_binding_invalid", "credential")
            secret_ref = config.secret_refs.get(secret_name, "")
            match = _ENV_SECRET_REF_RE.fullmatch(secret_ref)
            if match is None:
                raise _runtime_error("mcp_secret_resolver_unavailable", "credential")
            value = _environment_value(self._environment, match.group(1))
            if not value:
                raise _runtime_error("mcp_secret_unavailable", "credential")
            resolved[secret_name] = value
        return resolved

    def _connection(
        self, config: McpServerConfig, secrets: Mapping[str, str]
    ) -> "_McpConnection":
        profile = (
            self._trust_profile
            or TrustManager(
                repo_root=Path(__file__).resolve().parents[5],
                runtime_dir=self.settings.data_dir / "certs" / "runtime",
                env=self._environment,
            ).initialize()
        )
        if config.transport == "stdio":
            transport: _JsonRpcTransport = _StdioTransport(
                config,
                secrets,
                profile,
                working_dir=Path(__file__).resolve().parents[5],
                base_environment=self._environment,
            )
        elif config.transport == "streamable_http":
            transport = _StreamableHttpTransport(
                config,
                secrets,
                profile,
                http_transport=self._http_transport,
                dns_resolver=self._dns_resolver,
            )
        else:
            raise _runtime_error("mcp_transport_invalid", "transport")
        return _McpConnection(
            transport,
            timeout_seconds=config.timeout_seconds,
            sensitive_values=tuple(secrets.values()),
        )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _runtime_error("mcp_snapshot_invalid", "snapshot")
    return tuple(str(item) for item in value)


def _connection_cache_key(config: McpServerConfig, secrets: Mapping[str, str]) -> str:
    material = json.dumps(
        {
            "installation_id": config.installation_id,
            "configuration_revision_id": config.configuration_revision_id,
            "digest": config.digest,
            "secrets": sorted(secrets.items()),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _runtime_error(
    code: str,
    stage: str,
    *,
    retryable: bool = False,
    detail: str | None = None,
) -> McpRuntimeError:
    messages = {
        "credential": "MCP credential을 안전하게 준비할 수 없습니다.",
        "timeout": "MCP 도구 응답 시간이 초과되었습니다.",
        "cancel": "MCP 도구 실행이 취소되었습니다.",
        "schema": "MCP 도구 계약이 승인된 revision과 일치하지 않습니다.",
        "network": "MCP 서버에 안전하게 연결할 수 없습니다.",
        "tool": "MCP 도구가 요청을 완료하지 못했습니다.",
    }
    message = messages.get(stage, "MCP 요청을 안전하게 처리할 수 없습니다.")
    if detail:
        message = f"{message} 서버 응답: {detail[:1500]}"
    return McpRuntimeError(
        code,
        message,
        stage=stage,
        retryable=retryable,
    )


class _JsonRpcTransport(Protocol):
    async def start(self) -> None: ...

    async def request_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    async def send_notification(self, payload: Mapping[str, Any]) -> None: ...

    async def close(self) -> None: ...


class _McpConnection:
    def __init__(
        self,
        transport: _JsonRpcTransport,
        *,
        timeout_seconds: float,
        sensitive_values: tuple[str, ...] = (),
    ) -> None:
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._sensitive_values = sensitive_values
        self._next_id = 1
        self._initialized = False

    async def __aenter__(self) -> "_McpConnection":
        await self._transport.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._transport.close()

    async def initialize_and_list_tools(self) -> list[dict[str, Any]]:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "lumina-agent", "version": "0.1.0"},
            },
        )
        if result.get("protocolVersion") != PROTOCOL_VERSION:
            raise _runtime_error("mcp_protocol_version_mismatch", "schema")
        capabilities = result.get("capabilities")
        if not isinstance(capabilities, dict) or not isinstance(
            capabilities.get("tools"), dict
        ):
            raise _runtime_error("mcp_tools_capability_missing", "schema")
        await self._notification("notifications/initialized", {})
        self._initialized = True

        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _page in range(_MAX_TOOL_PAGES):
            params = {"cursor": cursor} if cursor is not None else {}
            page = await self._request("tools/list", params)
            raw_tools = page.get("tools")
            if not isinstance(raw_tools, list):
                raise _runtime_error("mcp_response_invalid", "schema")
            for raw_tool in raw_tools:
                tools.append(_normalize_negotiated_tool(raw_tool))
                if len(tools) > _MAX_TOOLS:
                    raise _runtime_error("mcp_tool_limit_exceeded", "schema")
            next_cursor = page.get("nextCursor")
            if next_cursor is None:
                return tools
            if (
                not isinstance(next_cursor, str)
                or not next_cursor
                or len(next_cursor) > 1000
                or next_cursor in seen_cursors
            ):
                raise _runtime_error("mcp_response_invalid", "schema")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise _runtime_error("mcp_tool_page_limit_exceeded", "schema")

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not self._initialized:
            raise _runtime_error("mcp_lifecycle_invalid", "transport")
        result = await self._request(
            "tools/call", {"name": name, "arguments": dict(arguments)}
        )
        if not isinstance(result.get("content", []), list):
            raise _runtime_error("mcp_response_invalid", "result")
        if "structuredContent" in result and not isinstance(
            result["structuredContent"], dict
        ):
            raise _runtime_error("mcp_response_invalid", "result")
        if "isError" in result and not isinstance(result["isError"], bool):
            raise _runtime_error("mcp_response_invalid", "result")
        return result

    async def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await self._transport.request_payload(payload)
        except TimeoutError as exc:
            await self._cancel_request(request_id, "timeout")
            raise _runtime_error("mcp_timeout", "timeout", retryable=True) from exc
        except asyncio.CancelledError:
            await self._cancel_request(request_id, "cancelled")
            raise
        if response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
            raise _runtime_error("mcp_response_invalid", "transport")
        if "error" in response:
            raise _runtime_error(
                "mcp_jsonrpc_error",
                "tool",
                detail=_mcp_error_detail(
                    response["error"], secrets=self._sensitive_values
                ),
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise _runtime_error("mcp_response_invalid", "transport")
        return result

    async def _notification(self, method: str, params: Mapping[str, Any]) -> None:
        await self._transport.send_notification(
            {"jsonrpc": "2.0", "method": method, "params": dict(params)}
        )

    async def _cancel_request(self, request_id: int, reason: str) -> None:
        try:
            await asyncio.shield(
                self._notification(
                    "notifications/cancelled",
                    {"requestId": request_id, "reason": reason},
                )
            )
        except Exception:
            # Cancellation is best effort; the original timeout/cancel remains primary.
            return


class _StdioTransport:
    def __init__(
        self,
        config: McpServerConfig,
        secrets: Mapping[str, str],
        trust_profile: TrustProfile,
        *,
        working_dir: Path,
        base_environment: Mapping[str, str],
    ) -> None:
        self._config = config
        self._secrets = dict(secrets)
        self._trust_profile = trust_profile
        self._working_dir = working_dir
        self._base_environment = base_environment
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        _validate_runtime_command(self._config.command)
        environment = {
            name: value
            for name in _SAFE_ENV_NAMES
            if (value := _environment_value(self._base_environment, name))
        }
        environment.update(self._secrets)
        environment.setdefault("PYTHONUTF8", "1")
        environment.setdefault("PYTHONIOENCODING", "utf-8")
        environment = self._trust_profile.subprocess_environment(environment)
        try:
            command = _resolve_stdio_command(self._config.command)
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
                env=environment,
                limit=_MAX_MESSAGE_BYTES + 1,
            )
        except (OSError, ValueError) as exc:
            raise _runtime_error("mcp_process_start_failed", "network") from exc
        assert self._process.stderr is not None
        self._stderr_task = asyncio.create_task(
            _discard_stderr(self._process.stderr), name="mcp-stderr-discard"
        )

    async def request_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        await self._write(payload)
        expected_id = payload.get("id")
        for _message in range(100):
            response = await self._read()
            if response.get("id") == expected_id:
                return response
        raise _runtime_error("mcp_response_invalid", "transport")

    async def send_notification(self, payload: Mapping[str, Any]) -> None:
        await self._write(payload)

    async def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
            try:
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=1.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        stderr_task = self._stderr_task
        if stderr_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(stderr_task), timeout=1.0)
            except TimeoutError:
                stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)
        self._stderr_task = None
        self._process = None

    async def _write(self, payload: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise _runtime_error("mcp_process_unavailable", "network")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(encoded) > _MAX_MESSAGE_BYTES or b"\n" in encoded:
            raise _runtime_error("mcp_message_too_large", "transport")
        try:
            process.stdin.write(encoded + b"\n")
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise _runtime_error("mcp_process_unavailable", "network") from exc

    async def _read(self) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise _runtime_error("mcp_process_unavailable", "network")
        try:
            raw = await process.stdout.readline()
        except (ValueError, asyncio.LimitOverrunError) as exc:
            raise _runtime_error("mcp_message_too_large", "transport") from exc
        if not raw or len(raw) > _MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
            raise _runtime_error("mcp_response_invalid", "transport")
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _runtime_error("mcp_response_invalid", "transport") from exc
        if not isinstance(decoded, dict):
            raise _runtime_error("mcp_response_invalid", "transport")
        return decoded


class _CoreResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: AsyncIterable[bytes]) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._stream:
            yield chunk

    async def aclose(self) -> None:
        close = getattr(self._stream, "aclose", None)
        if close is not None:
            await close()


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve once in Lumina, then connect only to that validated address.

    httpcore still receives the original hostname in its request URL, so TLS uses
    that hostname for SNI and certificate verification. Only the socket target is
    replaced with the already-approved IP address.
    """

    def __init__(
        self,
        expected_host: str,
        pinned_address: str,
        *,
        delegate: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._expected_host = expected_host.casefold().rstrip(".")
        self._pinned_address = pinned_address
        self._delegate = delegate or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if host.casefold().rstrip(".") != self._expected_host:
            raise httpcore.ConnectError("MCP connection target changed")
        return await self._delegate.connect_tcp(
            self._pinned_address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=cast(Any, socket_options),
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: object | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del path, timeout, socket_options
        raise httpcore.ConnectError("MCP Unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


class _PinnedAsyncHttpTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        trust_profile: TrustProfile,
        *,
        expected_host: str,
        pinned_address: str,
    ) -> None:
        network_backend = _PinnedNetworkBackend(expected_host, pinned_address)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=trust_profile.ssl_context,
            max_connections=1,
            max_keepalive_connections=1,
            http1=True,
            http2=False,
            network_backend=network_backend,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not isinstance(request.stream, httpx.AsyncByteStream):
            raise TypeError("MCP request body must be asynchronous")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = await self._pool.handle_async_request(core_request)
        except httpcore.TimeoutException as exc:
            raise httpx.TimeoutException(str(exc), request=request) from exc
        except httpcore.NetworkError as exc:
            raise httpx.NetworkError(str(exc), request=request) from exc
        except httpcore.ProxyError as exc:
            raise httpx.ProxyError(str(exc), request=request) from exc
        except httpcore.UnsupportedProtocol as exc:
            raise httpx.UnsupportedProtocol(str(exc), request=request) from exc
        except httpcore.ProtocolError as exc:
            raise httpx.ProtocolError(str(exc), request=request) from exc
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_CoreResponseStream(cast(AsyncIterable[bytes], response.stream)),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


class _StreamableHttpTransport:
    def __init__(
        self,
        config: McpServerConfig,
        secrets: Mapping[str, str],
        trust_profile: TrustProfile,
        *,
        http_transport: httpx.AsyncBaseTransport | None,
        dns_resolver: DnsResolver,
    ) -> None:
        self._config = config
        self._secrets = dict(secrets)
        self._trust_profile = trust_profile
        self._http_transport = http_transport
        self._dns_resolver = dns_resolver
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._pinned_address: str | None = None
        self._initialized = False
        self._credential_headers = _render_header_templates(config, secrets)

    async def start(self) -> None:
        if self._config.url is None:
            raise _runtime_error("mcp_url_invalid", "network")
        addresses = await self._validate_target()
        parsed = urlsplit(self._config.url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        self._pinned_address = min(
            addresses,
            key=lambda value: (
                ipaddress.ip_address(value).version,
                int(ipaddress.ip_address(value)),
            ),
        )
        transport = self._http_transport or _PinnedAsyncHttpTransport(
            self._trust_profile,
            expected_host=host,
            pinned_address=self._pinned_address,
        )
        self._client = httpx.AsyncClient(
            verify=self._trust_profile.ssl_context,
            timeout=httpx.Timeout(self._config.timeout_seconds),
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    async def request_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        response, response_headers = await self._post(payload)
        if payload.get("method") == "initialize":
            session_id = response_headers.get("MCP-Session-Id")
            if session_id is not None:
                self._session_id = _validate_session_id(session_id)
            self._initialized = True
        if response is None:
            raise _runtime_error("mcp_response_invalid", "transport")
        return response

    async def send_notification(self, payload: Mapping[str, Any]) -> None:
        await self._post(payload, notification=True)

    async def close(self) -> None:
        client = self._client
        if client is None:
            return
        if self._session_id is not None and self._config.url is not None:
            headers = self._request_headers()
            try:
                before = await self._validate_pinned_target()
                response = await client.delete(self._config.url, headers=headers)
                if 300 <= response.status_code < 400:
                    raise _runtime_error("mcp_redirect_forbidden", "network")
                await self._validate_target(expected_addresses=before)
            except (httpx.HTTPError, McpRuntimeError):
                pass
        await client.aclose()

    async def _post(
        self, payload: Mapping[str, Any], *, notification: bool = False
    ) -> tuple[dict[str, Any] | None, httpx.Headers]:
        client = self._client
        if client is None or self._config.url is None:
            raise _runtime_error("mcp_http_unavailable", "network")
        before = await self._validate_pinned_target()
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(encoded) > _MAX_MESSAGE_BYTES:
            raise _runtime_error("mcp_message_too_large", "transport")
        try:
            async with client.stream(
                "POST",
                self._config.url,
                content=encoded,
                headers=self._request_headers(),
            ) as response:
                if 300 <= response.status_code < 400:
                    raise _runtime_error("mcp_redirect_forbidden", "network")
                if response.status_code >= 400:
                    raise _runtime_error(
                        "mcp_http_error",
                        "network",
                        retryable=response.status_code >= 500,
                    )
                response_headers = httpx.Headers(response.headers)
                if notification and response.status_code == 202:
                    decoded = None
                else:
                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";", 1)[0]
                        .strip()
                        .casefold()
                    )
                    if content_type == "application/json":
                        decoded = await _read_json_response(response)
                    elif content_type == "text/event-stream":
                        decoded = await _read_sse_response(
                            response,
                            expected_id=payload.get("id"),
                            notification=notification,
                        )
                    else:
                        raise _runtime_error("mcp_content_type_invalid", "transport")
        except McpRuntimeError:
            raise
        except httpx.HTTPError as exc:
            raise _runtime_error(
                "mcp_network_error", "network", retryable=True
            ) from exc
        await self._validate_target(expected_addresses=before)
        return decoded, response_headers

    async def _validate_pinned_target(self) -> set[str]:
        addresses = await self._validate_target()
        if self._pinned_address is None or self._pinned_address not in addresses:
            raise _runtime_error("mcp_dns_rebinding_detected", "network")
        return addresses

    def _request_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **self._credential_headers,
        }
        if self._initialized:
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        if self._session_id is not None:
            headers["MCP-Session-Id"] = self._session_id
        return headers

    async def _validate_target(
        self, *, expected_addresses: set[str] | None = None
    ) -> set[str]:
        if self._config.url is None:
            raise _runtime_error("mcp_url_invalid", "network")
        parsed = urlsplit(self._config.url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if (
            parsed.scheme.casefold() != "https"
            or not host
            or host not in self._config.allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(ord(character) < 32 for character in self._config.url)
        ):
            raise _runtime_error("mcp_target_forbidden", "network")
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise _runtime_error("mcp_target_forbidden", "network") from exc
        try:
            resolved = self._dns_resolver(host, port)
            addresses = (
                await cast(Awaitable[set[str]], resolved)
                if inspect.isawaitable(resolved)
                else resolved
            )
        except (OSError, ValueError) as exc:
            raise _runtime_error("mcp_dns_failed", "network") from exc
        if not addresses:
            raise _runtime_error("mcp_dns_failed", "network")
        normalized: set[str] = set()
        for raw_address in addresses:
            try:
                address = ipaddress.ip_address(raw_address)
            except ValueError as exc:
                raise _runtime_error("mcp_target_forbidden", "network") from exc
            if not _runtime_address_allowed(address, self._config.allowed_ip_ranges):
                raise _runtime_error("mcp_target_forbidden", "network")
            normalized.add(str(address))
        if expected_addresses is not None and normalized != expected_addresses:
            raise _runtime_error("mcp_dns_rebinding_detected", "network")
        return normalized


async def _read_json_response(response: httpx.Response) -> dict[str, Any]:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > _MAX_MESSAGE_BYTES:
            raise _runtime_error("mcp_message_too_large", "transport")
        chunks.append(chunk)
    try:
        decoded = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _runtime_error("mcp_response_invalid", "transport") from exc
    if not isinstance(decoded, dict):
        raise _runtime_error("mcp_response_invalid", "transport")
    return decoded


async def _read_sse_response(
    response: httpx.Response,
    *,
    expected_id: Any,
    notification: bool,
) -> dict[str, Any]:
    data_lines: list[str] = []
    size = 0
    async for line in response.aiter_lines():
        size += len(line.encode("utf-8")) + 1
        if size > _MAX_MESSAGE_BYTES:
            raise _runtime_error("mcp_message_too_large", "transport")
        if line:
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
            continue
        decoded = _decode_sse_data(data_lines)
        data_lines = []
        if decoded is not None and (notification or decoded.get("id") == expected_id):
            return decoded
    decoded = _decode_sse_data(data_lines)
    if decoded is not None and (notification or decoded.get("id") == expected_id):
        return decoded
    raise _runtime_error("mcp_response_invalid", "transport")


def _decode_sse_data(data_lines: Sequence[str]) -> dict[str, Any] | None:
    if not data_lines:
        return None
    value = "\n".join(data_lines)
    if value == "[DONE]":
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise _runtime_error("mcp_response_invalid", "transport") from exc
    return decoded if isinstance(decoded, dict) else None


def _validate_session_id(value: str) -> str:
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise _runtime_error("mcp_session_invalid", "transport") from exc
    if (
        not encoded
        or len(encoded) > _MAX_SESSION_ID_BYTES
        or any(byte < 0x21 or byte > 0x7E for byte in encoded)
    ):
        raise _runtime_error("mcp_session_invalid", "transport")
    return value


async def _resolve_host(host: str, port: int) -> set[str]:
    rows = await asyncio.to_thread(
        socket.getaddrinfo, host, port, type=socket.SOCK_STREAM
    )
    return {str(row[4][0]) for row in rows}


def _runtime_address_allowed(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allowed_ip_ranges: Sequence[str],
) -> bool:
    if (
        address.is_unspecified
        or address.is_link_local
        or address.is_multicast
        or (address.is_reserved and not address.is_loopback)
    ):
        return False
    if address.is_global:
        return True
    if not (address.is_private or address.is_loopback):
        return False
    for raw_network in allowed_ip_ranges:
        try:
            network = ipaddress.ip_network(raw_network, strict=True)
        except ValueError as exc:
            raise _runtime_error("mcp_target_forbidden", "network") from exc
        if not _runtime_network_is_approvable(network):
            raise _runtime_error("mcp_target_forbidden", "network")
        if address.version == network.version and address in network:
            return True
    return False


def _runtime_network_is_approvable(
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> bool:
    if isinstance(network, ipaddress.IPv4Network):
        return any(
            isinstance(parent, ipaddress.IPv4Network) and network.subnet_of(parent)
            for parent in APPROVABLE_PRIVATE_NETWORKS
        )
    return any(
        isinstance(parent, ipaddress.IPv6Network) and network.subnet_of(parent)
        for parent in APPROVABLE_PRIVATE_NETWORKS
    )


async def _discard_stderr(stream: asyncio.StreamReader) -> None:
    while await stream.read(8192):
        pass


def _validate_runtime_command(command: Sequence[str]) -> None:
    if not command:
        raise _runtime_error("mcp_command_invalid", "transport")
    executable = command[0].casefold()
    if "/" in executable or "\\" in executable:
        raise _runtime_error("mcp_command_not_allowed", "transport")
    if executable.endswith(".exe"):
        executable = executable[:-4]
    if executable not in ALLOWED_STDIO_EXECUTABLES:
        raise _runtime_error("mcp_command_not_allowed", "transport")
    for argument in command:
        folded = argument.casefold()
        if (
            not argument
            or len(argument) > 500
            or any(character in argument for character in ("\x00", "\r", "\n"))
            or "${" in argument
            or "authorization=" in folded
            or "api_key=" in folded
            or "api-key=" in folded
            or "token=" in folded
            or "password=" in folded
        ):
            raise _runtime_error("mcp_command_invalid", "transport")


def _environment_value(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if value or os.name != "nt":
        return value
    folded_name = name.casefold()
    return next(
        (value for key, value in environment.items() if key.casefold() == folded_name),
        "",
    )


def _resolve_stdio_command(command: Sequence[str]) -> tuple[str, ...]:
    if os.name != "nt" or command[0].casefold().removesuffix(".exe") != "npx":
        return tuple(command)
    executable = shutil.which(command[0])
    if executable is None or Path(executable).suffix.casefold() not in {".cmd", ".bat"}:
        return tuple(command)
    npx_cli = Path(executable).parent / "node_modules" / "npm" / "bin" / "npx-cli.js"
    if not npx_cli.is_file():
        raise _runtime_error("mcp_process_start_failed", "network")
    return ("node", str(npx_cli), *command[1:])


def _render_header_templates(
    config: McpServerConfig, secrets: Mapping[str, str]
) -> dict[str, str]:
    rendered: dict[str, str] = {}
    for name, template in config.header_templates.items():
        if name not in ALLOWED_SECRET_HEADER_NAMES.values():
            raise _runtime_error("mcp_header_template_invalid", "credential")
        expected_pattern = (
            r"(?:Bearer )?\$\{([A-Z][A-Z0-9_]*)\}"
            if name == "Authorization"
            else r"\$\{([A-Z][A-Z0-9_]*)\}"
        )
        if re.fullmatch(expected_pattern, template) is None:
            raise _runtime_error("mcp_header_template_invalid", "credential")
        value = template
        for secret_name, secret_value in secrets.items():
            value = value.replace(f"${{{secret_name}}}", secret_value)
        if (
            "${" in value
            or any(character in value for character in ("\x00", "\r", "\n"))
            or len(value) > 8192
        ):
            raise _runtime_error("mcp_header_template_invalid", "credential")
        rendered[name] = value
    if (
        set(config.required_secret_names)
        != {
            placeholder
            for template in config.header_templates.values()
            for placeholder in re.findall(r"\$\{([A-Z][A-Z0-9_]*)\}", template)
        }
        and config.transport == "streamable_http"
    ):
        raise _runtime_error("mcp_header_template_invalid", "credential")
    return rendered


def _normalize_negotiated_tool(raw_tool: Any) -> dict[str, Any]:
    if not isinstance(raw_tool, dict):
        raise _runtime_error("mcp_tool_schema_invalid", "schema")
    name = raw_tool.get("name")
    input_schema = raw_tool.get("inputSchema")
    if (
        not isinstance(name, str)
        or not _TOOL_NAME_RE.fullmatch(name)
        or not isinstance(input_schema, dict)
        or input_schema.get("type", "object") != "object"
    ):
        raise _runtime_error("mcp_tool_schema_invalid", "schema")
    return {
        "name": name,
        "description": str(raw_tool.get("description", ""))[:2000],
        "inputSchema": input_schema,
    }


def _intersect_tools(
    config: McpServerConfig, negotiated_tools: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    declared = {
        str(tool.get("name")): tool
        for tool in config.declared_tools
        if isinstance(tool, Mapping) and tool.get("name")
    }
    negotiated = {str(tool.get("name")): tool for tool in negotiated_tools}
    selected: list[dict[str, Any]] = []
    for name in config.tool_allowlist:
        expected = declared.get(name)
        actual = negotiated.get(name)
        if expected is None or actual is None:
            raise _runtime_error("mcp_tool_schema_drift", "schema")
        expected_schema = expected.get("inputSchema", {"type": "object"})
        actual_schema = actual.get("inputSchema", {"type": "object"})
        if _canonical_json(expected_schema) != _canonical_json(actual_schema):
            raise _runtime_error("mcp_tool_schema_drift", "schema")
        selected.append(
            {
                "name": name,
                "description": str(expected.get("description", ""))[:2000],
                "inputSchema": expected_schema,
            }
        )
    return selected


def _provider_tool_name(config: McpServerConfig, tool_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", config.slug)[:20] or "server"
    tool = re.sub(r"[^A-Za-z0-9_-]", "_", tool_name)[:18] or "tool"
    tool_digest = hashlib.sha256(tool_name.encode("utf-8")).hexdigest()[:6]
    return f"mcp__{slug}__{tool}__{tool_digest}__{config.digest[:8]}"


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise _runtime_error("mcp_tool_schema_invalid", "schema") from exc


def _redact_value(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value, secrets=secrets)
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_value(item, secrets) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_sensitive_text(str(value), secrets=secrets)


def _mcp_error_detail(value: Any, *, secrets: tuple[str, ...] = ()) -> str:
    redacted = _redact_value(value, secrets)
    if isinstance(redacted, (dict, list)):
        rendered = json.dumps(
            redacted,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        rendered = str(redacted)
    return redact_sensitive_text(rendered, secrets=secrets)[:1500]


__all__ = [
    "McpRuntime",
    "McpRuntimeError",
    "McpServerConfig",
    "PreparedMcpTool",
    "PROTOCOL_VERSION",
    "load_pinned_server_configs",
]
