from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from lumina.extensions.agent_skill_spec import parse_agent_skill
from lumina.mcp.service import normalize_slug


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPOSITORY_ROOT / "extensions" / "mcp"
SKILL_ROOT = REPOSITORY_ROOT / "extensions" / "skills"
SENSITIVE_ENV_MARKERS = ("API_KEY", "PASSWORD", "SECRET", "TOKEN")


def _package_roots() -> list[Path]:
    return sorted(
        path
        for path in MCP_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith((".", "__"))
    )


def _manifest_paths() -> list[Path]:
    return [package_root / "mcp.json" for package_root in _package_roots()]


def test_mcp_root_contains_only_self_contained_packages() -> None:
    package_roots = _package_roots()
    assert package_roots
    assert not [path for path in MCP_ROOT.iterdir() if path.is_file()]

    catalog = json.loads((SKILL_ROOT / "catalog.json").read_text(encoding="utf-8"))
    packaged_skill_names: set[str] = set()
    server_names: set[str] = set()
    for package_root in package_roots:
        manifest_path = package_root / "mcp.json"
        assert manifest_path.is_file(), f"Missing package manifest: {package_root}"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        servers = manifest.get("mcpServers", {})
        assert len(servers) == 1, f"Each package owns one MCP server: {manifest_path}"
        server_name = next(iter(servers))
        assert normalize_slug(server_name) == package_root.name
        assert server_name not in server_names
        server_names.add(server_name)

        skill_paths = sorted((package_root / "skills").glob("*/SKILL.md"))
        assert len(skill_paths) == 1, f"Each package owns one Skill wrapper: {package_root}"
        skill_path = skill_paths[0]
        document = parse_agent_skill(
            skill_path.read_text(encoding="utf-8"),
            expected_name=skill_path.parent.name,
        )
        assert normalize_slug(
            document.metadata.get("lumina-source", "").removeprefix("skill-mcp:")
        ) == normalize_slug(server_name)
        packaged_skill_names.add(document.name)

    assert not packaged_skill_names.intersection(catalog)

    standalone_wrappers = []
    for skill_path in SKILL_ROOT.glob("*/SKILL.md"):
        document = parse_agent_skill(
            skill_path.read_text(encoding="utf-8"),
            expected_name=skill_path.parent.name,
        )
        if document.metadata.get("lumina-source", "").startswith("skill-mcp:"):
            standalone_wrappers.append(skill_path)
    assert standalone_wrappers == []


def test_mcp_manifests_use_package_relative_runtime_paths() -> None:
    for manifest_path in _manifest_paths():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for server_name, server in manifest["mcpServers"].items():
            assert server.get("cwd") == ".", f"{manifest_path}:{server_name}"
            assert server.get("tools"), (
                f"{manifest_path}:{server_name} must pin runtime Tool schemas"
            )
            for argument in server.get("args", []):
                assert not PureWindowsPath(argument).is_absolute()
                assert not PurePosixPath(argument).is_absolute()
                assert not argument.startswith((".mcp/", "extensions/mcp/"))
                if argument.startswith("runtime/"):
                    target = (manifest_path.parent / argument).resolve()
                    target.relative_to(manifest_path.parent.resolve())
                    if argument.endswith(".py"):
                        assert target.is_file(), (
                            f"{manifest_path}:{server_name} references a missing script"
                        )


def test_mcp_manifests_do_not_store_literal_secrets() -> None:
    for manifest_path in _manifest_paths():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for server_name, server in manifest["mcpServers"].items():
            for name in server.get("env", {}):
                assert not any(
                    marker in name.upper() for marker in SENSITIVE_ENV_MARKERS
                ), f"{manifest_path}:{server_name} stores {name} in the manifest"


def test_korea_weather_keeps_its_required_secret_binding() -> None:
    required_by_server = {
        server_name: server.get("requiredSecretNames", [])
        for manifest_path in _manifest_paths()
        for server_name, server in json.loads(
            manifest_path.read_text(encoding="utf-8")
        )["mcpServers"].items()
    }

    assert required_by_server["korea-weather"] == ["KOREA_WEATHER_API_KEY"]


def test_national_assembly_full_profile_pins_every_runtime_tool() -> None:
    manifest = json.loads(
        (MCP_ROOT / "national-assembly" / "mcp.json").read_text(encoding="utf-8")
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
