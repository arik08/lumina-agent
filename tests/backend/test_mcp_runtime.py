from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpcore
import httpx
import pytest

from lumina.config import Settings
from lumina.mcp.runtime import (
    McpRuntime,
    McpRuntimeError,
    McpServerConfig,
    _PinnedNetworkBackend,
    _environment_value,
    _resolve_stdio_command,
)


SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        database_url=f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}",
    )


def _stdio_config(tmp_path: Path, *, mode: str = "normal") -> McpServerConfig:
    server = Path(__file__).parents[1] / "fixtures" / "fake_mcp_server.py"
    return McpServerConfig(
        definition_id="definition-1",
        installation_id="installation-1",
        configuration_revision_id="revision-1",
        digest="a" * 64,
        slug="internal-docs",
        transport="stdio",
        command=("python", str(server.resolve()), mode, str(tmp_path / "mcp.log")),
        url=None,
        allowed_hosts=(),
        allowed_ip_ranges=(),
        header_templates={},
        declared_tools=(
            {"name": "echo", "description": "Echo", "inputSchema": SCHEMA},
            {"name": "not_allowed", "inputSchema": {"type": "object"}},
        ),
        tool_allowlist=("echo",),
        required_secret_names=("MCP_TEST_TOKEN",),
        secret_refs={"MCP_TEST_TOKEN": "env://SOURCE_TOKEN"},
        timeout_seconds=2.0,
    )


def _runtime_environment() -> dict[str, str]:
    names = (
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
    )
    return {
        **{name: os.environ[name] for name in names if name in os.environ},
        "SOURCE_TOKEN": "top-secret-value",
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows environment keys are case-insensitive")
def test_windows_environment_lookup_is_case_insensitive() -> None:
    assert _environment_value({"Path": "venv-path"}, "PATH") == "venv-path"


@pytest.mark.skipif(os.name != "nt", reason="npx uses a Windows command shim")
def test_windows_npx_command_uses_node_cli() -> None:
    resolved = _resolve_stdio_command(("npx", "-y", "example-mcp@1.0.0"))

    assert resolved[0] == "node"
    assert resolved[1].endswith("npx-cli.js")
    assert resolved[2:] == ("-y", "example-mcp@1.0.0")


@pytest.mark.asyncio
async def test_stdio_lifecycle_allowlist_call_and_secret_redaction(
    tmp_path: Path,
) -> None:
    runtime = McpRuntime(_settings(tmp_path), environment=_runtime_environment())
    tools = await runtime.prepare_servers((_stdio_config(tmp_path),))
    assert len(tools) == 1
    tool = tools[0]
    assert tool.original_name == "echo"
    assert tool.provider_name == "mcp__internal-docs__echo__092c79__aaaaaaaa"
    assert tool.provider_schema["function"]["parameters"] == SCHEMA

    result = await runtime.call_tool(tool, {"value": "hello"})
    encoded = json.dumps(result, ensure_ascii=False)
    assert "hello" in encoded
    assert "top-secret-value" not in encoded
    assert "[REDACTED]" in encoded
    assert (await runtime.prepare_servers((_stdio_config(tmp_path),)))[0] == tool

    methods = (tmp_path / "mcp.log").read_text(encoding="utf-8").splitlines()
    assert methods.count("initialize") == 1
    assert methods.count("notifications/initialized") == 1
    assert methods.count("tools/list") == 1
    assert methods.count("tools/call") == 1
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_code", "expected_detail"),
    (
        ("rpc_error", "mcp_jsonrpc_error", "Invalid parameter value"),
        ("tool_error", "mcp_tool_error", "echo=hello"),
    ),
)
async def test_stdio_tool_failures_preserve_safe_server_detail(
    tmp_path: Path,
    mode: str,
    expected_code: str,
    expected_detail: str,
) -> None:
    runtime = McpRuntime(_settings(tmp_path), environment=_runtime_environment())
    tool = (await runtime.prepare_servers((_stdio_config(tmp_path, mode=mode),)))[0]

    try:
        with pytest.raises(McpRuntimeError) as failure:
            await runtime.call_tool(tool, {"value": "hello"})

        assert failure.value.code == expected_code
        assert expected_detail in str(failure.value)
        assert "top-secret-value" not in str(failure.value)
        assert "[REDACTED]" in str(failure.value)
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_stdio_resolves_repository_relative_manifest_script(
    tmp_path: Path,
) -> None:
    config = _stdio_config(tmp_path)
    repository_root = Path(__file__).resolve().parents[2]
    relative_server = Path(config.command[1]).relative_to(repository_root)
    relative_config = replace(
        config,
        command=(config.command[0], relative_server.as_posix(), *config.command[2:]),
    )
    runtime = McpRuntime(_settings(tmp_path), environment=_runtime_environment())

    tools = await runtime.prepare_servers((relative_config,))

    assert [tool.original_name for tool in tools] == ["echo"]
    await runtime.close()


