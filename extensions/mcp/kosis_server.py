"""KOSIS OpenAPI MCP server."""

from __future__ import annotations

import html
import json
import logging
import os
import re
import ssl
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


DEFAULT_API_KEY = "NTI4ZGI4MzE5YzdlODRiYTdkZDY2MGVlMDc0ZjkxODQ="
BASE_URL = "https://kosis.kr/openapi"
MAX_ROWS = 500

logging.getLogger("httpx").setLevel(logging.WARNING)

server = FastMCP("kosis")


def _httpx_verify_argument() -> bool | ssl.SSLContext:
    """Return the SSL verification config for KOSIS requests."""
    try:
        from myharness.utils.certificates import httpx_verify_argument
    except ImportError:
        bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
        if not bundle:
            return True
        context = ssl.create_default_context()
        try:
            context.set_ciphers("DEFAULT@SECLEVEL=1")
        except ssl.SSLError:
            pass
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        context.load_verify_locations(cafile=bundle)
        return context
    return httpx_verify_argument()


def _api_key() -> str:
    return os.environ.get("KOSIS_API_KEY", DEFAULT_API_KEY)


def _clean_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_ROWS))


def _parse_kosis_json(text: str) -> Any:
    """Parse KOSIS JSON, including legacy responses with unquoted object keys."""
    stripped = html.unescape(text).strip()
    if not stripped:
        return []
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        quoted = re.sub(r'([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*):', r'\1"\2":', stripped)
        return json.loads(quoted)


def _to_json(data: Any, limit: int | None = None) -> str:
    if limit is not None and isinstance(data, list):
        data = data[: _clean_limit(limit)]
    return json.dumps(data, ensure_ascii=False, indent=2)


def _get(endpoint: str, params: dict[str, Any]) -> Any:
    query = {
        "method": "getList",
        "apiKey": _api_key(),
        "format": "json",
        "jsonVD": "Y",
    }
    query.update({key: value for key, value in params.items() if value is not None})
    try:
        response = httpx.get(
            f"{BASE_URL}/{endpoint}",
            params=query,
            timeout=30,
            verify=_httpx_verify_argument(),
        )
        response.raise_for_status()
    except (httpx.HTTPError, OSError, ssl.SSLError) as exc:
        raise RuntimeError(
            "KOSIS request failed. If this is a company network, check HTTPS proxy "
            "and corporate CA settings such as HTTPS_PROXY and SSL_CERT_FILE. "
            "MyHarness will pass the configured corporate SSL context to httpx."
        ) from exc
    data = _parse_kosis_json(response.text)
    if isinstance(data, dict) and data.get("err"):
        raise ValueError(f"KOSIS API error {data.get('err')}: {data.get('errMsg', '')}")
    return data


@server.tool()
def list_statistics(vw_cd: str = "MT_ZTITLE", parent_id: str = "A", limit: int = 100) -> str:
    """List KOSIS statistics categories and tables under a service view and parent list ID."""
    data = _get(
        "statisticsList.do",
        {
            "vwCd": vw_cd,
            "parentId": parent_id,
        },
    )
    return _to_json(data, limit)


@server.tool()
def search_statistics(keyword: str, limit: int = 50) -> str:
    """Search KOSIS tables by Korean keyword and return matching table IDs and paths."""
    data = _get(
        "statisticsSearch.do",
        {
            "searchNm": keyword,
        },
    )
    return _to_json(data, limit)


