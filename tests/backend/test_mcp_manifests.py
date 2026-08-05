from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from lumina.extensions.agent_skill_spec import parse_agent_skill


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPOSITORY_ROOT / "extensions" / "mcp"
SKILL_ROOT = REPOSITORY_ROOT / "extensions" / "skills"
SENSITIVE_ENV_MARKERS = ("API_KEY", "PASSWORD", "SECRET", "TOKEN")


def test_mcp_manifests_use_portable_repository_relative_paths() -> None:
    for manifest_path in sorted(MCP_ROOT.glob("*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for server_name, server in manifest["mcpServers"].items():
            assert server.get("cwd") == ".", f"{manifest_path.name}:{server_name}"
            assert server.get("tools"), (
                f"{manifest_path.name}:{server_name} must pin runtime Tool schemas"
            )
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
                assert not any(
                    marker in name.upper() for marker in SENSITIVE_ENV_MARKERS
                ), f"{manifest_path.name}:{server_name} stores {name} in the manifest"


def test_every_mcp_server_has_a_skill_wrapper() -> None:
    server_names = {
        server_name
        for manifest_path in MCP_ROOT.glob("*.json")
        for server_name in json.loads(manifest_path.read_text(encoding="utf-8"))[
            "mcpServers"
        ]
    }
    wrapped_names: list[str] = []
    for skill_path in SKILL_ROOT.glob("*/SKILL.md"):
        document = parse_agent_skill(
            skill_path.read_text(encoding="utf-8"),
            expected_name=skill_path.parent.name,
        )
        source = document.metadata.get("lumina-source", "")
        if source.startswith("skill-mcp:"):
            wrapped_names.append(source.removeprefix("skill-mcp:").strip())
    assert len(wrapped_names) == len(set(wrapped_names))
    assert set(wrapped_names) == server_names


def test_korea_weather_keeps_its_required_secret_binding() -> None:
    required_by_server = {
        server_name: server.get("requiredSecretNames", [])
        for manifest_path in MCP_ROOT.glob("*.json")
        for server_name, server in json.loads(
            manifest_path.read_text(encoding="utf-8")
        )["mcpServers"].items()
    }

    assert required_by_server["korea-weather"] == ["KOREA_WEATHER_API_KEY"]


def test_national_assembly_full_profile_pins_every_runtime_tool() -> None:
    manifest = json.loads(
        (MCP_ROOT / "national-assembly.json").read_text(encoding="utf-8")
    )
    server = manifest["mcpServers"]["national-assembly"]

    assert server["env"]["MCP_PROFILE"] == "full"
    assert {tool["name"] for tool in server["tools"]} == {
        "assembly_member",
        "assembly_bill",
        "assembly_session",
        "assembly_org",
        "discover_apis",
        "query_assembly",
        "bill_detail",
        "committee_detail",
        "petition_detail",
        "research_data",
        "get_nabo",
    }
