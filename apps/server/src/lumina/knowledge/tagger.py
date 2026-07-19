from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..providers.types import ProviderAdapter, ProviderMessage, ProviderRequest


MAX_DOCUMENT_TAGS = 5
MAX_TAG_INPUT_CHARACTERS = 16_000
MAX_TAG_SCOPE_NOTE_CHARACTERS = 40


class NewTagSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str = Field(alias="canonicalName", min_length=1, max_length=160)
    scope_note: str = Field(
        alias="scopeNote", min_length=1, max_length=MAX_TAG_SCOPE_NOTE_CHARACTERS
    )
    aliases: list[str] = Field(default_factory=list, max_length=8)


class _TagPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_ids: list[str] = Field(alias="tagIds", max_length=MAX_DOCUMENT_TAGS)
    new_tags: list[NewTagSuggestion] = Field(
        alias="newTags", max_length=MAX_DOCUMENT_TAGS
    )


@dataclass(frozen=True, slots=True)
class ExistingTagCandidate:
    id: str
    canonical_name: str
    scope_note: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentTagSuggestion:
    tag_ids: tuple[str, ...]
    new_tags: tuple[NewTagSuggestion, ...]


def _response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "knowledge_document_tags",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "tagIds": {
                        "type": "array",
                        "maxItems": MAX_DOCUMENT_TAGS,
                        "items": {"type": "string"},
                    },
                    "newTags": {
                        "type": "array",
                        "maxItems": MAX_DOCUMENT_TAGS,
                        "items": {
                            "type": "object",
                            "properties": {
                                "canonicalName": {"type": "string"},
                                "scopeNote": {
                                    "type": "string",
                                    "maxLength": MAX_TAG_SCOPE_NOTE_CHARACTERS,
                                },
                                "aliases": {
                                    "type": "array",
                                    "maxItems": 8,
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["canonicalName", "scopeNote", "aliases"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["tagIds", "newTags"],
                "additionalProperties": False,
            },
        },
    }


async def suggest_document_tags(
    *,
    provider: ProviderAdapter,
    model: str,
    title: str,
    body: str,
    candidates: list[ExistingTagCandidate],
) -> DocumentTagSuggestion:
    candidate_payload = [
        {
            "id": item.id,
            "canonicalName": item.canonical_name,
            "scopeNote": item.scope_note,
            "aliases": list(item.aliases),
        }
        for item in candidates[:40]
    ]
    prompt = (
        "Assign 2 to 5 concise topic tags to this Korean knowledge document. "
        "Reuse candidate tag IDs whenever their scope matches. Treat spelling variants, "
        "translations, and abbreviations as aliases of one tag. Do not merge homonyms or "
        "broader/narrower concepts. Propose a new tag only when no candidate fits; give it "
        "a short Korean canonical name, a Korean scope note of at most 40 characters "
        "that only disambiguates the tag (not a dictionary definition or summary), "
        "and useful aliases. "
        "Do not return generic tags such as knowledge, document, research, or answer.\n\n"
        f"Title: {title}\nCandidates: "
        f"{json.dumps(candidate_payload, ensure_ascii=False)}\nDocument:\n"
        f"{body[:MAX_TAG_INPUT_CHARACTERS]}"
    )
    chunks: list[str] = []
    async for event in provider.stream(
        ProviderRequest(
            model=model,
            messages=(
                ProviderMessage(
                    role="system",
                    content="Return only canonical document tags in the strict JSON schema.",
                ),
                ProviderMessage(role="user", content=prompt),
            ),
            response_format=_response_format(),
            max_output_tokens=700,
            temperature=0,
            metadata={"purpose": "knowledge_document_tagging"},
        )
    ):
        if event.type == "text_delta" and event.text:
            chunks.append(event.text)
    try:
        payload = _TagPayload.model_validate_json("".join(chunks).strip())
    except ValidationError as exc:
        raise ValueError("Provider returned invalid Knowledge tag JSON") from exc
    return DocumentTagSuggestion(
        tag_ids=tuple(dict.fromkeys(payload.tag_ids)),
        new_tags=tuple(payload.new_tags),
    )


__all__ = [
    "DocumentTagSuggestion",
    "ExistingTagCandidate",
    "MAX_DOCUMENT_TAGS",
    "MAX_TAG_SCOPE_NOTE_CHARACTERS",
    "NewTagSuggestion",
    "suggest_document_tags",
]
