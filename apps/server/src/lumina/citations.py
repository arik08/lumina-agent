from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from html import unescape
from typing import Any
from unicodedata import normalize
from urllib.parse import unquote

from .tools.web import WebToolError, normalize_public_url


_NUMBERED_MARKER_RE = re.compile(
    r"\[(?P<bracket>\d{1,2})\]|【(?P<corner>\d{1,2})】|"
    r"\[source:(?P<source>[A-Za-z0-9][A-Za-z0-9._:-]{0,159})\]"
)
_PROVIDER_CITATION_RE = re.compile(
    r"\ue200cite(?P<body>(?:\ue202[A-Za-z0-9][A-Za-z0-9._:-]{0,159})+)\ue201",
    re.IGNORECASE,
)
_PROVIDER_CITATION_SOURCE_RE = re.compile(
    r"\ue202(?P<source>[A-Za-z0-9][A-Za-z0-9._:-]{0,159})"
)
_CIRCLED_ORDINALS = {
    marker: index for index, marker in enumerate("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳", start=1)
}
_ARTIFACT_URL_RE = re.compile(r"https?://[^\s<>\"'\]\)]+", re.IGNORECASE)


def normalize_provider_citation_tokens(
    text: str,
    sources: Sequence[Mapping[str, Any]],
) -> str:
    """Translate provider-private citation tokens into Lumina source markers."""

    known_source_ids = {
        str(source.get("sourceId") or "").strip() for source in sources
    }
    known_source_ids.discard("")

    def replace(match: re.Match[str]) -> str:
        source_ids = (
            source_match.group("source")
            for source_match in _PROVIDER_CITATION_SOURCE_RE.finditer(
                match.group("body")
            )
        )
        return "".join(
            f"[source:{source_id}]"
            for source_id in source_ids
            if source_id in known_source_ids
        )

    return _PROVIDER_CITATION_RE.sub(replace, text)


def resolve_inline_citations(
    text: str,
    sources: Sequence[Mapping[str, Any]],
    *,
    reference_texts: Sequence[str] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Resolve explicit answer markers and links used in generated text artifacts.

    Sources that were consulted but neither marked in the answer nor linked from a
    generated text artifact remain visible as ``reference_only``.
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

    occurrences: list[tuple[int, int, str, str, int]] = []
    for match in _NUMBERED_MARKER_RE.finditer(text):
        explicit_source_id = match.group("source")
        if explicit_source_id is not None:
            source_id = explicit_source_id
            marker_number = int(source_by_id.get(source_id, {}).get("citationOrdinal", 0))
        else:
            raw_ordinal = match.group("bracket") or match.group("corner") or "0"
            marker_number = int(raw_ordinal)
            source_id = _source_id_at(normalized_sources, marker_number)
        if source_id in source_by_id:
            occurrences.append(
                (match.start(), match.end(), match.group(0), source_id, marker_number)
            )
    for position, marker in enumerate(text):
        circled_ordinal = _CIRCLED_ORDINALS.get(marker)
        if circled_ordinal is None:
            continue
        source_id = _source_id_at(normalized_sources, circled_ordinal)
        if source_id in source_by_id:
            occurrences.append(
                (position, position + 1, marker, source_id, circled_ordinal)
            )
    for match in _PROVIDER_CITATION_RE.finditer(text):
        for source_match in _PROVIDER_CITATION_SOURCE_RE.finditer(
            match.group("body")
        ):
            source_id = source_match.group("source")
            source = source_by_id.get(source_id)
            if source is None:
                continue
            occurrences.append(
                (
                    match.start(),
                    match.end(),
                    match.group(0),
                    source_id,
                    int(source["citationOrdinal"]),
                )
            )

    citations: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int, str]] = set()
    cited_source_ids: set[str] = set()
    for start, end, marker, source_id, marker_number in sorted(occurrences):
        if (start, end, source_id) in seen_spans:
            continue
        seen_spans.add((start, end, source_id))
        source = source_by_id[source_id]
        source["citationStatus"] = "cited"
        cited_source_ids.add(source_id)
        citation_id = hashlib.sha256(
            f"{source_id}:{start}:{end}:{marker}".encode("utf-8")
        ).hexdigest()[:24]
        citations.append(
            {
                "citationId": citation_id,
                "sourceId": source_id,
                "sourceOrdinal": source["citationOrdinal"],
                "marker": marker,
                "markerNumber": marker_number,
                "charStart": start,
                "charEnd": end,
                "status": "cited",
            }
        )

    artifact_marker_number = len(cited_source_ids) + 1
    for document_index, position, source_id in _artifact_source_occurrences(
        reference_texts, normalized_sources
    ):
        if source_id in cited_source_ids:
            continue
        cited_source_ids.add(source_id)
        source = source_by_id[source_id]
        source["citationStatus"] = "cited"
        citation_id = hashlib.sha256(
            f"artifact:{source_id}:{document_index}:{position}".encode("utf-8")
        ).hexdigest()[:24]
        citations.append(
            {
                "citationId": citation_id,
                "sourceId": source_id,
                "sourceOrdinal": source["citationOrdinal"],
                "markerNumber": artifact_marker_number,
                "citationOrigin": "artifact_link",
                "status": "cited",
            }
        )
        artifact_marker_number += 1

    return {"citations": citations, "sources": normalized_sources}


def _artifact_source_occurrences(
    reference_texts: Sequence[str], sources: Sequence[Mapping[str, Any]]
) -> list[tuple[int, int, str]]:
    source_by_url: dict[str, str] = {}
    for source in sources:
        source_id = str(source.get("sourceId") or "")
        for key in ("normalizedUrl", "originalUrl"):
            candidate = str(source.get(key) or "").strip()
            if not candidate:
                continue
            try:
                source_by_url.setdefault(_url_match_key(candidate), source_id)
            except WebToolError:
                continue

    occurrences: list[tuple[int, int, str]] = []
    for document_index, document in enumerate(reference_texts):
        for match in _ARTIFACT_URL_RE.finditer(document):
            candidate = (
                unescape(match.group(0))
                .split("<", 1)[0]
                .rstrip(".,;:!?，。；：！？")
            )
            try:
                normalized_url = _url_match_key(candidate)
            except WebToolError:
                continue
            matched_source_id = source_by_url.get(normalized_url)
            if matched_source_id:
                occurrences.append((document_index, match.start(), matched_source_id))
    return occurrences


def _url_match_key(url: str) -> str:
    return normalize("NFC", unquote(normalize_public_url(url)))


def _source_id_at(sources: Sequence[Mapping[str, Any]], ordinal: int) -> str:
    if ordinal < 1 or ordinal > len(sources):
        return ""
    return str(sources[ordinal - 1].get("sourceId") or "")


__all__ = ["normalize_provider_citation_tokens", "resolve_inline_citations"]
