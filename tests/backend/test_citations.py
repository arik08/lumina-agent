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
