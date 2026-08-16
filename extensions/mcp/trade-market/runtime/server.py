"""Official trade-market MCP for customs, Census, WTO, and Eurostat COMEXT."""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import partial
from typing import Any
from urllib.parse import unquote
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


CUSTOMS_URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"
CENSUS_BASE_URL = "https://api.census.gov/data/timeseries/intltrade"
WTO_BASE_URL = "https://api.wto.org/timeseries/v1"
EUROSTAT_COMEXT_URL = (
    "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409"
)

SOURCES = {
    "customs_kr": "Korea Customs Service trade statistics",
    "census": "U.S. Census International Trade",
    "wto": "World Trade Organization Timeseries API",
    "eurostat_comext": "Eurostat COMEXT DS-045409",
}

server = FastMCP("trade-market")


def _source(source: str) -> str:
    key = source.strip().lower().replace("-", "_")
    aliases = {
        "customs": "customs_kr",
        "kcs": "customs_kr",
        "us_census": "census",
        "eurostat": "eurostat_comext",
        "comext": "eurostat_comext",
    }
    key = aliases.get(key, key)
    if key not in SOURCES:
        raise ValueError(f"Unknown source {source!r}. Use one of: {', '.join(SOURCES)}")
    return key


def _required_env(message: str, *names: str) -> str:
    value = first_env(*names)
    if not value:
        raise ValueError(message)
    return value


def _customs_key() -> str:
    return unquote(
        _required_env(
            "KCS_TRADE_API_KEY or DATA_GO_KR_API_KEY is required for Korea Customs data.",
            "KCS_TRADE_API_KEY",
            "DATA_GO_KR_API_KEY",
        )
    )


def _census_key() -> str:
    return _required_env(
        "CENSUS_API_KEY is required for the U.S. Census Data API.",
        "CENSUS_API_KEY",
    )


def _wto_key() -> str:
    return _required_env("WTO_API_KEY is required for the WTO Timeseries API.", "WTO_API_KEY")


def _wto_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Ocp-Apim-Subscription-Key": _wto_key(),
    }


def _month(value: str, *, field_name: str) -> str:
    token = value.replace("-", "").strip()
    if not re.fullmatch(r"\d{6}", token):
        raise ValueError(f"{field_name} must be YYYYMM or YYYY-MM.")
    datetime.strptime(token, "%Y%m")
    return token


def _customs_period(start_period: str, end_period: str) -> tuple[str, str]:
    start = _month(start_period, field_name="start_period")
    end = _month(end_period, field_name="end_period")
    start_index = int(start[:4]) * 12 + int(start[4:])
    end_index = int(end[:4]) * 12 + int(end[4:])
    if end_index < start_index:
        raise ValueError("end_period must not be earlier than start_period.")
    if end_index - start_index >= 12:
        raise ValueError("Korea Customs requests must cover at most 12 months.")
    return start, end


def _month_sequence(start_period: str, end_period: str) -> list[str]:
    """Return an inclusive sequence of at most twelve validated YYYYMM values."""
    start, end = _customs_period(start_period, end_period)
    year, month = int(start[:4]), int(start[4:])
    values = []
    while True:
        values.append(f"{year:04d}{month:02d}")
        if values[-1] == end:
            return values
        month += 1
        if month == 13:
            year += 1
            month = 1


def _eurostat_period(value: str, *, frequency: str, field_name: str) -> str:
    token = value.strip()
    if frequency == "M":
        compact = _month(token, field_name=field_name)
        return f"{compact[:4]}-{compact[4:]}"
    if not re.fullmatch(r"\d{4}", token):
        raise ValueError(f"{field_name} must be YYYY for annual Eurostat queries.")
    return token


def _xml_rows(content: bytes) -> tuple[list[dict[str, str]], dict[str, str]]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ValueError("Korea Customs returned invalid XML.") from exc
    header = root.find(".//header")
    header_data = {
        child.tag: (child.text or "").strip()
        for child in (list(header) if header is not None else [])
    }
    result_code = header_data.get("resultCode", header_data.get("result_code", ""))
    if result_code and result_code not in {"00", "000", "0"}:
        raise ValueError(
            f"Korea Customs API error {result_code}: "
            f"{header_data.get('resultMsg', header_data.get('result_msg', ''))}"
        )
    rows = [
        {child.tag: (child.text or "").strip() for child in list(item)}
        for item in root.findall(".//items/item")
    ]
    return rows, header_data


