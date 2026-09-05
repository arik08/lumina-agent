import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "extensions/skills/skill-evaluator/scripts/skill_lint.py"
spec = importlib.util.spec_from_file_location("skill_lint", SCRIPT)
assert spec and spec.loader
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)


def evaluate(tmp_path: Path, fields: str):
    (tmp_path / "SKILL.md").write_text(
        "---\nname: example-skill\n"
        "description: Use when examining a portable skill package for compatibility and preserving its required source metadata.\n"
        + fields + "\n---\n\n# Example\n",
        encoding="utf-8",
    )
    return lint.lint_skill(tmp_path)


def test_accepts_optional_fields_and_preserves_mcp_source(tmp_path):
    result = evaluate(tmp_path, 'license: MIT\ncompatibility: Python 3.12\nallowed-tools: Read\nmetadata:\n  lumina-source: skill-mcp:example')
    assert result["verdict"] == "ready", result
    assert "lumina-source: skill-mcp:example" in (tmp_path / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("fields", ["metadata: null", "metadata: []", "metadata:\n  version: 1", "license: []", "allowed-tools: false", "compatibility: " + "x" * 501])
def test_rejects_invalid_optional_field_types(tmp_path, fields):
    assert evaluate(tmp_path, fields)["verdict"] == "needs changes"


def test_unknown_client_extension_requires_review(tmp_path):
    result = evaluate(tmp_path, "client-extra: true")
    assert any("nonstandard keys: client-extra" in item["message"] for item in result["findings"])