@server.tool()
def get_stat_data(
    org_id: str,
    tbl_id: str,
    prd_se: str = "Y",
    start_prd_de: str | None = None,
    end_prd_de: str | None = None,
    new_est_prd_cnt: int | None = 3,
    itm_id: str = "ALL",
    obj_l1: str = "ALL",
    obj_l2: str = "",
    obj_l3: str = "",
    obj_l4: str = "",
    obj_l5: str = "",
    obj_l6: str = "",
    obj_l7: str = "",
    obj_l8: str = "",
    limit: int = 200,
) -> str:
    """Fetch KOSIS statistical data for an org/table and item/classification filters."""
    data = _get(
        "Param/statisticsParameterData.do",
        {
            "orgId": org_id,
            "tblId": tbl_id,
            "prdSe": prd_se,
            "startPrdDe": start_prd_de,
            "endPrdDe": end_prd_de,
            "newEstPrdCnt": new_est_prd_cnt,
            "itmId": itm_id,
            "objL1": obj_l1,
            "objL2": obj_l2,
            "objL3": obj_l3,
            "objL4": obj_l4,
            "objL5": obj_l5,
            "objL6": obj_l6,
            "objL7": obj_l7,
            "objL8": obj_l8,
        },
    )
    return _to_json(data, limit)


@server.tool()
def get_table_meta(org_id: str, tbl_id: str, meta_type: str = "TBL", limit: int = 200) -> str:
    """Return KOSIS table metadata such as title, organization, items, units, notes, or update date."""
    data = _get(
        "statisticsData.do",
        {
            "method": "getMeta",
            "type": meta_type,
            "orgId": org_id,
            "tblId": tbl_id,
        },
    )
    return _to_json(data, limit)


@server.tool()
def explain_statistics(
    org_id: str | None = None,
    tbl_id: str | None = None,
    stat_id: str | None = None,
    meta_itm: str = "All",
    limit: int = 200,
) -> str:
    """Return KOSIS survey/statistics explanation metadata by statId or orgId plus tblId."""
    if not stat_id and not (org_id and tbl_id):
        raise ValueError("Provide stat_id or both org_id and tbl_id.")
    data = _get(
        "statisticsExplData.do",
        {
            "statId": stat_id,
            "orgId": org_id,
            "tblId": tbl_id,
            "metaItm": meta_itm,
        },
    )
    return _to_json(data, limit)


@server.tool()
def check_connection() -> str:
    """Check whether the KOSIS API is reachable from the current network."""
    data = _get(
        "statisticsList.do",
        {
            "vwCd": "MT_ZTITLE",
            "parentId": "A",
        },
    )
    rows = data if isinstance(data, list) else []
    return _to_json(
        {
            "ok": True,
            "base_url": BASE_URL,
            "sample_count": len(rows),
            "proxy_env_present": {
                "HTTP_PROXY": bool(os.environ.get("HTTP_PROXY")),
                "HTTPS_PROXY": bool(os.environ.get("HTTPS_PROXY")),
                "SSL_CERT_FILE": bool(os.environ.get("SSL_CERT_FILE")),
                "REQUESTS_CA_BUNDLE": bool(os.environ.get("REQUESTS_CA_BUNDLE")),
            },
            "message": "KOSIS API is reachable.",
        }
    )


@server.resource("kosis://overview", name="KOSIS MCP overview")
def overview() -> str:
    """Describe available KOSIS tools and common service view codes."""
    return _to_json(
        {
            "service": "KOSIS OpenAPI",
            "tools": [
                "list_statistics",
                "search_statistics",
                "get_stat_data",
                "get_table_meta",
                "explain_statistics",
                "check_connection",
            ],
            "company_network_notes": [
                "HTTPS is kept enabled because HTTP redirects expose query parameters.",
                "Use HTTPS_PROXY or HTTP_PROXY if outbound traffic must pass through a company proxy.",
                "Use SSL_CERT_FILE or REQUESTS_CA_BUNDLE if the company network requires a custom CA bundle.",
            ],
            "common_vw_cd": {
                "MT_ZTITLE": "국내통계 주제별",
                "MT_OTITLE": "국내통계 기관별",
                "MT_GTITLE01": "e-지방지표 주제별",
                "MT_GTITLE02": "e-지방지표 지역별",
                "MT_RTITLE": "국제통계",
            },
        }
    )


if __name__ == "__main__":
    server.run("stdio")
