from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPOSITORY_ROOT / "extensions" / "skills" / "idea-orchestrator"


def test_idea_orchestrator_routes_and_synthesizes_methods() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "name: idea-orchestrator" in skill
    assert "select two or three complementary methods" in skill
    assert "Never run every method by default" in skill
    assert "Apply each selected method independently" in skill
    assert "Merge duplicates" in skill
    assert "small reversible experiment" in skill


def test_idea_orchestrator_upstream_files_match_pinned_digests() -> None:
    references = SKILL_ROOT / "references"
    manifest = json.loads(
        (references / "upstream-sources.json").read_text(encoding="utf-8")
    )

    assert manifest["repository"] == "https://github.com/neurofoo/agent-skills"
    assert len(manifest["revision"]) == 40
    assert manifest["license"] == "MIT"
    assert manifest["files"]

    for entry in manifest["files"]:
        target = references / entry["target"]
        assert target.is_file()
        assert target.name.startswith("upstream-")
        assert hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"]


def test_idea_orchestrator_has_catalog_and_ui_metadata() -> None:
    catalog = json.loads(
        (REPOSITORY_ROOT / "extensions" / "skills" / "catalog.json").read_text(
            encoding="utf-8"
        )
    )
    interface = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert catalog["idea-orchestrator"]["tags"] == ["경영기획", "아이디어"]
    assert "TRIZ" in catalog["idea-orchestrator"]["description"]
    assert 'display_name: "Idea Orchestrator"' in interface
    assert "Use $idea-orchestrator" in interface
