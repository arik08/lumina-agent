"""Official company disclosure MCP for OpenDART, SEC EDGAR, and Companies House."""

from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import zipfile
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

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


DART_BASE_URL = "https://opendart.fss.or.kr/api"
SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_FILES_BASE_URL = "https://www.sec.gov/files"
COMPANIES_HOUSE_BASE_URL = "https://api.company-information.service.gov.uk"

SOURCES = {
    "opendart": "Financial Supervisory Service OpenDART",
    "sec": "U.S. SEC EDGAR",
    "companies_house": "UK Companies House",
}

server = FastMCP("company-disclosure")


def _source(source: str) -> str:
    key = source.strip().lower().replace("-", "_")
    aliases = {"dart": "opendart", "edgar": "sec", "companieshouse": "companies_house"}
    key = aliases.get(key, key)
    if key not in SOURCES:
        raise ValueError(f"Unknown source {source!r}. Use one of: {', '.join(SOURCES)}")
    return key


def _date(value: str | None, *, field_name: str, compact: bool = False) -> str | None:
    """Validate an ISO or compact calendar date and return the requested format."""
    if value is None:
        return None
    token = value.strip()
    parsed = None
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            parsed = datetime.strptime(token, pattern)
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError(f"{field_name} must be YYYY-MM-DD or YYYYMMDD.")
    return parsed.strftime("%Y%m%d" if compact else "%Y-%m-%d")


def _dart_key() -> str:
    key = first_env("DART_API_KEY", "OPENDART_API_KEY")
    if not key:
        raise ValueError("DART_API_KEY or OPENDART_API_KEY is required for OpenDART.")
    return key


def _dart_json(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = request_json(
        "OpenDART",
        f"{DART_BASE_URL}/{endpoint}",
        params={"crtfc_key": _dart_key(), **params},
    )
    if not isinstance(payload, dict):
        raise ValueError("OpenDART returned an unexpected JSON shape.")
    status = str(payload.get("status", ""))
    if status == "000":
        return payload
    if status == "013":
        copied = dict(payload)
        copied.setdefault("list", [])
        return copied
    raise ValueError(f"OpenDART API error {status or 'unknown'}: {payload.get('message', '')}")


def _xml_text(node: Element, name: str) -> str:
    child = node.find(name)
    return (child.text or "").strip() if child is not None else ""


@lru_cache(maxsize=1)
def _dart_corporations() -> tuple[dict[str, str], ...]:
    response = request(
        "OpenDART",
        f"{DART_BASE_URL}/corpCode.xml",
        params={"crtfc_key": _dart_key()},
        timeout=90,
    )
    content = response.content
    if zipfile.is_zipfile(io.BytesIO(content)):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            if not xml_names:
                raise ValueError("OpenDART corporation archive does not contain XML.")
            content = archive.read(xml_names[0])
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ValueError(
            "OpenDART corporation list is neither a valid ZIP nor XML response."
        ) from exc
    status = _xml_text(root, "status")
    if status and status != "000":
        raise ValueError(f"OpenDART API error {status}: {_xml_text(root, 'message')}")
    rows = []
    for item in root.findall(".//list"):
        rows.append(
            {
                "corp_code": _xml_text(item, "corp_code"),
                "corp_name": _xml_text(item, "corp_name"),
                "corp_eng_name": _xml_text(item, "corp_eng_name"),
                "stock_code": _xml_text(item, "stock_code"),
                "modify_date": _xml_text(item, "modify_date"),
            }
        )
    return tuple(rows)


def _search_dart_companies(query: str, limit: int) -> list[dict[str, str]]:
    needle = query.casefold().strip()
    if not needle:
        raise ValueError("query is required for OpenDART company search.")
    matches = [
        row
        for row in _dart_corporations()
        if needle
        in " ".join(
            (row["corp_code"], row["corp_name"], row["corp_eng_name"], row["stock_code"])
        ).casefold()
    ]
    matches.sort(
        key=lambda row: (
            row["corp_name"].casefold() != needle,
            not row["stock_code"],
            row["corp_name"],
        )
    )
    return matches[: clean_limit(limit, maximum=100)]


def _sec_user_agent() -> str:
    value = first_env("SEC_USER_AGENT")
    if not value:
        raise ValueError(
            "SEC_USER_AGENT is required by SEC fair-access policy. "
            "Set it to an application name and monitored contact email."
        )
    return value


def _sec_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": _sec_user_agent(),
    }


