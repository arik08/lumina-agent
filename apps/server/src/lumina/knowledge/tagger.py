from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..providers.types import ProviderAdapter, ProviderMessage, ProviderRequest


MAX_DOCUMENT_TAGS = 5
MAX_TAG_BATCH_DOCUMENTS = 8
MAX_TAG_BATCH_INPUT_CHARACTERS = 48_000
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

    document_index: int = Field(alias="documentIndex", ge=0)
    candidate_indexes: list[int] = Field(
        alias="candidateIndexes", max_length=MAX_DOCUMENT_TAGS
    )
    new_tags: list[NewTagSuggestion] = Field(
        alias="newTags", max_length=MAX_DOCUMENT_TAGS
    )


class _TagBatchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[_TagPayload]


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


@dataclass(frozen=True, slots=True)
class DocumentTagInput:
    title: str
    body: str


def _response_format(*, document_count: int, candidate_count: int) -> dict[str, object]:
    candidate_index_schema: dict[str, object] = {
        "type": "integer",
        "minimum": 0,
    }
    if candidate_count:
        candidate_index_schema["maximum"] = candidate_count - 1
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "knowledge_document_tag_batch",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "documents": {
                        "type": "array",
                        "minItems": document_count,
                        "maxItems": document_count,
                        "items": {
                            "type": "object",
                            "properties": {
                                "documentIndex": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": document_count - 1,
                                },
                                "candidateIndexes": {
                                    "type": "array",
                                    "maxItems": MAX_DOCUMENT_TAGS,
                                    "items": candidate_index_schema,
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
                                        "required": [
                                            "canonicalName",
                                            "scopeNote",
                                            "aliases",
                                        ],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": [
                                "documentIndex",
                                "candidateIndexes",
                                "newTags",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["documents"],
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
    suggestions = await suggest_document_tag_batch(
        provider=provider,
        model=model,
        documents=(DocumentTagInput(title=title, body=body),),
        candidates=candidates,
    )
    return suggestions[0]


async def suggest_document_tag_batch(
    *,
    provider: ProviderAdapter,
    model: str,
    documents: tuple[DocumentTagInput, ...],
    candidates: list[ExistingTagCandidate],
) -> tuple[DocumentTagSuggestion, ...]:
    if not documents:
        return ()
    if len(documents) > MAX_TAG_BATCH_DOCUMENTS:
        raise ValueError(
            f"Knowledge tag batch exceeds {MAX_TAG_BATCH_DOCUMENTS} documents"
        )
    selected_candidates = candidates[:40]
    candidate_payload = [
        {
            "candidateIndex": index,
            "canonicalName": item.canonical_name,
            "scopeNote": item.scope_note,
            "aliases": list(item.aliases),
        }
        for index, item in enumerate(selected_candidates)
    ]
    document_payload = [
        {
            "documentIndex": index,
            "title": item.title,
            "body": item.body[:MAX_TAG_INPUT_CHARACTERS],
        }
        for index, item in enumerate(documents)
    ]
    prompt = (
        "Assign 2 to 5 concise topic tags independently to each Korean knowledge document. "
        "Return exactly one result for every documentIndex. Reuse candidate indexes "
        "whenever their scope matches. Treat spelling variants, "
        "translations, and abbreviations as aliases of one tag. Do not merge homonyms or "
        "broader/narrower concepts. Propose a new tag only when no candidate fits; give it "
        "a short Korean canonical name, a Korean scope note of at most 40 characters "
        "that only disambiguates the tag (not a dictionary definition or summary), "
        "and useful aliases. "
        "Do not return generic tags such as knowledge, document, research, or answer.\n\n"
        f"Candidates: {json.dumps(candidate_payload, ensure_ascii=False)}\n"
        f"Documents: {json.dumps(document_payload, ensure_ascii=False)}"
    )
    chunks: list[str] = []
    async for event in provider.stream(
        ProviderRequest(
            model=model,
            messages=(
                ProviderMessage(
                    role="system",
                    content=(
                        "Return only canonical document tags for every input document "
                        "in the strict JSON schema."
                    ),
                ),
                ProviderMessage(role="user", content=prompt),
            ),
            response_format=_response_format(
                document_count=len(documents),
                candidate_count=len(selected_candidates),
            ),
            max_output_tokens=700 * len(documents),
            temperature=0,
            metadata={"purpose": "knowledge_document_batch_tagging"},
        )
    ):
        if event.type == "text_delta" and event.text:
            chunks.append(event.text)
    try:
        payload = _TagBatchPayload.model_validate_json("".join(chunks).strip())
    except ValidationError as exc:
        raise ValueError("Provider returned invalid Knowledge tag JSON") from exc
    suggestions: list[DocumentTagSuggestion | None] = [None] * len(documents)
    for item in payload.documents:
        if item.document_index >= len(documents):
            raise ValueError("Provider returned an out-of-range document index")
        if suggestions[item.document_index] is not None:
            raise ValueError("Provider returned a duplicate document index")
        try:
            tag_ids = tuple(
                dict.fromkeys(
                    selected_candidates[index].id for index in item.candidate_indexes
                )
            )
        except IndexError as exc:
            raise ValueError(
                "Provider returned an out-of-range candidate index"
            ) from exc
        suggestions[item.document_index] = DocumentTagSuggestion(
            tag_ids=tag_ids,
            new_tags=tuple(item.new_tags),
        )
    if any(item is None for item in suggestions):
        raise ValueError("Provider omitted a document from the Knowledge tag batch")
    return tuple(item for item in suggestions if item is not None)


__all__ = [
    "DocumentTagSuggestion",
    "DocumentTagInput",
    "ExistingTagCandidate",
    "MAX_DOCUMENT_TAGS",
    "MAX_TAG_BATCH_DOCUMENTS",
    "MAX_TAG_BATCH_INPUT_CHARACTERS",
    "MAX_TAG_INPUT_CHARACTERS",
    "MAX_TAG_SCOPE_NOTE_CHARACTERS",
    "NewTagSuggestion",
    "suggest_document_tag_batch",
    "suggest_document_tags",
]
