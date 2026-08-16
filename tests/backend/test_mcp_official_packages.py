from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from lumina.config import Settings
from lumina.mcp.runtime import McpRuntime, McpServerConfig


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPOSITORY_ROOT / "extensions" / "mcp"
EXPECTED_TOOLS = {
    "company-disclosure": {
        "search_catalog",
        "search_records",
        "get_record",
        "get_document_link",
        "get_source_health",
    },
    "development-finance": {"search_catalog", "query_series", "get_source_health"},
    "environment-industry": {
        "search_catalog",
        "query_industry",
        "search_facilities",
        "get_source_health",
    },
    "legislation-regulation": {
        "search_catalog",
        "search_records",
        "get_record",
        "get_document_link",
        "get_source_health",
    },
    "macro-finance": {"search_catalog", "query_series", "get_source_health"},
    "patent-tech": {
        "search_catalog",
        "search_records",
        "get_record",
        "get_source_health",
    },
    "trade-market": {"search_catalog", "query_trade", "get_source_health"},
}


def _load_server(package_name: str) -> ModuleType:
    runtime_dir = MCP_ROOT / package_name / "runtime"
    module_name = f"lumina_mcp_{package_name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, runtime_dir / "server.py")
    assert spec is not None and spec.loader is not None
    sys.path.insert(0, str(runtime_dir))
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(runtime_dir))
        sys.modules.pop(module_name, None)
        sys.modules.pop("official_data", None)


@pytest.mark.parametrize("package_name", sorted(EXPECTED_TOOLS))
def test_official_data_package_runtime_tools_match_pinned_manifests(
    package_name: str,
) -> None:
    package_root = MCP_ROOT / package_name
    manifest = json.loads((package_root / "mcp.json").read_text(encoding="utf-8"))
    server_config = manifest["mcpServers"][package_name]
    assert server_config["command"] == "python"
    assert server_config["args"] == ["runtime/server.py"]
    assert (package_root / "runtime" / "official_data.py").is_file()

    module = _load_server(package_name)
    runtime_tools = asyncio.run(module.server.list_tools())
    runtime_tool_names = {tool.name for tool in runtime_tools}
    manifest_tool_names = {tool["name"] for tool in server_config["tools"]}

    assert runtime_tool_names == EXPECTED_TOOLS[package_name]
    assert manifest_tool_names == runtime_tool_names


@pytest.mark.asyncio
async def test_official_data_packages_complete_stdio_tools_list_without_network(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        database_url=f"sqlite:///{(tmp_path / 'mcp.db').as_posix()}",
    )
    runtime = McpRuntime(
        settings,
        environment={
            "PATH": os.environ.get("PATH", ""),
            "PATHEXT": os.environ.get("PATHEXT", ""),
            "SystemRoot": os.environ.get("SystemRoot", ""),
        },
    )
    try:
        for package_name in sorted(EXPECTED_TOOLS):
            package_root = MCP_ROOT / package_name
            manifest = json.loads(
                (package_root / "mcp.json").read_text(encoding="utf-8")
            )
            server_config = manifest["mcpServers"][package_name]
            declared_tools = tuple(server_config["tools"])
            config = McpServerConfig(
                definition_id=f"test-{package_name}",
                installation_id=f"test-{package_name}",
                configuration_revision_id="test-revision",
                digest="a" * 64,
                slug=package_name,
                transport="stdio",
                command=(
                    "python",
                    str((package_root / "runtime" / "server.py").resolve()),
                ),
                url=None,
                allowed_hosts=(),
                allowed_ip_ranges=(),
                header_templates={},
                declared_tools=declared_tools,
                tool_allowlist=tuple(tool["name"] for tool in declared_tools),
                required_secret_names=(),
                secret_refs={},
                timeout_seconds=15.0,
            )
            tools = await runtime.prepare_servers((config,))
            assert {tool.original_name for tool in tools} == EXPECTED_TOOLS[package_name]
    finally:
        await runtime.close()
