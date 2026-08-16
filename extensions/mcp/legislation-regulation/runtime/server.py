"""Official legislation and regulation MCP for the US, EU, and UK."""

from __future__ import annotations

import json
import re
from defusedxml import ElementTree as ET
from datetime import datetime
from functools import partial
from typing import Any

from mcp.server.fastmcp import FastMCP

from official_data import (
    checked_health_envelope,
    clean_limit,
    first_env,
    request,
    request_json,
    result_envelope,
    safe_identifier,
)


CONGRESS_BASE_URL = "https://api.congress.gov/v3"
FEDERAL_REGISTER_BASE_URL = "https://www.federalregister.gov/api/v1"
EP_BASE_URL = "https://data.europarl.europa.eu/api/v2"
CELLAR_BASE_URL = "https://publications.europa.eu/resource/celex"
UK_BILLS_BASE_URL = "https://bills-api.parliament.uk/api/v1"
UK_LEGISLATION_BASE_URL = "https://www.legislation.gov.uk"

SOURCES = {
    "congress": "U.S. Congress.gov API",
    "federal_register": "U.S. Federal Register API",
    "europarl": "European Parliament Open Data API",
    "eurlex": "EUR-Lex CELLAR dissemination API",
    "uk_bills": "UK Parliament Bills API",
    "uk_legislation": "legislation.gov.uk",
}

server = FastMCP("legislation-regulation")


def _source(source: str) -> str:
    key = source.strip().lower().replace("-", "_")
    aliases = {
        "federalregister": "federal_register",
        "ep": "europarl",
        "cellar": "eurlex",
        "uk_parliament": "uk_bills",
        "legislation_gov_uk": "uk_legislation",
    }
    key = aliases.get(key, key)
    if key not in SOURCES:
        raise ValueError(f"Unknown source {source!r}. Use one of: {', '.join(SOURCES)}")
    return key


def _congress_key() -> str:
    key = first_env("CONGRESS_API_KEY", "DATA_GOV_API_KEY")
    if not key:
        raise ValueError("CONGRESS_API_KEY or DATA_GOV_API_KEY is required for Congress.gov.")
    return key


def _congress_json(path: str, params: dict[str, Any] | None = None) -> object:
    return request_json(
        "Congress.gov",
        f"{CONGRESS_BASE_URL}/{path.lstrip('/')}",
        params={"api_key": _congress_key(), "format": "json", **(params or {})},
    )


def _ep_json(path: str, params: dict[str, Any] | None = None) -> object:
    return request_json(
        "European Parliament",
        f"{EP_BASE_URL}/{path.lstrip('/')}",
        params=params,
        headers={"Accept": "application/ld+json"},
        timeout=60,
    )


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _xml_summary(content: bytes, *, max_values: int = 250) -> dict[str, Any]:
    """Extract bounded text metadata from structured XML without returning document bodies."""
    root = ET.fromstring(content)
    values: dict[str, list[str]] = {}
    count = 0
    for element in root.iter():
        text = (element.text or "").strip()
        if not text or len(text) > 1000:
            continue
        key = _xml_local_name(element.tag)
        bucket = values.setdefault(key, [])
        if text not in bucket:
            bucket.append(text)
            count += 1
        if count >= max_values:
            break
    return {
        "root": _xml_local_name(root.tag),
        "values": values,
        "parsed_value_count": count,
        "response_bytes": len(content),
    }


def _uk_legislation_path(record_id: str) -> str:
    path = record_id.strip().strip("/")
    if not re.fullmatch(r"[a-z0-9-]+/\d{4}/\d+", path):
        raise ValueError("UK legislation record_id must look like ukpga/2025/18 or uksi/2026/336.")
    return path


def _celex(record_id: str) -> str:
    return safe_identifier(
        record_id.upper(),
        field_name="CELEX number",
        pattern=r"[0-9A-Z()._-]{5,40}",
    )


