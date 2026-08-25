from __future__ import annotations

import json
from pathlib import Path

from lumina.agent.executor import (
    _MAX_USER_INPUT_QUESTIONS,
    _REQUEST_USER_INPUT_TOOL_SCHEMA,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPOSITORY_ROOT / "extensions" / "skills"
GENERAL_SKILL_ROOT = SKILL_ROOT / "General"


def test_grill_me_uses_the_existing_question_ui_with_a_per_round_cap() -> None:
    skill = (GENERAL_SKILL_ROOT / "grill-me" / "SKILL.md").read_text(encoding="utf-8")

    assert "name: grill-me" in skill
    assert "design tree" in skill
    assert "The frontier" in skill
    assert "Call `request_user_input` by itself" in skill
    assert "recommended answer first" in skill
    assert " (추천)" in skill
    assert "more than twenty questions in one question card" in skill
    assert "no cumulative question limit across the Run" in skill
    assert "stop as soon as the material tree is resolved" in skill
    assert "Never repeat a resolved question" in skill
    assert "Do not implement" in skill


def test_grill_me_has_repository_catalog_metadata_and_attribution() -> None:
    catalog = json.loads((SKILL_ROOT / "catalog.json").read_text(encoding="utf-8"))
    license_text = (GENERAL_SKILL_ROOT / "grill-me" / "LICENSE").read_text(
        encoding="utf-8"
    )

    assert "ask-me" not in catalog
    assert catalog["grill-me"]["description"].startswith("계획·결정·아이디어를")
    assert catalog["grill-me"]["tags"] == ["Agent", "업무설계"]
    assert "Copyright (c) 2026 Matt Pocock" in license_text
    assert "5b15a47f2d7150f545fbcacbfe381787fc0230dc" in license_text


def test_grill_me_is_explicitly_invoked() -> None:
    interface = (GENERAL_SKILL_ROOT / "grill-me" / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )

    assert 'display_name: "Grill Me"' in interface
    assert "allow_implicit_invocation: false" in interface
    assert "Use $grill-me" in interface


def test_request_user_input_limits_each_bundle_to_twenty_not_the_run() -> None:
    questions_schema = _REQUEST_USER_INPUT_TOOL_SCHEMA["function"]["parameters"][
        "properties"
    ]["questions"]
    description = _REQUEST_USER_INPUT_TOOL_SCHEMA["function"]["description"]

    assert _MAX_USER_INPUT_QUESTIONS == 20
    assert questions_schema["minItems"] == 1
    assert questions_schema["maxItems"] == _MAX_USER_INPUT_QUESTIONS
    assert "up to twenty questions" in description
    assert "no cumulative Run limit" in description
    assert "dependent decisions" in description
    assert "ten questions in total across the Run" not in description
