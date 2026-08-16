from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPOSITORY_ROOT / "extensions" / "mcp"


def _load_module(name: str, package: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name, MCP_ROOT / package / "runtime" / filename
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ecos_requires_explicit_key_when_unconfigured(monkeypatch) -> None:
    ecos = _load_module("test_ecos_server", "ecos", "server.py")
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    monkeypatch.delenv("BOK_ECOS_API_KEY", raising=False)

    with pytest.raises(ValueError, match="ECOS_API_KEY"):
        ecos._api_key()


def test_eia_requires_explicit_key_when_unconfigured(monkeypatch) -> None:
    eia = _load_module("test_eia_server", "eia", "server.py")
    monkeypatch.delenv("EIA_API_KEY", raising=False)

    with pytest.raises(ValueError, match="EIA_API_KEY"):
        eia._api_key()


def test_configured_api_keys_override_public_defaults(monkeypatch) -> None:
    ecos = _load_module("test_ecos_server_override", "ecos", "server.py")
    eia = _load_module("test_eia_server_override", "eia", "server.py")
    monkeypatch.setenv("ECOS_API_KEY", "configured-ecos-key")
    monkeypatch.setenv("EIA_API_KEY", "configured-eia-key")

    assert ecos._api_key() == "configured-ecos-key"
    assert eia._api_key() == "configured-eia-key"


def test_national_assembly_bootstrap_does_not_embed_api_key() -> None:
    assembly = _load_module(
        "test_national_assembly_bootstrap", "national-assembly", "bootstrap.py"
    )

    assert not hasattr(assembly, "DEFAULT_ASSEMBLY_API_KEY")