def _rows_from_census(payload: object, limit: int) -> list[dict[str, str]]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise ValueError("U.S. Census returned an unexpected response shape.")
    headers = [str(value) for value in payload[0]]
    return [
        dict(zip(headers, [str(value) for value in row], strict=False))
        for row in payload[1 : clean_limit(limit, maximum=5000) + 1]
        if isinstance(row, list)
    ]


def _census_flow(flow: str) -> tuple[str, str, list[str]]:
    selected = flow.strip().lower()
    if selected in {"import", "imports", "m", "1"}:
        return (
            "imports/hs",
            "I_COMMODITY",
            [
                "I_COMMODITY",
                "I_COMMODITY_LDESC",
                "CTY_CODE",
                "CTY_NAME",
                "GEN_VAL_MO",
                "GEN_VAL_YR",
                "CON_VAL_MO",
            ],
        )
    if selected in {"export", "exports", "x", "2"}:
        return (
            "exports/hs",
            "E_COMMODITY",
            [
                "E_COMMODITY",
                "E_COMMODITY_LDESC",
                "CTY_CODE",
                "CTY_NAME",
                "ALL_VAL_MO",
                "ALL_VAL_YR",
            ],
        )
    raise ValueError("flow must be imports or exports.")


@server.tool()
def search_catalog(source: str, query: str = "", limit: int = 50) -> str:
    """Inspect supported source variables, indicators, and fixed dataset identifiers."""
    selected = _source(source)
    safe_limit = clean_limit(limit, maximum=500)
    needle = query.casefold().strip()
    if selected == "customs_kr":
        data: object = {
            "dataset": "data.go.kr 15100475",
            "endpoint": "getNitemtradeList",
            "parameters": ["start_period", "end_period", "product", "partner"],
            "product_levels": [2, 4, 6, 10],
            "partner_format": "ISO alpha-2",
        }
        source_id = "15100475"
    elif selected == "census":
        endpoint, _, _ = _census_flow("imports")
        payload = request_json(
            "U.S. Census International Trade",
            f"{CENSUS_BASE_URL}/{endpoint}/variables.json",
            params={"key": _census_key()},
        )
        variables = payload.get("variables", {}) if isinstance(payload, dict) else {}
        rows = [
            {"name": name, **details}
            for name, details in variables.items()
            if isinstance(details, dict)
            and (
                not needle
                or needle
                in f"{name} {details.get('label', '')} {details.get('concept', '')}".casefold()
            )
        ]
        data = rows[:safe_limit]
        source_id = "imports/hs/variables"
    elif selected == "wto":
        payload = request_json(
            "WTO Timeseries API",
            f"{WTO_BASE_URL}/indicator",
            params={"lang": 1},
            headers=_wto_headers(),
        )
        rows = (
            payload
            if isinstance(payload, list)
            else payload.get("Dataset", payload)
            if isinstance(payload, dict)
            else payload
        )
        if isinstance(rows, list) and needle:
            rows = [row for row in rows if needle in json.dumps(row, ensure_ascii=False).casefold()]
        data = rows[:safe_limit] if isinstance(rows, list) else rows
        source_id = "indicator"
    else:
        data = {
            "dataset": "DS-045409",
            "dimensions": ["freq", "reporter", "partner", "product", "flow", "time", "indicators"],
            "flow_codes": {"1": "imports", "2": "exports"},
            "indicator_examples": ["VALUE_IN_EUROS", "QUANTITY_IN_100KG", "SUPPLEMENTARY_QUANTITY"],
            "constraint_url": "https://ec.europa.eu/eurostat/api/comext/dissemination/sdmx/2.1/contentconstraint/estat/DS-045409",
        }
        source_id = "DS-045409"
    return result_envelope(
        source=SOURCES[selected],
        source_id=source_id,
        data=data,
        completeness="catalog_or_bounded_search",
        license_name="Official source reuse terms",
    )


