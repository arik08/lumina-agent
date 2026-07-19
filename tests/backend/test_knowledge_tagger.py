from __future__ import annotations

import pytest
from pydantic import ValidationError

from lumina.knowledge.tagger import (
    MAX_TAG_SCOPE_NOTE_CHARACTERS,
    NewTagSuggestion,
)


def test_new_tag_scope_note_is_limited_to_a_short_disambiguating_phrase() -> None:
    accepted = NewTagSuggestion.model_validate(
        {
            "canonicalName": "Java",
            "scopeNote": "프로그래밍 언어",
            "aliases": [],
        }
    )
    assert accepted.scope_note == "프로그래밍 언어"

    with pytest.raises(ValidationError):
        NewTagSuggestion.model_validate(
            {
                "canonicalName": "Java",
                "scopeNote": "가" * (MAX_TAG_SCOPE_NOTE_CHARACTERS + 1),
                "aliases": [],
            }
        )
