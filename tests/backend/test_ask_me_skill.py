from __future__ import annotations

import json
from pathlib import Path

from lumina.agent.executor import (
    _MAX_USER_INPUT_QUESTIONS,
    _REQUEST_USER_INPUT_TOOL_SCHEMA,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPOSITORY_ROOT / "extensions" / "skills"


def test_ask_me_uses_the_existing_question_ui_without_over_questioning() -> None:
    skill = (SKILL_ROOT / "ask-me" / "SKILL.md").read_text(encoding="utf-8")

    assert "name: ask-me" in skill
    assert "Call `request_user_input` by itself" in skill
    assert "Normally ask one question" in skill
    assert "prefer no more than three" in skill
    assert "Never exceed ten questions" in skill
    assert " (추천)" in skill
    assert "Never place a user-facing question in ordinary response text" in skill
    assert "If no Blocking item remains" in skill


def test_ask_me_has_repository_catalog_metadata() -> None:
    descriptions = json.loads(
        (SKILL_ROOT / "catalog.ko.json").read_text(encoding="utf-8")
    )
    tags = json.loads(
        (SKILL_ROOT / "catalog.tags.json").read_text(encoding="utf-8")
    )

    assert descriptions["ask-me"].startswith("작업을 실행하기 전에")
    assert tags["ask-me"] == ["Agent", "업무설계"]


def test_ask_me_is_explicitly_invoked() -> None:
    interface = (SKILL_ROOT / "ask-me" / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )

    assert 'display_name: "Ask Me"' in interface
    assert "allow_implicit_invocation: false" in interface
    assert "Use $ask-me" in interface


def test_request_user_input_allows_up_to_ten_questions() -> None:
    questions_schema = _REQUEST_USER_INPUT_TOOL_SCHEMA["function"]["parameters"][
        "properties"
    ]["questions"]

    assert _MAX_USER_INPUT_QUESTIONS == 10
    assert questions_schema["minItems"] == 1
    assert questions_schema["maxItems"] == _MAX_USER_INPUT_QUESTIONS
