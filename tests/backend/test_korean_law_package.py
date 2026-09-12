"""Runtime and routing regression checks for the Korean Law MCP package."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_prepare_runtime_installs_once_and_refreshes_changed_lock(
    tmp_path, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "bootstrap_prepare", ROOT / "extensions/mcp/korean-law/runtime/bootstrap.py"
    )
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    lock = tmp_path / "package-lock.json"
    lock.write_text("first", encoding="utf-8")
    calls = []

    def install(args, **kwargs):
        calls.append((args, kwargs))
        entry = tmp_path / "node_modules/korean-law-mcp/build/index.js"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("", encoding="utf-8")

    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "npm")
    monkeypatch.setattr(bootstrap.subprocess, "run", install)
    monkeypatch.setattr(bootstrap, "apply_compatibility_patch", lambda runtime: None)
    bootstrap.prepare_runtime(tmp_path)
    bootstrap.prepare_runtime(tmp_path)
    assert len(calls) == 1
    assert calls[0][1]["cwd"] == tmp_path
    assert calls[0][0][1] == "ci"
    lock.write_text("changed", encoding="utf-8")
    bootstrap.prepare_runtime(tmp_path)
    assert len(calls) == 2


def test_korean_law_runtime_uses_fixed_upstream_release() -> None:
    package = json.loads(
        (ROOT / "extensions/mcp/korean-law/runtime/package.json").read_text(
            encoding="utf-8"
        )
    )

    assert package["dependencies"]["korean-law-mcp"] == "4.9.7"


def test_korean_law_bootstrap_patches_exact_name_selection(tmp_path: Path) -> None:
    bootstrap_path = ROOT / "extensions/mcp/korean-law/runtime/bootstrap.py"
    spec = importlib.util.spec_from_file_location(
        "korean_law_bootstrap", bootstrap_path
    )
    assert spec and spec.loader
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)

    build = tmp_path / "node_modules/korean-law-mcp/build/tools"
    build.mkdir(parents=True)
    search = build / "search.js"
    search.write_text(
        "let xmlText = await apiClient.searchLaw(input.query, input.apiKey, input.display);",
        encoding="utf-8",
    )
    annex = build / "annex.js"
    annex.write_text(
        "    // 쿼리에서 단어 추출\n"
        "    const queryWords = queryName.split(/\\s+/).filter((w) => w.length > 0);",
        encoding="utf-8",
    )
    # Minimal unpatched v4.9.7 anchors for the API/penalty compatibility fixes.
    (build.parent / "lib").mkdir()
    (build / "scenarios").mkdir()
    (build.parent / "lib/api-client.js").write_text(
        '            target: "eflaw",', encoding="utf-8"
    )
    (build / "law-text.js").write_text(
        "    jo: z.string().optional().describe(\n"
        "${input.efYd || 'current'}`;\n"
        "        if (articleUnits.length === 0) {\n"
        "        if (!input.jo && articleUnits.length > 20) {",
        encoding="utf-8",
    )
    (build / "scenarios/penalty.js").write_text(
        '            search: "벌칙",', encoding="utf-8"
    )

    bootstrap.apply_compatibility_patch(tmp_path)
    bootstrap.apply_compatibility_patch(tmp_path)

    assert "Math.max(input.display, 50)" in search.read_text(encoding="utf-8")
    patched_annex = annex.read_text(encoding="utf-8")
    assert "const exact = annexList.filter" in patched_annex
    assert "=== queryKey" in patched_annex
    assert "부분 LIKE 오탐" in patched_annex


def test_law_text_uses_valid_endpoint_and_returns_filtered_article_bodies() -> None:
    """Exercise the installed JS with a fake HTTP response, including cache reuse."""
    import subprocess

    runtime = ROOT / "extensions/mcp/korean-law/runtime"
    spec = importlib.util.spec_from_file_location(
        "law_bootstrap_contract", runtime / "bootstrap.py"
    )
    assert spec and spec.loader
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    if not (runtime / "node_modules/korean-law-mcp/build/index.js").is_file():
        pytest.skip("Run installer to prepare Korean Law runtime")
    script = r"""