@server.tool()
def query_trade(
    source: str,
    flow: str,
    start_period: str,
    end_period: str | None = None,
    product: str = "TOTAL",
    reporter: str | None = None,
    partner: str | None = None,
    frequency: str = "M",
    indicator: str | None = None,
    limit: int = 100,
) -> str:
    """Query bilateral or reporter trade values using source-native official classifications."""
    selected = _source(source)
    safe_limit = clean_limit(limit, maximum=5000)
    end_value = end_period or start_period
    if selected == "customs_kr":
        start, end = _customs_period(start_period, end_value)
        if not partner:
            raise ValueError("partner ISO alpha-2 code is required for Korea Customs.")
        partner_code = safe_identifier(partner.upper(), field_name="partner", pattern=r"[A-Z]{2}")
        product_code = (
            ""
            if product.upper() == "TOTAL"
            else safe_identifier(
                product,
                field_name="HS code",
                pattern=r"\d{2}|\d{4}|\d{6}|\d{10}",
            )
        )
        response = request(
            "Korea Customs Service",
            CUSTOMS_URL,
            params={
                "serviceKey": _customs_key(),
                "strtYymm": start,
                "endYymm": end,
                "hsSgn": product_code,
                "cntyCd": partner_code,
            },
        )
        rows, header = _xml_rows(response.content)
        return result_envelope(
            source=SOURCES[selected],
            source_id=f"15100475:{partner_code}:{product_code or 'TOTAL'}",
            data=rows[:safe_limit],
            as_of=end,
            unit="USD and kg as labeled by source",
            revision="monthly revisions around the 15th",
            completeness="requested_period_up_to_12_months",
            license_name="Korea Open Government data, unrestricted dataset entry",
            metadata={"header": header, "flow_parameter_ignored": flow},
        )
    if selected == "census":
        endpoint, commodity_field, fields = _census_flow(flow)
        periods = _month_sequence(start_period, end_value)
        if not partner:
            raise ValueError("partner numeric CTY_CODE is required for Census trade queries.")
        base_params: dict[str, Any] = {"get": ",".join(fields), "key": _census_key()}
        if product.upper() != "TOTAL":
            base_params[commodity_field] = safe_identifier(
                product, field_name="HS code", pattern=r"\d{2,10}"
            )
        base_params["CTY_CODE"] = safe_identifier(
            partner, field_name="CTY_CODE", pattern=r"\d{1,4}"
        )
        rows: list[dict[str, str]] = []
        for period in periods:
            payload = request_json(
                "U.S. Census International Trade",
                f"{CENSUS_BASE_URL}/{endpoint}",
                params={**base_params, "time": f"{period[:4]}-{period[4:]}"},
            )
            for row in _rows_from_census(payload, safe_limit - len(rows)):
                row.setdefault("time", f"{period[:4]}-{period[4:]}")
                rows.append(row)
            if len(rows) >= safe_limit:
                break
        return result_envelope(
            source=SOURCES[selected],
            source_id=endpoint,
            data=rows,
            as_of=periods[-1],
            unit="USD and source-native quantity fields",
            revision="revised annually with April statistics",
            completeness="inclusive_month_range_row_limited",
            license_name="U.S. Census API terms",
        )
    if selected == "wto":
        if not indicator:
            raise ValueError("indicator is required for WTO queries; use search_catalog first.")
        reporter_code = (
            safe_identifier(reporter.upper(), field_name="reporter", pattern=r"[A-Z0-9_+]+")
            if reporter
            else None
        )
        partner_code = (
            safe_identifier(partner.upper(), field_name="partner", pattern=r"[A-Z0-9_+]+")
            if partner
            else None
        )
        payload = request_json(
            "WTO Timeseries API",
            f"{WTO_BASE_URL}/indicator",
            params={
                "i": safe_identifier(indicator, field_name="indicator", pattern=r"[A-Za-z0-9_]+"),
                "r": reporter_code,
                "p": partner_code,
                "ps": start_period,
                "pe": end_value,
                "fmt": "json",
                "max": safe_limit,
            },
            headers=_wto_headers(),
        )
        return result_envelope(
            source=SOURCES[selected],
            source_id=indicator,
            data=payload,
            as_of=end_value,
            completeness="api_limit_applied",
            license_name="WTO statistical data terms",
        )
    freq = frequency.upper()
    if freq not in {"A", "M"}:
        raise ValueError("frequency must be A or M for Eurostat COMEXT.")
    flow_value = flow.strip().lower()
    if flow_value in {"import", "imports", "m", "1"}:
        flow_code = "1"
    elif flow_value in {"export", "exports", "x", "2"}:
        flow_code = "2"
    else:
        raise ValueError("flow must be imports or exports for Eurostat COMEXT.")
    if not reporter or not partner:
        raise ValueError("reporter and partner are required for Eurostat COMEXT.")
    start_value = _eurostat_period(start_period, frequency=freq, field_name="start_period")
    end_value = _eurostat_period(end_value, frequency=freq, field_name="end_period")
    if end_value < start_value:
        raise ValueError("end_period must not be earlier than start_period.")
    if freq == "M" and len(_month_sequence(start_value, end_value)) > 12:
        raise ValueError("Monthly Eurostat COMEXT requests must cover at most 12 months.")
    if freq == "A" and int(end_value) - int(start_value) >= 10:
        raise ValueError("Annual Eurostat COMEXT requests must cover at most 10 years.")
    indicator_code = safe_identifier(
        (indicator or "VALUE_IN_EUROS").upper(),
        field_name="indicator",
        pattern=r"[A-Z0-9_]{2,60}",
    )
    params = {
        "format": "JSON",
        "lang": "en",
        "freq": freq,
        "reporter": safe_identifier(reporter.upper(), field_name="reporter", pattern=r"[A-Z0-9_]+"),
        "partner": safe_identifier(partner.upper(), field_name="partner", pattern=r"[A-Z0-9_]+"),
        "product": "TOTAL"
        if product.upper() == "TOTAL"
        else safe_identifier(
            product,
            field_name="product",
            pattern=r"[A-Z0-9_]{2,10}",
        ),
        "flow": flow_code,
        "indicators": indicator_code,
        "sinceTimePeriod": start_value,
        "untilTimePeriod": end_value,
    }
    payload = request_json("Eurostat COMEXT", EUROSTAT_COMEXT_URL, params=params, timeout=90)
    return result_envelope(
        source=SOURCES[selected],
        source_id="DS-045409",
        data=payload,
        as_of=end_value,
        unit=indicator_code,
        revision="latest Eurostat dissemination revision",
        completeness="exact_filtered_json_stat_query",
        license_name="Eurostat reuse policy",
    )