@pytest.mark.asyncio
async def test_stdio_rejects_schema_drift_and_unavailable_secret_resolver(
    tmp_path: Path,
) -> None:
    runtime = McpRuntime(_settings(tmp_path), environment=_runtime_environment())
    with pytest.raises(McpRuntimeError) as drift:
        await runtime.prepare_servers((_stdio_config(tmp_path, mode="drift"),))
    assert drift.value.code == "mcp_tool_schema_drift"

    config = _stdio_config(tmp_path)
    unavailable = replace(
        config,
        secret_refs={"MCP_TEST_TOKEN": "vault://users/alice/token"},
    )
    with pytest.raises(McpRuntimeError) as resolver:
        await runtime.prepare_servers((unavailable,))
    assert resolver.value.code == "mcp_secret_resolver_unavailable"
    assert "vault" not in str(resolver.value).casefold()


class _HangingSseStream(httpx.AsyncByteStream):
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.closed = False

    async def __aiter__(self):
        yield self.payload
        await asyncio.sleep(10)

    async def aclose(self) -> None:
        self.closed = True


class _HttpMcpServer:
    def __init__(
        self, *, delay_call: bool = False, hang_after_sse: bool = False
    ) -> None:
        self.delay_call = delay_call
        self.hang_after_sse = hang_after_sse
        self.messages: list[dict[str, Any]] = []
        self.headers: list[httpx.Headers] = []
        self.last_stream: _HangingSseStream | None = None

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(204)
        payload = json.loads(request.content)
        self.messages.append(payload)
        self.headers.append(request.headers)
        method = payload.get("method")
        if "id" not in payload:
            return httpx.Response(202)
        if method == "initialize":
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "MCP-Session-Id": "session-123",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mock", "version": "1"},
                    },
                },
            )
        if method == "tools/list":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Echo",
                                "inputSchema": SCHEMA,
                            },
                            {
                                "name": "not_allowed",
                                "inputSchema": {"type": "object"},
                            },
                        ]
                    },
                },
            )
        if self.delay_call:
            await asyncio.sleep(1)
        data = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "content": [{"type": "text", "text": "done"}],
                    "isError": False,
                },
            },
            separators=(",", ":"),
        )
        body = f"event: message\ndata: {data}\n\n"
        if self.hang_after_sse:
            self.last_stream = _HangingSseStream(body.encode())
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=self.last_stream,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=body,
        )


def _http_config(
    *,
    timeout_seconds: float = 1.0,
    allowed_ip_ranges: tuple[str, ...] = (),
) -> McpServerConfig:
    return McpServerConfig(
        definition_id="definition-http",
        installation_id="installation-http",
        configuration_revision_id="revision-http",
        digest="b" * 64,
        slug="http-docs",
        transport="streamable_http",
        command=(),
        url="https://mcp.example.test/v1/mcp",
        allowed_hosts=("mcp.example.test",),
        allowed_ip_ranges=allowed_ip_ranges,
        header_templates={"Authorization": "Bearer ${API_TOKEN}"},
        declared_tools=(
            {"name": "echo", "description": "Echo", "inputSchema": SCHEMA},
        ),
        tool_allowlist=("echo",),
        required_secret_names=("API_TOKEN",),
        secret_refs={"API_TOKEN": "env://HTTP_TOKEN"},
        timeout_seconds=timeout_seconds,
    )


async def _public_dns(_host: str, _port: int) -> set[str]:
    return {"8.8.8.8"}


@pytest.mark.asyncio
async def test_streamable_http_headers_session_sse_and_timeout_cancellation(
    tmp_path: Path,
) -> None:
    server = _HttpMcpServer(hang_after_sse=True)
    runtime = McpRuntime(
        _settings(tmp_path),
        http_transport=httpx.MockTransport(server),
        dns_resolver=_public_dns,
        environment={"HTTP_TOKEN": "http-secret"},
    )
    tool = (await runtime.prepare_servers((_http_config(),)))[0]
    result = await runtime.call_tool(tool, {"value": "ok"})
    assert result["content"] == [{"type": "text", "text": "done"}]
    assert server.last_stream is not None and server.last_stream.closed is True
    assert all(
        headers["authorization"] == "Bearer http-secret" for headers in server.headers
    )
    initialized_index = next(
        index
        for index, message in enumerate(server.messages)
        if message.get("method") == "notifications/initialized"
    )
    assert server.headers[initialized_index]["mcp-protocol-version"] == "2025-11-25"
    assert server.headers[initialized_index]["mcp-session-id"] == "session-123"
    assert (
        sum(message.get("method") == "initialize" for message in server.messages) == 1
    )
    assert (
        sum(message.get("method") == "tools/list" for message in server.messages) == 1
    )
    await runtime.close()

    delayed = _HttpMcpServer(delay_call=True)
    timeout_runtime = McpRuntime(
        _settings(tmp_path),
        http_transport=httpx.MockTransport(delayed),
        dns_resolver=_public_dns,
        environment={"HTTP_TOKEN": "http-secret"},
    )
    timeout_tool = (
        await timeout_runtime.prepare_servers((_http_config(timeout_seconds=0.03),))
    )[0]
    with pytest.raises(McpRuntimeError) as timeout:
        await timeout_runtime.call_tool(timeout_tool, {"value": "slow"})
    assert timeout.value.code == "mcp_timeout"
    assert any(
        message.get("method") == "notifications/cancelled"
        for message in delayed.messages
    )

    cancelled_server = _HttpMcpServer(delay_call=True)
    cancel_runtime = McpRuntime(
        _settings(tmp_path),
        http_transport=httpx.MockTransport(cancelled_server),
        dns_resolver=_public_dns,
        environment={"HTTP_TOKEN": "http-secret"},
    )
    cancel_tool = (
        await cancel_runtime.prepare_servers((_http_config(timeout_seconds=2.0),))
    )[0]
    task = asyncio.create_task(cancel_runtime.call_tool(cancel_tool, {"value": "stop"}))
    for _attempt in range(100):
        if any(
            message.get("method") == "tools/call"
            for message in cancelled_server.messages
        ):
            break
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(
        message.get("method") == "notifications/cancelled"
        for message in cancelled_server.messages
    )
    await timeout_runtime.close()
    await cancel_runtime.close()


