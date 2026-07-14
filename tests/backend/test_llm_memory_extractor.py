import json

from lumina.agent.executor import _InlineMemoryStream
from lumina.memories.service import memory_candidates_from_inline_json


def test_inline_memory_json_accepts_general_durable_facts_as_concise_sentences() -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "category": "user_identity",
                    "fact": "사용자 고향은 서산입니다.",
                    "confidence": 0.96,
                    "conflictKey": "user_hometown",
                },
                {
                    "category": "communication_preference",
                    "fact": "답변은 간결한 형식을 선호합니다.",
                    "confidence": 0.94,
                    "conflictKey": "response_detail",
                },
            ]
        },
        ensure_ascii=False,
    )

    candidates = memory_candidates_from_inline_json(
        payload,
        source_message_ids=("message-1",),
    )

    assert [candidate.display_text for candidate in candidates] == [
        "사용자 고향은 서산입니다.",
        "답변은 간결한 형식을 선호합니다.",
    ]
    assert all(candidate.fact == candidate.display_text for candidate in candidates)
    assert all(candidate.source_message_ids == ("message-1",) for candidate in candidates)


def test_inline_memory_json_rejects_malformed_or_unrecognized_rows() -> None:
    assert memory_candidates_from_inline_json(
        "not-json", source_message_ids=("message-1",)
    ) == ()
    assert memory_candidates_from_inline_json(
        json.dumps(
            {
                "candidates": [
                    {
                        "category": "unknown",
                        "fact": "저장하면 안 됩니다.",
                        "confidence": 0.9,
                        "conflictKey": None,
                    },
                    {
                        "category": "recurring_rule",
                        "fact": "신뢰도 형식이 잘못되었습니다.",
                        "confidence": "high",
                        "conflictKey": None,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        source_message_ids=("message-1",),
    ) == ()


def test_inline_memory_stream_hides_json_across_arbitrary_chunk_boundaries() -> None:
    stream = _InlineMemoryStream()
    chunks = (
        "확인했습니다.\n<lum",
        "ina_memory>{\"candidates\":[{\"category\":\"user_role\",",
        "\"fact\":\"사용자 역할은 제품 관리자입니다.\",",
        "\"confidence\":0.93,\"conflictKey\":\"user_role\"}]}",
        "</lumina_memory>",
    )

    visible = "".join(stream.feed(chunk) for chunk in chunks) + stream.finish()

    assert visible == "확인했습니다.\n"
    assert stream.payload is not None
    assert json.loads(stream.payload)["candidates"][0]["category"] == "user_role"


def test_inline_memory_stream_preserves_plain_responses_without_envelope() -> None:
    stream = _InlineMemoryStream()

    visible = stream.feed("일반 답변입니다.<lum") + stream.finish()

    assert visible == "일반 답변입니다.<lum"
    assert stream.payload is None
