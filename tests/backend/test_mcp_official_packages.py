from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest
import httpx

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


@pytest.mark.parametrize("package_name", sorted(EXPECTED_TOOLS))
def test_health_failure_reports_http_status_without_secret(
    package_name: str,
) -> None:
    module = _load_server(package_name)

    def probe() -> None:
        response = httpx.Response(
            429,
            request=httpx.Request("GET", "https://example.com/?api_key=fixture-secret"),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError("wrapped fixture-secret") from exc

    result = json.loads(
        module.checked_health_envelope(
            source="fixture", probe=probe, success_detail="ok"
        )
    )
    assert result["ok"] is False
    assert result["detail"] == "Official endpoint probe failed (HTTP 429)."
    assert "fixture-secret" not in json.dumps(result)


def test_adb_legacy_dataflows_use_v5_and_keep_bounded_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_server("development-finance")
    requests = []

    def request(source, url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(200, content=b"TIME_PERIOD,OBS_VALUE\n2024,123\n")

    monkeypatch.setattr(module, "request", request)
    monkeypatch.setattr(
        module,
        "request_json",
        lambda source, url, **kwargs: requests.append((url, kwargs)) or [],
    )
    module.search_catalog("adb_kidb", "PPL_POP")
    assert requests[-1][0].endswith("/dataflow/indicators/DF_PPSI")
    result = json.loads(
        module.query_series("adb_kidb", "EO_NA", "NGDP_XDC", "PHI", 2024, 2024)
    )
    assert requests[-1][0].endswith("/v5/sdmx/data/ADB,DF_NA/A.NGDP_XDC.PHI")
    assert requests[-1][1]["params"]["startPeriod"] == 2024
    assert result["data"][0]["OBS_VALUE"] == "123"
    with pytest.raises(ValueError, match="50 years"):
        module.query_series("adb_kidb", "DF_NA", "NGDP_XDC", "PHI", 1950, 2024)


def test_semantic_scholar_requires_key_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_server("patent-tech")
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    requests = []
    monkeypatch.setattr(
        module,
        "request_json",
        lambda *args, **kwargs: requests.append(kwargs) or {"data": []},
    )
    result = json.loads(module.get_source_health("semantic_scholar"))
    assert result["ok"] is False
    assert requests == []
    with pytest.raises(ValueError, match="기업용 API KEY 신청이 필요합니다"):
        module.search_records("semantic_scholar", "steel")
    with pytest.raises(ValueError, match="기업용 API KEY 신청이 필요합니다"):
        module.get_record("semantic_scholar", "P1")
    assert requests == []
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "fixture-secret")
    result = module.get_source_health("semantic_scholar")
    assert requests[-1]["headers"] == {"x-api-key": "fixture-secret"}
    assert "fixture-secret" not in result



def test_semantic_scholar_rate_limit_is_not_missing_key(monkeypatch):
    module = _load_server("patent-tech")
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "fixture-secret")
    def limited(*args, **kwargs):
        response = httpx.Response(429, request=httpx.Request("GET", "https://example.com"))
        response.raise_for_status()
    monkeypatch.setattr(module, "request_json", limited)
    result = module.get_source_health("semantic_scholar")
    assert json.loads(result)["ok"] is False
    assert "429" in result
    assert "기업용 API KEY" not in result
    assert "fixture-secret" not in result


def test_crossref_remains_keyless(monkeypatch):
    module = _load_server("patent-tech")
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("CROSSREF_MAILTO", raising=False)
    monkeypatch.setattr(module, "request_json", lambda *args, **kwargs: {"message": {"items": []}})
    assert json.loads(module.get_source_health("crossref"))["ok"] is True


def _load_server(package_name: str) -> ModuleType:
    runtime_dir = MCP_ROOT / package_name / "runtime"
    module_name = f"lumina_mcp_{package_name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(
        module_name, runtime_dir / "server.py"
    )
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
    by_name = {tool.name: tool for tool in runtime_tools}
    for declared in server_config["tools"]:
        assert declared["inputSchema"] == by_name[declared["name"]].inputSchema
        source_schema = declared["inputSchema"].get("properties", {}).get("source")
        if source_schema:
            assert source_schema["enum"] == list(module.SOURCES)


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