def _iso_date(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    token = value.strip()
    try:
        datetime.strptime(token, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD.") from exc
    return token


CONGRESS_WEB_BILL_TYPES = {
    "hr": "house-bill",
    "s": "senate-bill",
    "hjres": "house-joint-resolution",
    "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution",
    "sconres": "senate-concurrent-resolution",
    "hres": "house-resolution",
    "sres": "senate-resolution",
}


@server.tool()
def search_catalog(source: str, query: str = "", limit: int = 20) -> str:
    """Describe supported record types or list a small source-native catalog."""
    selected = _source(source)
    safe_limit = clean_limit(limit, maximum=100)
    if selected == "congress":
        payload = _congress_json("congress", {"limit": safe_limit})
        data: object = payload.get("congresses", []) if isinstance(payload, dict) else payload
        source_id = "congress"
    else:
        catalog = {
            "federal_register": ["rule", "proposed_rule", "notice", "presidential_document"],
            "europarl": ["procedures", "procedure events", "adopted texts", "documents"],
            "eurlex": ["CELEX identifier metadata", "CELLAR identifiers", "official viewer link"],
            "uk_bills": ["bills", "stages", "publications"],
            "uk_legislation": ["Acts", "Statutory Instruments", "structured XML", "Akoma Ntoso"],
        }[selected]
        needle = query.casefold().strip()
        data = [item for item in catalog if not needle or needle in item.casefold()][:safe_limit]
        source_id = "supported_record_types"
    return result_envelope(
        source=SOURCES[selected],
        source_id=source_id,
        data=data,
        completeness="bounded_catalog",
        license_name="Official source reuse terms",
    )


@server.tool()
def search_records(
    source: str,
    query: str = "",
    limit: int = 20,
    congress: int | None = None,
    bill_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Search official legislative or regulatory records using source-native filters."""
    selected = _source(source)
    safe_limit = clean_limit(limit, maximum=100)
    start_date = _iso_date(start_date, field_name="start_date")
    end_date = _iso_date(end_date, field_name="end_date")
    if start_date and end_date and end_date < start_date:
        raise ValueError("end_date must not be earlier than start_date.")
    if selected == "congress":
        path = "bill"
        if congress is not None:
            if not 1 <= int(congress) <= 999:
                raise ValueError("congress must be between 1 and 999.")
            path += f"/{int(congress)}"
            if bill_type:
                path += "/" + safe_identifier(
                    bill_type.lower(), field_name="bill_type", pattern=r"[a-z]{1,10}"
                )
        elif bill_type:
            raise ValueError("congress is required when bill_type is supplied.")
        payload = _congress_json(path, {"limit": safe_limit * 5})
        rows = payload.get("bills", []) if isinstance(payload, dict) else []
        needle = query.casefold().strip()
        data: object = [
            row
            for row in rows
            if isinstance(row, dict)
            and (
                not needle or needle in f"{row.get('title', '')} {row.get('number', '')}".casefold()
            )
        ][:safe_limit]
        source_id = path
        completeness = "latest_page_locally_filtered"
    elif selected == "federal_register":
        payload = request_json(
            "Federal Register",
            f"{FEDERAL_REGISTER_BASE_URL}/documents.json",
            params={
                "conditions[term]": query or None,
                "conditions[publication_date][gte]": start_date,
                "conditions[publication_date][lte]": end_date,
                "per_page": safe_limit,
                "order": "newest",
            },
        )
        data = payload.get("results", []) if isinstance(payload, dict) else payload
        source_id = "documents"
        completeness = "query_and_page_limited"
    elif selected == "europarl":
        payload = _ep_json("procedures", {"limit": min(safe_limit * 5, 100)})
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        needle = query.casefold().strip()
        data = [
            row
            for row in rows
            if isinstance(row, dict)
            and (not needle or needle in json.dumps(row, ensure_ascii=False).casefold())
        ][:safe_limit]
        source_id = "procedures"
        completeness = "latest_page_locally_filtered"
    elif selected == "eurlex":
        if not query:
            raise ValueError("EUR-Lex search requires an exact CELEX identifier.")
        celex = _celex(query)
        return get_record("eurlex", celex)
    elif selected == "uk_bills":
        payload = request_json(
            "UK Parliament Bills",
            f"{UK_BILLS_BASE_URL}/Bills",
            params={"SearchTerm": query or None, "Skip": 0, "Take": safe_limit},
        )
        data = payload.get("items", []) if isinstance(payload, dict) else payload
        source_id = "Bills"
        completeness = "query_and_page_limited"
    else:
        response = request(
            "legislation.gov.uk",
            f"{UK_LEGISLATION_BASE_URL}/all/data.feed",
            params={"title": query or None},
            headers={"Accept": "application/atom+xml"},
            timeout=60,
        )
        root = ET.fromstring(response.content)
        atom = {"a": "http://www.w3.org/2005/Atom"}
        rows = []
        for entry in root.findall("a:entry", atom)[:safe_limit]:
            links = [link.attrib for link in entry.findall("a:link", atom)]
            rows.append(
                {
                    "id": entry.findtext("a:id", default="", namespaces=atom),
                    "title": entry.findtext("a:title", default="", namespaces=atom),
                    "updated": entry.findtext("a:updated", default="", namespaces=atom),
                    "links": links,
                }
            )
        data = rows
        source_id = "all/data.feed"
        completeness = "query_and_feed_limited"
    return result_envelope(
        source=SOURCES[selected],
        source_id=source_id,
        data=data,
        as_of=end_date,
        revision="latest_returned_by_api",
        completeness=completeness,
        license_name="Official source reuse terms",
    )


@server.tool()
def get_record(source: str, record_id: str, record_type: str = "detail") -> str:
    """Get one record plus optional actions, events, stages, or publications."""
    selected = _source(source)
    kind = record_type.strip().lower()
    if selected == "congress":
        match = re.fullmatch(r"(\d{1,3})/([a-z]{1,10})/(\d{1,8})", record_id.strip().lower())
        if not match:
            raise ValueError("Congress record_id must look like 119/hr/1.")
        allowed = {
            "detail",
            "bill",
            "actions",
            "committees",
            "cosponsors",
            "subjects",
            "summaries",
            "text",
        }
        if kind not in allowed:
            raise ValueError(
                "Congress record_type must be detail, actions, committees, cosponsors, "
                "subjects, summaries, or text."
            )
        suffix = "" if kind in {"detail", "bill"} else f"/{kind}"
        path = f"bill/{match.group(1)}/{match.group(2)}/{match.group(3)}{suffix}"
        payload: object = _congress_json(path, {"limit": 250})
        source_id = path
    elif selected == "federal_register":
        if kind != "detail":
            raise ValueError("Federal Register record_type must be detail.")
        document_number = safe_identifier(
            record_id, field_name="document_number", pattern=r"[A-Za-z0-9-]{4,40}"
        )
        payload = request_json(
            "Federal Register",
            f"{FEDERAL_REGISTER_BASE_URL}/documents/{document_number}.json",
        )
        source_id = document_number
    elif selected == "europarl":
        if kind not in {"detail", "events"}:
            raise ValueError("European Parliament record_type must be detail or events.")
        process_id = safe_identifier(
            record_id, field_name="process_id", pattern=r"[A-Za-z0-9()_.-]{3,50}"
        )
        suffix = "/events" if kind == "events" else ""
        payload = _ep_json(f"procedures/{process_id}{suffix}")
        source_id = f"procedures/{process_id}{suffix}"
    elif selected == "eurlex":
        if kind != "detail":
            raise ValueError("EUR-Lex record_type must be detail.")
        celex = _celex(record_id)
        response = request(
            "EUR-Lex CELLAR",
            f"{CELLAR_BASE_URL}/{celex}",
            params={"language": "en"},
            headers={"Accept": "application/xml;notice=object"},
            timeout=90,
        )
        payload = _xml_summary(response.content)
        source_id = celex
    elif selected == "uk_bills":
        bill_id = safe_identifier(record_id, field_name="bill_id", pattern=r"\d{1,10}")
        suffixes = {"detail": "", "bill": "", "stages": "/Stages", "publications": "/Publications"}
        if kind not in suffixes:
            raise ValueError("UK Bills record_type must be detail, stages, or publications.")
        path = f"Bills/{bill_id}{suffixes[kind]}"
        payload = request_json("UK Parliament Bills", f"{UK_BILLS_BASE_URL}/{path}")
        source_id = path
    else:
        if kind != "detail":
            raise ValueError("UK legislation record_type must be detail.")
        path = _uk_legislation_path(record_id)
        response = request(
            "legislation.gov.uk",
            f"{UK_LEGISLATION_BASE_URL}/{path}/data.xml",
            headers={"Accept": "application/xml"},
            timeout=90,
        )
        payload = _xml_summary(response.content)
        source_id = path
    return result_envelope(
        source=SOURCES[selected],
        source_id=source_id,
        data=payload,
        revision="latest_returned_by_source",
        completeness="structured_metadata_no_pdf_or_ocr",
        license_name="Official source reuse terms",
    )


@server.tool()
def get_document_link(source: str, record_id: str) -> str:
    """Return an official HTML viewer link; never download or OCR PDFs."""
    selected = _source(source)
    if selected == "congress":
        match = re.fullmatch(r"(\d{1,3})/([a-z]{1,10})/(\d{1,8})", record_id.strip().lower())
        if not match:
            raise ValueError("Congress record_id must look like 119/hr/1.")
        bill_type = CONGRESS_WEB_BILL_TYPES.get(match.group(2))
        if not bill_type:
            raise ValueError("Unsupported Congress bill type for an official viewer link.")
        url = f"https://www.congress.gov/bill/{match.group(1)}th-congress/{bill_type}/{match.group(3)}"
    elif selected == "federal_register":
        number = safe_identifier(
            record_id, field_name="document_number", pattern=r"[A-Za-z0-9-]{4,40}"
        )
        url = f"https://www.federalregister.gov/d/{number}"
    elif selected == "europarl":
        process_id = safe_identifier(
            record_id, field_name="process_id", pattern=r"[A-Za-z0-9()_.-]{3,50}"
        )
        url = (
            f"https://oeil.secure.europarl.europa.eu/oeil/en/procedure-file?reference={process_id}"
        )
    elif selected == "eurlex":
        url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{_celex(record_id)}"
    elif selected == "uk_bills":
        bill_id = safe_identifier(record_id, field_name="bill_id", pattern=r"\d{1,10}")
        url = f"https://bills.parliament.uk/bills/{bill_id}"
    else:
        url = f"{UK_LEGISLATION_BASE_URL}/{_uk_legislation_path(record_id)}"
    return result_envelope(
        source=SOURCES[selected],
        source_id=record_id,
        data={"url": url, "mime_type": "text/html"},
        completeness="link_only_no_document_download",
    )


@server.tool()
def get_source_health(source: str) -> str:
    """Perform a lightweight official endpoint check and report credential presence safely."""
    selected = _source(source)
    credential_env: tuple[str, ...] = ()
    if selected == "congress":
        credential_env = ("CONGRESS_API_KEY", "DATA_GOV_API_KEY")
        detail = "Congress.gov API is reachable."
        probe = partial(_congress_json, "congress/current")
    elif selected == "federal_register":
        detail = "Federal Register JSON API is reachable."
        probe = partial(
            request_json,
            "Federal Register",
            f"{FEDERAL_REGISTER_BASE_URL}/documents.json",
            params={"per_page": 1},
        )
    elif selected == "europarl":
        detail = "European Parliament JSON-LD API v2 is reachable."
        probe = partial(_ep_json, "procedures", {"limit": 1})
    elif selected == "eurlex":
        probe = partial(
            request,
            "EUR-Lex CELLAR",
            f"{CELLAR_BASE_URL}/32023R0956",
            headers={"Accept": "application/xml;notice=identifiers"},
            timeout=60,
        )
        detail = "EUR-Lex CELLAR structured metadata endpoint is reachable."
    elif selected == "uk_bills":
        detail = "UK Parliament Bills JSON API is reachable."
        probe = partial(
            request_json,
            "UK Parliament Bills",
            f"{UK_BILLS_BASE_URL}/Bills",
            params={"Skip": 0, "Take": 1},
        )
    else:
        probe = partial(
            request,
            "legislation.gov.uk",
            f"{UK_LEGISLATION_BASE_URL}/all/data.feed",
            params={"title": "steel"},
            headers={"Accept": "application/atom+xml"},
            timeout=60,
        )
        detail = "legislation.gov.uk Atom/XML API is reachable."
    return checked_health_envelope(
        source=SOURCES[selected],
        credential_env=credential_env,
        probe=probe,
        success_detail=detail,
    )


@server.resource(
    "legislation-regulation://overview", name="Legislation and regulation MCP overview"
)
def overview() -> str:
    """Describe sources, credentials, tools, and the no-OCR document policy."""
    return json.dumps(
        {
            "sources": SOURCES,
            "tools": [
                "search_catalog",
                "search_records",
                "get_record",
                "get_document_link",
                "get_source_health",
            ],
            "credentials": {"congress": ["CONGRESS_API_KEY", "DATA_GOV_API_KEY"]},
            "document_policy": "Structured JSON, JSON-LD, Atom, or XML only; return HTML links instead of PDF/OCR.",
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    server.run("stdio")
