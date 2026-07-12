from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any


_NUMBERED_MARKER_RE = re.compile(
    r"\[(?P<bracket>\d{1,2})\]|【(?P<corner>\d{1,2})】|"
    r"\[source:(?P<source>[A-Za-z0-9][A-Za-z0-9._:-]{0,159})\]"
)
_CIRCLED_ORDINALS = {
    marker: index for index, marker in enumerate("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳", start=1)
}


def resolve_inline_citations(
    text: str, sources: Sequence[Mapping[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Resolve only explicit answer markers against immutable source IDs.

    The resolver never invents a citation for an unmarked claim. Sources that were
    consulted but not explicitly cited remain visible as ``reference_only``.
    """

    normalized_sources: list[dict[str, Any]] = []
    source_by_id: dict[str, dict[str, Any]] = {}
    for ordinal, raw_source in enumerate(sources, start=1):
        source = dict(raw_source)
        source_id = str(source.get("sourceId") or "").strip()
        if not source_id or source_id in source_by_id:
            continue
        source["citationOrdinal"] = ordinal
        source["citationStatus"] = "reference_only"
        normalized_sources.append(source)
        source_by_id[source_id] = source

    occurrences: list[tuple[int, int, str, str]] = []
    for match in _NUMBERED_MARKER_RE.finditer(text):
        explicit_source_id = match.group("source")
        if explicit_source_id is not None:
            source_id = explicit_source_id
        else:
            raw_ordinal = match.group("bracket") or match.group("corner") or "0"
            source_id = _source_id_at(normalized_sources, int(raw_ordinal))
        if source_id in source_by_id:
            occurrences.append((match.start(), match.end(), match.group(0), source_id))
    for position, marker in enumerate(text):
        circled_ordinal = _CIRCLED_ORDINALS.get(marker)
        if circled_ordinal is None:
            continue
        source_id = _source_id_at(normalized_sources, circled_ordinal)
        if source_id in source_by_id:
            occurrences.append((position, position + 1, marker, source_id))

    citations: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()
    for start, end, marker, source_id in sorted(occurrences):
        if (start, end) in seen_spans:
            continue
        seen_spans.add((start, end))
        source = source_by_id[source_id]
        source["citationStatus"] = "cited"
        citation_id = hashlib.sha256(
            f"{source_id}:{start}:{end}:{marker}".encode("utf-8")
        ).hexdigest()[:24]
        citations.append(
            {
                "citationId": citation_id,
                "sourceId": source_id,
                "sourceOrdinal": source["citationOrdinal"],
                "marker": marker,
                "charStart": start,
                "charEnd": end,
                "status": "resolved",
            }
        )

    return {"citations": citations, "sources": normalized_sources}


def _source_id_at(sources: Sequence[Mapping[str, Any]], ordinal: int) -> str:
    if ordinal < 1 or ordinal > len(sources):
        return ""
    return str(sources[ordinal - 1].get("sourceId") or "")


__all__ = ["resolve_inline_citations"]
