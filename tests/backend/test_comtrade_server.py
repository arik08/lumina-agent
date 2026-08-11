from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest


MCP_SERVER_PATH = (
    Path(__file__).resolve().parents[2]
    / "extensions"
    / "mcp"
    / "comtrade"
    / "runtime"
    / "server.py"
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
    monkeypatch.setattr(comtrade_server, "_wait_for_request_slot", lambda: None)

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
    monkeypatch.setattr(comtrade_server, "_wait_for_request_slot", lambda: None)

    assert comtrade_server._request_json("test") == {"data": []}
    assert sleeps == [1.25, 1.25, 1.75]


def test_request_json_paces_each_public_attempt(monkeypatch) -> None:
    responses = iter((_response(429), _response(200)))
    waits: list[bool] = []

    monkeypatch.setattr(
        comtrade_server.httpx, "get", lambda *_args, **_kwargs: next(responses)
    )
    monkeypatch.setattr(
        comtrade_server, "_wait_for_request_slot", lambda: waits.append(True)
    )
    monkeypatch.setattr(comtrade_server, "_retry_sleep", lambda *_args: None)

    assert comtrade_server._request_json("test") == {"data": []}
    assert waits == [True, True]


def test_retry_sleep_honors_json_rate_limit_message(monkeypatch) -> None:
    response = httpx.Response(
        429,
        json={"message": "Rate limit is exceeded. Try again in 2 seconds."},
        request=httpx.Request("GET", "https://comtradeapi.un.org/test"),
    )
    sleeps: list[float] = []
    monkeypatch.setattr(comtrade_server.time, "sleep", sleeps.append)

    comtrade_server._retry_sleep(1, response)

    assert sleeps == [2.25]


def test_public_request_slot_enforces_minimum_interval(monkeypatch) -> None:
    sleeps: list[float] = []
    monotonic_values = iter((10.0, 10.5))
    monkeypatch.setattr(comtrade_server, "_last_public_request_at", 0.0)
    monkeypatch.setattr(comtrade_server.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(comtrade_server.time, "sleep", sleeps.append)

    comtrade_server._wait_for_request_slot()
    comtrade_server._wait_for_request_slot()

    assert sleeps == [1.75]


def test_request_json_preserves_safe_http_error_detail(monkeypatch) -> None:
    response = httpx.Response(
        400,
        json={
            "error": "Invalid parameter value",
            "details": [{"MemberNames": ["partnerCode"]}],
        },
        request=httpx.Request("GET", "https://comtradeapi.un.org/test"),
    )
    monkeypatch.setattr(
        comtrade_server.httpx, "get", lambda *_args, **_kwargs: response
    )
    monkeypatch.setattr(comtrade_server, "_wait_for_request_slot", lambda: None)

    with pytest.raises(RuntimeError) as failure:
        comtrade_server._request_json("test")

    assert "HTTP 400" in str(failure.value)
    assert "Invalid parameter value" in str(failure.value)
    assert "partnerCode" in str(failure.value)


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


def test_trade_params_reject_invalid_partner_alias() -> None:
    with pytest.raises(ValueError, match="partner_code must be"):
        comtrade_server._trade_params(
            reporter_code="410",
            period="2024",
            cmd_code="2601",
            flow_code="M",
            partner_code="invalid-partner",
            partner2_code="0",
            customs_code="C00",
            mot_code="0",
            include_desc=True,
        )