@pytest.mark.asyncio
async def test_streamable_http_blocks_private_dns_before_network(
    tmp_path: Path,
) -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async def private_dns(_host: str, _port: int) -> set[str]:
        return {"127.0.0.1"}

    runtime = McpRuntime(
        _settings(tmp_path),
        http_transport=httpx.MockTransport(handler),
        dns_resolver=private_dns,
        environment={"HTTP_TOKEN": "http-secret"},
    )
    with pytest.raises(McpRuntimeError) as blocked:
        await runtime.prepare_servers((_http_config(),))
    assert blocked.value.code == "mcp_target_forbidden"
    assert calls == 0


class _RecordingNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.hosts: list[str] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del port, timeout, local_address, socket_options
        self.hosts.append(host)
        raise httpcore.ConnectError("test stop")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: object | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del path, timeout, socket_options
        raise AssertionError("Unix socket connection was not expected")

    async def sleep(self, seconds: float) -> None:
        del seconds


@pytest.mark.asyncio
async def test_pinned_network_backend_substitutes_only_the_socket_address() -> None:
    delegate = _RecordingNetworkBackend()
    backend = _PinnedNetworkBackend("mcp.example.test", "8.8.8.8", delegate=delegate)

    with pytest.raises(httpcore.ConnectError, match="test stop"):
        await backend.connect_tcp("mcp.example.test", 443)
    assert delegate.hosts == ["8.8.8.8"]

    with pytest.raises(httpcore.ConnectError, match="target changed"):
        await backend.connect_tcp("redirect.example.test", 443)
    assert delegate.hosts == ["8.8.8.8"]


@pytest.mark.asyncio
async def test_streamable_http_rebinds_before_request_without_network(
    tmp_path: Path,
) -> None:
    network_calls = 0
    dns_calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        return httpx.Response(500)

    async def rebinding_dns(_host: str, _port: int) -> set[str]:
        nonlocal dns_calls
        dns_calls += 1
        return {"8.8.8.8"} if dns_calls == 1 else {"1.1.1.1"}

    runtime = McpRuntime(
        _settings(tmp_path),
        http_transport=httpx.MockTransport(handler),
        dns_resolver=rebinding_dns,
        environment={"HTTP_TOKEN": "http-secret"},
    )
    with pytest.raises(McpRuntimeError) as rebinding:
        await runtime.prepare_servers((_http_config(),))
    assert rebinding.value.code == "mcp_dns_rebinding_detected"
    assert network_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("address", "allowed_range"),
    (("10.20.30.40", "10.0.0.0/8"), ("127.0.0.1", "127.0.0.0/8")),
)
async def test_streamable_http_allows_only_explicit_private_ranges(
    tmp_path: Path,
    address: str,
    allowed_range: str,
) -> None:
    server = _HttpMcpServer()

    async def corporate_dns(_host: str, _port: int) -> set[str]:
        return {address}

    runtime = McpRuntime(
        _settings(tmp_path),
        http_transport=httpx.MockTransport(server),
        dns_resolver=corporate_dns,
        environment={"HTTP_TOKEN": "http-secret"},
    )
    tools = await runtime.prepare_servers(
        (_http_config(allowed_ip_ranges=(allowed_range,)),)
    )
    assert len(tools) == 1
    assert server.messages[0]["method"] == "initialize"
    await runtime.close()


@pytest.mark.asyncio
async def test_streamable_http_rejects_link_local_even_if_runtime_config_lists_it(
    tmp_path: Path,
) -> None:
    async def link_local_dns(_host: str, _port: int) -> set[str]:
        return {"169.254.10.20"}

    runtime = McpRuntime(
        _settings(tmp_path),
        http_transport=httpx.MockTransport(_HttpMcpServer()),
        dns_resolver=link_local_dns,
        environment={"HTTP_TOKEN": "http-secret"},
    )
    with pytest.raises(McpRuntimeError) as blocked:
        await runtime.prepare_servers(
            (_http_config(allowed_ip_ranges=("169.254.0.0/16",)),)
        )
    assert blocked.value.code == "mcp_target_forbidden"