def _sec_json(url: str) -> object:
    """Fetch SEC JSON, falling back to system curl for SEC edge TLS blocks."""
    try:
        return request_json("SEC EDGAR", url, headers=_sec_headers())
    except RuntimeError as primary_error:
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if not curl:
            raise
        # The executable comes from shutil.which, arguments are a fixed list, the URL is
        # assembled only from SEC constants plus validated identifiers, and no shell is used.
        completed = subprocess.run(  # noqa: S603
            [
                curl,
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                "45",
                "--user-agent",
                _sec_user_agent(),
                "--header",
                "Accept: application/json",
                "--header",
                "Accept-Encoding: gzip, deflate",
                url,
            ],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise primary_error
        try:
            return json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("SEC EDGAR curl fallback returned invalid JSON.") from exc


@lru_cache(maxsize=1)
def _sec_companies() -> tuple[dict[str, Any], ...]:
    payload = _sec_json(f"{SEC_FILES_BASE_URL}/company_tickers.json")
    if not isinstance(payload, dict):
        raise ValueError("SEC company ticker response has an unexpected shape.")
    rows = [row for row in payload.values() if isinstance(row, dict)]
    return tuple(rows)


def _search_sec_companies(query: str, limit: int) -> list[dict[str, Any]]:
    needle = query.casefold().strip()
    if not needle:
        raise ValueError("query is required for SEC company search.")
    matches = [
        row
        for row in _sec_companies()
        if needle
        in f"{row.get('ticker', '')} {row.get('title', '')} {row.get('cik_str', '')}".casefold()
    ]
    matches.sort(
        key=lambda row: (
            str(row.get("ticker", "")).casefold() != needle,
            str(row.get("title", "")).casefold() != needle,
            str(row.get("title", "")),
        )
    )
    return matches[: clean_limit(limit, maximum=100)]


def _sec_cik(value: str) -> str:
    token = safe_identifier(value, field_name="CIK", pattern=r"\d{1,10}")
    return token.zfill(10)


def _sec_recent_filings(
    payload: object,
    *,
    limit: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Convert the SEC columnar recent-filings object into bounded rows."""
    recent = payload.get("filings", {}).get("recent", {}) if isinstance(payload, dict) else {}
    if not isinstance(recent, dict):
        raise ValueError("SEC submissions response is missing filings.recent.")
    keys = list(recent)
    row_count = min([len(value) for value in recent.values() if isinstance(value, list)] or [0])
    rows = [
        {key: recent[key][index] for key in keys if isinstance(recent.get(key), list)}
        for index in range(row_count)
    ]
    if start_date:
        rows = [row for row in rows if str(row.get("filingDate", "")) >= start_date]
    if end_date:
        rows = [row for row in rows if str(row.get("filingDate", "")) <= end_date]
    return rows[: clean_limit(limit, maximum=1000)]


def _bounded_sec_companyfacts(
    payload: object, *, limit: int
) -> tuple[dict[str, Any], dict[str, int]]:
    """Bound SEC companyfacts by concept and recent unit observations."""
    if not isinstance(payload, dict) or not isinstance(payload.get("facts"), dict):
        raise ValueError("SEC companyfacts response is missing facts.")
    concept_limit = clean_limit(limit, maximum=250)
    bounded_facts: dict[str, dict[str, Any]] = {}
    total_concepts = 0
    returned_concepts = 0
    for taxonomy, concepts in payload["facts"].items():
        if not isinstance(concepts, dict):
            continue
        total_concepts += len(concepts)
        taxonomy_rows: dict[str, Any] = {}
        for concept, details in concepts.items():
            if returned_concepts >= concept_limit:
                break
            if not isinstance(details, dict):
                continue
            copied = {key: value for key, value in details.items() if key != "units"}
            units = details.get("units", {})
            if isinstance(units, dict):
                copied["units"] = {
                    unit: observations[-20:] if isinstance(observations, list) else observations
                    for unit, observations in units.items()
                }
            taxonomy_rows[str(concept)] = copied
            returned_concepts += 1
        if taxonomy_rows:
            bounded_facts[str(taxonomy)] = taxonomy_rows
        if returned_concepts >= concept_limit:
            break
    data = {
        "cik": payload.get("cik"),
        "entityName": payload.get("entityName"),
        "facts": bounded_facts,
    }
    return data, {"total_concepts": total_concepts, "returned_concepts": returned_concepts}


def _companies_house_key() -> str:
    key = first_env("COMPANIES_HOUSE_API_KEY")
    if not key:
        raise ValueError("COMPANIES_HOUSE_API_KEY is required for Companies House.")
    return key


def _companies_house_headers() -> dict[str, str]:
    token = base64.b64encode(f"{_companies_house_key()}:".encode()).decode()
    return {"Accept": "application/json", "Authorization": f"Basic {token}"}


def _companies_house_json(path: str, params: dict[str, Any] | None = None) -> object:
    return request_json(
        "Companies House",
        f"{COMPANIES_HOUSE_BASE_URL}/{path.lstrip('/')}",
        params=params,
        headers=_companies_house_headers(),
    )


@server.tool()
def search_catalog(source: str, query: str, limit: int = 20) -> str:
    """Search company identifiers before requesting filings or financial data."""
    selected = _source(source)
    safe_limit = clean_limit(limit, maximum=100)
    if selected == "opendart":
        data = _search_dart_companies(query, safe_limit)
        source_id = "corpCode.xml"
        license_name = "OpenDART Open API terms"
    elif selected == "sec":
        data = _search_sec_companies(query, safe_limit)
        source_id = "company_tickers.json"
        license_name = "U.S. government public data"
    else:
        payload = _companies_house_json(
            "search/companies",
            {"q": query, "items_per_page": safe_limit},
        )
        data = payload.get("items", []) if isinstance(payload, dict) else []
        source_id = "search/companies"
        license_name = "Companies House API terms"
    return result_envelope(
        source=SOURCES[selected],
        source_id=source_id,
        data=data,
        completeness="bounded_search_results",
        license_name=license_name,
    )


@server.tool()
def search_records(
    source: str,
    query: str = "",
    identifier: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
) -> str:
    """Search disclosure records; identifier means corp code, CIK, or company number by source."""
    selected = _source(source)
    safe_limit = clean_limit(limit, maximum=100)
    start_iso = _date(start_date, field_name="start_date")
    end_iso = _date(end_date, field_name="end_date")
    if start_iso and end_iso and start_iso > end_iso:
        raise ValueError("end_date must not be earlier than start_date.")
    if selected == "opendart":
        corp_code = identifier
        company_matches: list[dict[str, str]] = []
        if not corp_code:
            company_matches = _search_dart_companies(query, 5)
            if not company_matches:
                return result_envelope(
                    source=SOURCES[selected],
                    source_id="list.json",
                    data=[],
                    completeness="no_matching_company",
                    license_name="OpenDART Open API terms",
                )
            corp_code = company_matches[0]["corp_code"]
        corp_code = safe_identifier(corp_code, field_name="corp_code", pattern=r"\d{8}")
        payload = _dart_json(
            "list.json",
            {
                "corp_code": corp_code,
                "bgn_de": _date(start_date, field_name="start_date", compact=True),
                "end_de": _date(end_date, field_name="end_date", compact=True),
                "page_count": safe_limit,
                "sort": "date",
                "sort_mth": "desc",
            },
        )
        return result_envelope(
            source=SOURCES[selected],
            source_id="list.json",
            data=payload.get("list", []),
            as_of=end_iso,
            completeness="page_limited",
            license_name="OpenDART Open API terms",
            metadata={
                "resolved_company": company_matches[0] if company_matches else None,
                "total_count": payload.get("total_count"),
                "total_page": payload.get("total_page"),
            },
        )
    if selected == "sec":
        if not identifier:
            return search_catalog("sec", query, safe_limit)
        cik = _sec_cik(identifier)
        payload = _sec_json(f"{SEC_DATA_BASE_URL}/submissions/CIK{cik}.json")
        rows = _sec_recent_filings(
            payload,
            limit=safe_limit,
            start_date=start_iso,
            end_date=end_iso,
        )
        return result_envelope(
            source=SOURCES[selected],
            source_id=f"CIK{cik}/submissions",
            data=rows,
            as_of=end_iso,
            completeness="recent_filings_only_locally_date_filtered",
            license_name="U.S. government public data",
            metadata={"company_name": payload.get("name") if isinstance(payload, dict) else None},
        )
    if not identifier:
        return search_catalog("companies_house", query, safe_limit)
    company_number = safe_identifier(
        identifier, field_name="company_number", pattern=r"[A-Za-z0-9]{1,12}"
    )
    payload = _companies_house_json(
        f"company/{company_number}/filing-history",
        {"items_per_page": safe_limit},
    )
    data = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(data, list):
        raise ValueError("Companies House filing history has an unexpected shape.")
    if start_iso:
        data = [row for row in data if str(row.get("date", "")) >= start_iso]
    if end_iso:
        data = [row for row in data if str(row.get("date", "")) <= end_iso]
    return result_envelope(
        source=SOURCES[selected],
        source_id=f"company/{company_number}/filing-history",
        data=data,
        as_of=end_iso,
        completeness="recent_page_locally_date_filtered",
        license_name="Companies House API terms",
        metadata={"total_count": payload.get("total_count") if isinstance(payload, dict) else None},
    )


@server.tool()
def get_record(
    source: str,
    record_id: str,
    record_type: str = "company",
    business_year: int | None = None,
    report_code: str = "11011",
    financial_statement: str = "CFS",
    limit: int = 1000,
) -> str:
    """Get one company profile, filing collection, or structured financial statement."""
    selected = _source(source)
    kind = record_type.strip().lower()
    if selected == "opendart":
        corp_code = safe_identifier(record_id, field_name="corp_code", pattern=r"\d{8}")
        if kind == "company":
            payload = _dart_json("company.json", {"corp_code": corp_code})
            data: object = {
                key: value for key, value in payload.items() if key not in {"status", "message"}
            }
            source_id = f"company:{corp_code}"
            as_of = None
        elif kind in {"financials", "financial_statement", "finance"}:
            if business_year is None:
                raise ValueError("business_year is required for OpenDART financial statements.")
            if not 1900 <= int(business_year) <= datetime.now(UTC).year:
                raise ValueError("business_year must be between 1900 and the current year.")
            if report_code not in {"11011", "11012", "11013", "11014"}:
                raise ValueError("report_code must be 11011, 11012, 11013, or 11014.")
            fs_div = financial_statement.upper()
            if fs_div not in {"CFS", "OFS"}:
                raise ValueError("financial_statement must be CFS or OFS.")
            payload = _dart_json(
                "fnlttSinglAcntAll.json",
                {
                    "corp_code": corp_code,
                    "bsns_year": str(business_year),
                    "reprt_code": report_code,
                    "fs_div": fs_div,
                },
            )
            data = payload.get("list", [])[: clean_limit(limit, maximum=5000)]
            source_id = f"financials:{corp_code}:{business_year}:{report_code}:{fs_div}"
            as_of = str(business_year)
        else:
            raise ValueError("OpenDART record_type must be company or financials.")
        return result_envelope(
            source=SOURCES[selected],
            source_id=source_id,
            data=data,
            as_of=as_of,
            revision="latest_returned_by_api",
            completeness=(
                "row_limited_reported_by_filer"
                if kind in {"financials", "financial_statement", "finance"}
                else "reported_by_filer"
            ),
            license_name="OpenDART Open API terms",
        )
    if selected == "sec":
        cik = _sec_cik(record_id)
        if kind not in {"company", "submissions", "companyfacts", "facts", "financials"}:
            raise ValueError("SEC record_type must be company, submissions, or companyfacts.")
        endpoint = (
            "companyfacts" if kind in {"companyfacts", "facts", "financials"} else "submissions"
        )
        url = (
            f"{SEC_DATA_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json"
            if endpoint == "companyfacts"
            else f"{SEC_DATA_BASE_URL}/submissions/CIK{cik}.json"
        )
        payload = _sec_json(url)
        metadata: dict[str, Any] | None = None
        if endpoint == "companyfacts":
            data, metadata = _bounded_sec_companyfacts(payload, limit=limit)
            completeness = "concept_and_recent_observation_limited"
        else:
            if not isinstance(payload, dict):
                raise ValueError("SEC submissions response has an unexpected shape.")
            data = {
                key: payload.get(key)
                for key in (
                    "cik",
                    "name",
                    "tickers",
                    "exchanges",
                    "sic",
                    "sicDescription",
                    "fiscalYearEnd",
                    "stateOfIncorporation",
                    "addresses",
                )
            }
            data["recent_filings"] = _sec_recent_filings(payload, limit=limit)
            completeness = "profile_with_recent_filings_limited"
        return result_envelope(
            source=SOURCES[selected],
            source_id=f"CIK{cik}/{endpoint}",
            data=data,
            revision="latest_returned_by_api",
            completeness=completeness,
            license_name="U.S. government public data",
            metadata=metadata,
        )
    company_number = safe_identifier(
        record_id, field_name="company_number", pattern=r"[A-Za-z0-9]{1,12}"
    )
    if kind not in {"company", "profile", "officers"}:
        raise ValueError("Companies House record_type must be company or officers.")
    path = (
        f"company/{company_number}/officers" if kind == "officers" else f"company/{company_number}"
    )
    payload = _companies_house_json(path)
    return result_envelope(
        source=SOURCES[selected],
        source_id=path,
        data=payload,
        revision="latest_returned_by_api",
        completeness="reported_by_registry",
        license_name="Companies House API terms",
    )


@server.tool()
def get_document_link(source: str, record_id: str, auxiliary_id: str | None = None) -> str:
    """Return an official viewer or registry link without downloading PDF documents."""
    selected = _source(source)
    if selected == "opendart":
        receipt = safe_identifier(record_id, field_name="receipt number", pattern=r"\d{14}")
        url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}"
    elif selected == "sec":
        cik = _sec_cik(auxiliary_id or record_id).lstrip("0") or "0"
        if auxiliary_id:
            accession = safe_identifier(
                record_id, field_name="accession number", pattern=r"\d{10}-\d{2}-\d{6}"
            )
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
        else:
            url = f"https://www.sec.gov/edgar/browse/?CIK={cik}"
    else:
        company_number = safe_identifier(
            record_id, field_name="company_number", pattern=r"[A-Za-z0-9]{1,12}"
        )
        url = f"https://find-and-update.company-information.service.gov.uk/company/{company_number}"
    return result_envelope(
        source=SOURCES[selected],
        source_id=record_id,
        data={"url": url, "mime_type": "text/html"},
        completeness="link_only_no_document_download",
        license_name=None,
    )


@server.tool()
def get_source_health(source: str) -> str:
    """Perform a lightweight official endpoint check and report credential presence safely."""
    selected = _source(source)
    if selected == "opendart":
        return checked_health_envelope(
            source=SOURCES[selected],
            credential_env=("DART_API_KEY", "OPENDART_API_KEY"),
            probe=lambda: _dart_json("company.json", {"corp_code": "00126380"}),
            success_detail="OpenDART company endpoint is reachable.",
        )
    if selected == "sec":
        return checked_health_envelope(
            source=SOURCES[selected],
            credential_env=("SEC_USER_AGENT",),
            probe=lambda: _sec_json(f"{SEC_DATA_BASE_URL}/submissions/CIK0000320193.json"),
            success_detail=(
                "SEC data endpoint is reachable. Company ticker catalog uses www.sec.gov, "
                "which may be independently blocked by a network or SEC edge policy."
            ),
        )
    return checked_health_envelope(
        source=SOURCES[selected],
        credential_env=("COMPANIES_HOUSE_API_KEY",),
        probe=lambda: _companies_house_json("company/00000006"),
        success_detail="Companies House company endpoint is reachable.",
    )


@server.resource("company-disclosure://overview", name="Company disclosure MCP overview")
def overview() -> str:
    """Describe supported company disclosure sources, tools, and credentials."""
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
            "credentials": {
                "opendart": ["DART_API_KEY", "OPENDART_API_KEY"],
                "sec": ["SEC_USER_AGENT"],
                "companies_house": ["COMPANIES_HOUSE_API_KEY"],
            },
            "document_policy": "Return official links; do not download or OCR filing PDFs.",
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    server.run("stdio")
