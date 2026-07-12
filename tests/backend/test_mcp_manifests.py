from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPOSITORY_ROOT / "extensions" / "mcp"
SENSITIVE_ENV_MARKERS = ("API_KEY", "PASSWORD", "SECRET", "TOKEN")


def test_mcp_manifests_use_portable_repository_relative_paths() -> None:
    for manifest_path in sorted(MCP_ROOT.glob("*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for server_name, server in manifest["mcpServers"].items():
            assert server.get("cwd") == ".", f"{manifest_path.name}:{server_name}"
            for argument in server.get("args", []):
                assert not PureWindowsPath(argument).is_absolute(), (
                    f"{manifest_path.name}:{server_name} has an absolute Windows path"
                )
                assert not PurePosixPath(argument).is_absolute(), (
                    f"{manifest_path.name}:{server_name} has an absolute POSIX path"
                )
                assert not argument.startswith(".mcp/"), (
                    f"{manifest_path.name}:{server_name} uses the obsolete .mcp path"
                )
                if argument.endswith(".py"):
                    assert (REPOSITORY_ROOT / argument).is_file(), (
                        f"{manifest_path.name}:{server_name} references a missing script"
                    )


def test_mcp_manifests_do_not_store_literal_secrets() -> None:
    for manifest_path in sorted(MCP_ROOT.glob("*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for server_name, server in manifest["mcpServers"].items():
            for name in server.get("env", {}):
                assert not any(marker in name.upper() for marker in SENSITIVE_ENV_MARKERS), (
                    f"{manifest_path.name}:{server_name} stores {name} in the manifest"
                )
