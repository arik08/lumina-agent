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
    assert "normally no more than three" in skill
    assert "each independent fact or decision as its own question" in skill
    assert "Never combine several requested facts" in skill
    assert "every currently foreseeable high-value question in the first bundle" in skill
    assert "Do not intentionally split known questions" in skill
    assert "could not reasonably have been anticipated" in skill
    assert "ten total questions" in skill
    assert "Never repeat a resolved question" in skill
    assert "verify the result against that contract" in skill
    assert " (추천)" in skill
    assert "Never place a question in ordinary response text" in skill
    assert "If no Blocking item remains" in skill
    assert "requests personalized guidance without facts" in skill
    assert "Do not substitute a generic conditional checklist" in skill
    assert "Role-play framing or an assigned profession" in skill
    assert "Do not trigger intake for general knowledge" in skill
    assert "gives an underspecified search or retrieval request" in skill
    assert "Before using files, enterprise search, MCP, or web search" in skill
    assert "if the preceding conversation already identifies it" in skill


def test_ask_me_has_repository_catalog_metadata() -> None:
    catalog = json.loads((SKILL_ROOT / "catalog.json").read_text(encoding="utf-8"))

    assert catalog["ask-me"]["description"].startswith("기존 확인 질문 UI를 통해")
    assert catalog["ask-me"]["tags"] == ["Agent", "업무설계"]


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

    description = _REQUEST_USER_INPUT_TOOL_SCHEMA["function"]["description"]
    assert "exactly one fact or decision" in description
    assert "separate question items in the same bundle" in description
    assert "every currently foreseeable high-value question" in description
    assert "repeated submit-and-wait cycles" in description
    assert "could not reasonably have been anticipated" in description
