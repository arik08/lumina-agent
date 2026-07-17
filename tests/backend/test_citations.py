from lumina.citations import resolve_inline_citations


def _sources() -> list[dict[str, str]]:
    return [
        {"sourceId": "source-a", "title": "A", "normalizedUrl": "https://a.test"},
        {"sourceId": "source-b", "title": "B", "normalizedUrl": "https://b.test"},
        {"sourceId": "source-c", "title": "C", "normalizedUrl": "https://c.test"},
    ]


def test_resolves_explicit_markers_and_leaves_reference_only_sources() -> None:
    text = "첫 주장[1], 둘째 주장【2】, 다시 첫 근거 ①. 범위를 벗어난 표시는 [9]."
    payload = resolve_inline_citations(text, _sources())

    assert [item["sourceId"] for item in payload["citations"]] == [
        "source-a",
        "source-b",
        "source-a",
    ]
    assert [item["marker"] for item in payload["citations"]] == ["[1]", "【2】", "①"]
    assert {item["status"] for item in payload["citations"]} == {"cited"}
    assert [source["citationStatus"] for source in payload["sources"]] == [
        "cited",
        "cited",
        "reference_only",
    ]
    for citation in payload["citations"]:
        assert text[citation["charStart"] : citation["charEnd"]] == citation["marker"]


def test_resolves_source_id_marker_without_fabricating_unknown_source() -> None:
    payload = resolve_inline_citations(
        "확인됨[source:source-c], 알 수 없음[source:missing].", _sources()
    )

    assert len(payload["citations"]) == 1
    assert payload["citations"][0]["sourceId"] == "source-c"
    assert payload["sources"][2]["citationStatus"] == "cited"


def test_resolves_artifact_links_in_first_appearance_order() -> None:
    sources = _sources()
    sources[2]["normalizedUrl"] = "https://c.test/%EC%9E%90%EB%A3%8C"
    payload = resolve_inline_citations(
        "보고서를 생성했습니다.",
        sources,
        reference_texts=(
            """
            <h2>주요 참고자료</h2>
            https://c.test/자료&lt;br&gt;[2]
            [A 자료](https://a.test/)
            <a href="https://c.test/%EC%9E%90%EB%A3%8C?utm_source=report">C 자료 재인용</a>
            """,
        ),
    )

    assert [item["sourceId"] for item in payload["citations"]] == [
        "source-c",
        "source-a",
    ]
    assert [item["markerNumber"] for item in payload["citations"]] == [1, 2]
    assert {item["citationOrigin"] for item in payload["citations"]} == {
        "artifact_link"
    }
    assert [source["citationStatus"] for source in payload["sources"]] == [
        "cited",
        "reference_only",
        "cited",
    ]


def test_artifact_does_not_promote_unlinked_search_sources() -> None:
    payload = resolve_inline_citations(
        "보고서를 생성했습니다.",
        _sources(),
        reference_texts=("<p>링크 없이 검색 결과만 참고했습니다.</p>",),
    )

    assert payload["citations"] == []
    assert {source["citationStatus"] for source in payload["sources"]} == {
        "reference_only"
    }
