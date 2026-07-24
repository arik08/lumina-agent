from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx


MCP_SERVER_PATH = (
    Path(__file__).resolve().parents[2] / "extensions" / "mcp" / "comtrade_server.py"
)
SPEC = importlib.util.spec_from_file_location("test_comtrade_server_module", MCP_SERVER_PATH)
assert SPEC is not None and SPEC.loader is not None
comtrade_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comtrade_server)


def _response(status_code: int, *, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(
        status_code,
        headers=headers,
        json={"data": []},
        request=httpx.Request("GET", "https://comtradeapi.un.org/test"),
    )


def test_request_json_honors_retry_after_with_boundary_grace(monkeypatch) -> None:
    responses = iter((_response(429, retry_after="1"), _response(200)))
    sleeps: list[float] = []

    monkeypatch.setattr(
        comtrade_server.httpx, "get", lambda *_args, **_kwargs: next(responses)
    )
    monkeypatch.setattr(comtrade_server.time, "sleep", sleeps.append)

    assert comtrade_server._request_json("test") == {"data": []}
    assert sleeps == [1.25]


def test_request_json_allows_a_fourth_attempt_after_repeated_rate_limits(
    monkeypatch,
) -> None:
    responses = iter(
        (
            _response(429, retry_after="1"),
            _response(429, retry_after="1"),
            _response(429, retry_after="1"),
            _response(200),
        )
    )
    sleeps: list[float] = []

    monkeypatch.setattr(
        comtrade_server.httpx, "get", lambda *_args, **_kwargs: next(responses)
    )
    monkeypatch.setattr(comtrade_server.time, "sleep", sleeps.append)

    assert comtrade_server._request_json("test") == {"data": []}
    assert sleeps == [1.25, 1.25, 1.75]


def test_trade_params_omit_partner_code_for_all_partner_breakdown() -> None:
    params = comtrade_server._trade_params(
        reporter_code="410",
        period="2024",
        cmd_code="2601",
        flow_code="M",
        partner_code=" ALL ",
        partner2_code="0",
        customs_code="C00",
        mot_code="0",
        include_desc=True,
    )

    query = {key: value for key, value in params.items() if value is not None}

    assert "partnerCode" not in query


def test_trade_params_keep_world_partner_code() -> None:
    params = comtrade_server._trade_params(
        reporter_code="410",
        period="2024",
        cmd_code="2601",
        flow_code="M",
        partner_code="0",
        partner2_code="0",
        customs_code="C00",
        mot_code="0",
        include_desc=True,
    )

    assert params["partnerCode"] == "0"
