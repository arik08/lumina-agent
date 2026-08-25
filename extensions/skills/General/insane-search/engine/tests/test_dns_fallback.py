from __future__ import annotations

import os
import sys
from types import SimpleNamespace


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from engine import fetch_chain  # noqa: E402


def test_curl_probe_retries_dns_failure_with_doh(monkeypatch) -> None:
    calls: list[dict] = []
    response = SimpleNamespace(status_code=200, text="ok")

    def fake_get(_url: str, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("DNSError: Could not resolve host")
        return response

    from curl_cffi import requests as cffi_requests

    monkeypatch.setattr(cffi_requests, "get", fake_get)

    result, error = fetch_chain._curl_probe(
        "https://example.com/",
        impersonate="safari",
        referer="",
        timeout=5,
    )

    assert result is response
    assert error is None
    assert "curl_options" not in calls[0]
    assert calls[1]["curl_options"]


def test_curl_probe_does_not_retry_non_dns_failure(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_get(_url: str, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("connection refused")

    from curl_cffi import requests as cffi_requests

    monkeypatch.setattr(cffi_requests, "get", fake_get)

    result, error = fetch_chain._curl_probe(
        "https://example.com/",
        impersonate="safari",
        referer="",
        timeout=5,
    )

    assert result is None
    assert error == "RuntimeError:connection refused"
    assert len(calls) == 1
