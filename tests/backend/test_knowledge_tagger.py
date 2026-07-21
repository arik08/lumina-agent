from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from lumina.knowledge.tagger import (
    DocumentTagInput,
    ExistingTagCandidate,
    MAX_TAG_SCOPE_NOTE_CHARACTERS,
    NewTagSuggestion,
    suggest_document_tag_batch,
)
from lumina.providers.types import ProviderEvent, ProviderRequest


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


@pytest.mark.asyncio
async def test_multiple_documents_are_tagged_in_one_provider_request() -> None:
    class RecordingProvider:
        def __init__(self) -> None:
            self.requests: list[ProviderRequest] = []

        async def stream(self, request: ProviderRequest):
            self.requests.append(request)
            yield ProviderEvent(
                type="text_delta",
                text=json.dumps(
                    {
                        "documents": [
                            {
                                "documentIndex": 1,
                                "candidateIndexes": [0],
                                "newTags": [],
                            },
                            {
                                "documentIndex": 0,
                                "candidateIndexes": [],
                                "newTags": [
                                    {
                                        "canonicalName": "검색 증강 생성",
                                        "scopeNote": "외부 지식 검색을 결합한 생성 방식",
                                        "aliases": ["RAG"],
                                    }
                                ],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
            )

    provider = RecordingProvider()
    suggestions = await suggest_document_tag_batch(
        provider=provider,  # type: ignore[arg-type]
        model="mock-agent",
        documents=(
            DocumentTagInput(title="RAG 설계", body="검색 결과를 답변에 연결합니다."),
            DocumentTagInput(title="배치 처리", body="여러 문서를 한 번에 처리합니다."),
        ),
        candidates=[
            ExistingTagCandidate(
                id="internal-tag-id",
                canonical_name="배치 처리",
                scope_note="여러 입력을 묶는 처리 방식",
                aliases=("batch",),
            )
        ],
    )

    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.max_output_tokens == 1_400
    assert request.metadata["purpose"] == "knowledge_document_batch_tagging"
    assert request.messages[1].content is not None
    assert request.messages[1].content.count('"candidateIndex": 0') == 1
    assert "internal-tag-id" not in request.messages[1].content
    assert suggestions[0].new_tags[0].canonical_name == "검색 증강 생성"
    assert suggestions[1].tag_ids == ("internal-tag-id",)