@server.tool()
def get_source_health(source: str) -> str:
    """Check a trade source or report that its required credential is not configured."""
    selected = _source(source)
    credential_names = {
        "customs_kr": ("KCS_TRADE_API_KEY", "DATA_GO_KR_API_KEY"),
        "census": ("CENSUS_API_KEY",),
        "wto": ("WTO_API_KEY",),
        "eurostat_comext": (),
    }[selected]
    if selected == "eurostat_comext":
        probe = partial(
            query_trade,
            "eurostat_comext",
            "imports",
            "2025-01",
            "2025-01",
            product="7208",
            reporter="DE",
            partner="US",
            indicator="VALUE_IN_EUROS",
            limit=1,
        )
        detail = "Eurostat COMEXT endpoint is reachable."
    elif selected == "census":

        def probe() -> object:
            return request_json(
                "U.S. Census International Trade",
                f"{CENSUS_BASE_URL}/imports/hs/variables.json",
                params={"key": _census_key()},
            )

        detail = "U.S. Census International Trade endpoint is reachable."
    elif selected == "wto":

        def probe() -> object:
            return request_json(
                "WTO Timeseries API",
                f"{WTO_BASE_URL}/indicator",
                params={"lang": 1},
                headers=_wto_headers(),
            )

        detail = "WTO Timeseries endpoint is reachable."
    else:
        probe = partial(
            query_trade, "customs_kr", "both", "202501", "202501", partner="US", limit=1
        )
        detail = "Korea Customs endpoint is reachable."
    return checked_health_envelope(
        source=SOURCES[selected],
        credential_env=credential_names,
        probe=probe,
        success_detail=detail,
    )


@server.resource("trade-market://overview", name="Trade market MCP overview")
def overview() -> str:
    """Describe the trade-market source routing and classifications."""
    return json.dumps(
        {
            "sources": SOURCES,
            "tools": ["search_catalog", "query_trade", "get_source_health"],
            "routing": {
                "Korea bilateral HS trade": "customs_kr",
                "United States bilateral HS trade": "census",
                "WTO indicators and tariffs": "wto",
                "EU member and partner CN/HS trade": "eurostat_comext",
                "global country comparison": "existing comtrade MCP",
            },
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    server.run("stdio")