import assert from 'node:assert/strict';
import {LawApiClient} from './lib/api-client.js';
import {getLawText} from './tools/law-text.js';
const urls = [];
globalThis.fetch = async url => {
    urls.push(new URL(url));
    const units = Array.from({length: 25}, (_, i) => ({
        조문여부: '조문', 조문번호: String(i + 1),
        조문제목: i === 24 ? '과징금' : '일반 사항',
        조문내용: i === 24 ? '원문 과징금 근거' : '일반 본문',
    }));
    return new Response(JSON.stringify({법령: {기본정보: {법령명_한글: '시험법'}, 조문: {조문단위: units}}}));
};
const api = new LawApiClient({apiKey: 'fixture'});
const toc = await getLawText(api, {mst: '123'});
assert.match(toc.content[0].text, /목차/);
assert.equal(urls[0].searchParams.get('target'), 'law');
const filtered = await getLawText(api, {mst: '123', search: '벌칙 과태료 과징금'});
assert.equal(filtered.isError, undefined);
assert.match(filtered.content[0].text, /원문 과징금 근거/);
assert.doesNotMatch(filtered.content[0].text, /일반 본문|목차/);
await api.getLawText({mst: '123', efYd: '20250101'});
assert.equal(urls.at(-1).searchParams.get('target'), 'eflaw');
assert.equal(urls.at(-1).searchParams.get('efYd'), '20250101');
await api.getLawText({lawId: '456'});
assert.equal(urls.at(-1).searchParams.get('target'), 'eflaw');
console.log('PASS');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=runtime / "node_modules/korean-law-mcp/build",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_prepare_runtime_passes_offline_to_npm(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "bootstrap_offline", ROOT / "extensions/mcp/korean-law/runtime/bootstrap.py"
    )
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    (tmp_path / "package-lock.json").write_text("offline", encoding="utf-8")
    calls = []

    def install(args, **kwargs):
        calls.append(args)
        (tmp_path / "node_modules").mkdir()

    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "npm")
    monkeypatch.setattr(bootstrap.subprocess, "run", install)
    monkeypatch.setattr(bootstrap, "apply_compatibility_patch", lambda runtime: None)
    bootstrap.prepare_runtime(tmp_path, offline=True)
    assert "--offline" in calls[0]


@pytest.mark.parametrize("installed", [False, True])
def test_startup_never_installs_or_patches_missing_or_stale_runtime(
    tmp_path, monkeypatch, installed
):
    spec = importlib.util.spec_from_file_location(
        "bootstrap_start", ROOT / "extensions/mcp/korean-law/runtime/bootstrap.py"
    )
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    (tmp_path / "package-lock.json").write_text("changed", encoding="utf-8")
    if installed:
        entry = tmp_path / "node_modules/korean-law-mcp/build/index.js"
        entry.parent.mkdir(parents=True)
        entry.write_text("", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "RUNTIME", tmp_path)
    monkeypatch.setattr(bootstrap.sys, "argv", ["bootstrap.py"])

    def forbidden(*args, **kwargs):
        pytest.fail("startup attempted installation, patching, or process execution")

    monkeypatch.setattr(bootstrap, "prepare_runtime", forbidden)
    monkeypatch.setattr(bootstrap, "apply_compatibility_patch", forbidden)
    monkeypatch.setattr(bootstrap.subprocess, "call", forbidden)
    with pytest.raises(RuntimeError, match="installer.bat"):
        bootstrap.main()


@pytest.mark.asyncio
async def test_korean_law_lumina_runtime_matches_pinned_tools(tmp_path):
    import os
    from lumina.config import Settings
    from lumina.mcp.runtime import McpRuntime, McpServerConfig

    package = ROOT / "extensions/mcp/korean-law"
    if not (package / "runtime/node_modules/korean-law-mcp/build/index.js").is_file():
        pytest.skip("Run installer to prepare Korean Law runtime")
    raw = json.loads((package / "mcp.json").read_text(encoding="utf-8"))["mcpServers"][
        "korean-law"
    ]
    runtime = McpRuntime(
        Settings(
            environment="test",
            data_dir=tmp_path,
            files_dir=tmp_path / "files",
            artifacts_dir=tmp_path / "artifacts",
            database_url="sqlite://",
        ),
        environment={
            name: os.environ.get(name, "") for name in ("PATH", "PATHEXT", "SystemRoot")
        },
    )
    config = McpServerConfig(
        definition_id="test",
        installation_id="test",
        configuration_revision_id="test",
        digest="a" * 64,
        slug="korean-law",
        transport="stdio",
        command=("python", str(package / "runtime/bootstrap.py")),
        url=None,
        allowed_hosts=(),
        allowed_ip_ranges=(),
        header_templates={},
        declared_tools=tuple(raw["tools"]),
        tool_allowlist=tuple(tool["name"] for tool in raw["tools"]),
        required_secret_names=(),
        secret_refs={},
        timeout_seconds=15,
    )
    try:
        tools = await runtime.prepare_servers((config,))
        assert {tool.original_name for tool in tools} == {
            tool["name"] for tool in raw["tools"]
        }
        assert len(tools) == 10
    finally:
        await runtime.close()


def test_installer_prepares_mcp_only_in_dependency_stage():
    source = (ROOT / "devtools/install_lumina.ps1").read_text(encoding="utf-8")
    dependency_stage = source[
        source.index(
            'Write-Host "[Lumina] Installing frontend dependencies'
        ) : source.index('Write-Host "[Lumina] Applying database migrations')
    ]
    assert "extensions/mcp/korean-law/runtime/bootstrap.py" in dependency_stage
    assert '"--prepare"' in dependency_stage
    assert 'if ($NoNetwork) { $mcpArguments += "--offline" }' in dependency_stage
