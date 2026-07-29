from __future__ import annotations

import asyncio
import hashlib
import ssl
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from reportlab.pdfgen.canvas import Canvas

from lumina.http_client import HttpClientOptions, TrustProfile
from lumina.tools import web as web_module
from lumina.tools.web import (
    UNTRUSTED_CONTENT_BANNER,
    WebToolError,
    WebToolPolicy,
    create_web_http_client,
    normalize_public_url,
    web_fetch,
    web_search,
)


async def _public_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
    return ("93.184.216.34",)


@pytest.mark.asyncio
async def test_duckduckgo_search_parses_structured_evidence() -> None:
    search_html = """
    <html><body>
      <div class="result">
        <h2><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fguide%2F%3Futm_source%3Dddg%26x%3D1">Example <b>Guide</b></a></h2>
        <a class="result__snippet">A verbatim result snippet with useful evidence.</a>
      </div>
      <div class="result">
        <a class="result__a" href="https://example.com/guide/?x=1&utm_medium=duplicate">Duplicate URL</a>
        <div class="result__snippet">This duplicate must be removed.</div>
      </div>
      <div class="result">
        <a class="result__a" href="http://127.0.0.1/private">Private result</a>
        <div class="result__snippet">This result must be rejected.</div>
      </div>
      <div class="result">
        <a class="result__a" href="https://second.example/news">Second result</a>
        <div class="result__snippet">Another source.</div>
      </div>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "html.duckduckgo.com"
        assert request.url.params["q"] == "steel market outlook"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=search_html.encode(),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await web_search(
            "  steel   market\n outlook  ",
            tool_execution_id="tool-search-1",
            result_limit=5,
            purpose="official_facts",
            parent_invocation_id="search-parent",
            client=client,
            resolver=_public_resolver,
        )

    assert result.invocation.backend == "duckduckgo_html"
    assert result.invocation.query == "steel market outlook"
    assert result.invocation.tool_execution_id == "tool-search-1"
    assert result.invocation.purpose == "official_facts"
    assert result.invocation.parent_invocation_id == "search-parent"
    assert len(result.sources) == 2
    first = result.sources[0]
    assert first.title == "Example Guide"
    assert first.normalized_url == "https://example.com/guide?x=1"
    assert first.original_url.endswith("utm_source=ddg&x=1")
    assert first.verbatim_excerpt == "A verbatim result snippet with useful evidence."
    assert first.evidence_kind == "search_snippet"
    assert first.extraction_status == "snippet_only"
    assert first.search_backends == ("duckduckgo_html",)
    assert first.query_ids == (result.invocation.invocation_id,)
    assert first.tool_execution_ids == ("tool-search-1",)
    assert first.source_id.startswith("src_")
    assert len(first.content_hash) == 64
    assert result.to_dict()["untrustedExternalContent"] is True


@pytest.mark.asyncio
async def test_web_search_uses_explicit_backend_boundary() -> None:
    class PlannedBackend:
        name = "planned_test_backend"

        async def search(self, query: str, **_kwargs) -> tuple[object, ...]:
            assert query == "future backend boundary"
            return (
                web_module._SearchEntry(
                    url="https://example.com/future",
                    title="Future backend",
                    snippet="Backend result",
                ),
            )

    result = await web_search(
        "future backend boundary",
        tool_execution_id="tool-planned-backend",
        backend=PlannedBackend(),
        resolver=_public_resolver,
    )

    assert result.invocation.backend == "planned_test_backend"
    assert result.sources[0].search_backends == ("planned_test_backend",)


@pytest.mark.asyncio
async def test_web_fetch_extracts_readable_html_and_content_hash() -> None:
    html = b"""<!doctype html><html><head><title>  Safety &amp; Quality </title>
    <script>ignore_secret_script()</script></head><body>
    <nav>Navigation must be omitted</nav>
    <main><h1>Inspection result</h1><p>All checks passed.</p></main>
    </body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://example.com/report")
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=html,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await web_fetch(
            "https://example.com/report#internal-anchor",
            tool_execution_id="tool-fetch-1",
            query_ids=("search-1", "search-1"),
            page_start=1,
            page_end=1,
            client=client,
            resolver=_public_resolver,
        )

    assert result.evidence.title == "Safety & Quality"
    assert result.evidence.normalized_url == "https://example.com/report"
    assert result.evidence.query_ids == ("search-1",)
    assert result.evidence.evidence_kind == "fetched_content"
    assert result.evidence.content_type == "text/html"
    assert result.evidence.extraction_status == "complete"
    assert result.evidence.text_chars == len(result.text)
    assert result.evidence.content_hash == hashlib.sha256(html).hexdigest()
    assert "Inspection result" in result.text
    assert "All checks passed." in result.text
    assert "ignore_secret_script" not in result.text
    assert "Navigation must be omitted" not in result.text
    assert result.prompt_text.startswith(UNTRUSTED_CONTENT_BANNER)
    assert result.to_dict()["text"].startswith(UNTRUSTED_CONTENT_BANNER)


@pytest.mark.asyncio
async def test_web_fetch_retries_retryable_http_failure() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={"content-type": "text/html"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<main><h1>Recovered source</h1></main>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await web_fetch(
            "https://example.com/recovered",
            tool_execution_id="tool-fetch-retry",
            client=client,
            resolver=_public_resolver,
        )

    assert attempts == 2
    assert "Recovered source" in result.text


@pytest.mark.asyncio
async def test_web_fetch_extracts_rss_feed_entries() -> None:
    feed = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <title>Steel News</title>
      <item>
        <title>New low-carbon steel route</title>
        <link>https://example.com/news/steel-route</link>
        <pubDate>Wed, 29 Jul 2026 08:00:00 GMT</pubDate>
        <description><![CDATA[<p>A pilot line started operation.</p>]]></description>
      </item>
      <item>
        <title>Second industry update</title>
        <link>https://example.com/news/update</link>
        <description>Capacity will expand next year.</description>
      </item>
    </channel></rss>"""

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/rss+xml; charset=utf-8"},
            content=feed,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await web_fetch(
            "https://example.com/news.xml",
            tool_execution_id="tool-fetch-rss",
            client=client,
            resolver=_public_resolver,
        )

    assert result.evidence.title == "Steel News"
    assert result.content_type == "application/rss+xml"
    assert "New low-carbon steel route" in result.text
    assert "https://example.com/news/steel-route" in result.text
    assert "A pilot line started operation." in result.text
    assert "Second industry update" in result.text


@pytest.mark.asyncio
async def test_web_fetch_prefers_primary_content_and_removes_page_chrome() -> None:
    html = b"""<!doctype html><html><head><title>Primary report</title></head><body>
    <header>Global company navigation<br><img src="logo.png">and account links</header>
    <div class="cookie-banner">Accept every cookie to continue</div>
    <main><article>
      <header><h1>Quarterly operating result</h1></header>
      <p>The primary report contains enough substantive detail to be selected over
      surrounding page chrome and retained as the readable body for model context.</p>
      <div class="social share">Share this report everywhere</div>
      <p>Production increased while the safety incident rate declined.</p>
    </article></main>
    <aside>Related articles and sponsored links</aside>
    <footer>Copyright, privacy, careers, and repeated site navigation</footer>
    </body></html>"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=html,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await web_fetch(
            "https://example.com/quarterly-report",
            tool_execution_id="tool-fetch-primary",
            client=client,
            resolver=_public_resolver,
        )

    assert "Quarterly operating result" in result.text
    assert "Production increased" in result.text
    assert "Global company navigation" not in result.text
    assert "Accept every cookie" not in result.text
    assert "Share this report" not in result.text
    assert "Related articles" not in result.text
    assert "Copyright, privacy" not in result.text


@pytest.mark.asyncio
async def test_web_fetch_extracts_pdf_text_with_page_locators() -> None:
    buffer = BytesIO()
    canvas = Canvas(buffer)
    canvas.drawString(72, 720, "First page annual report evidence")
    canvas.showPage()
    canvas.drawString(72, 720, "Second page procurement evidence")
    canvas.save()
    pdf = buffer.getvalue()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=pdf,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await web_fetch(
            "https://example.com/annual-report.pdf",
            tool_execution_id="tool-fetch-pdf",
            policy=WebToolPolicy(max_response_bytes=12),
            client=client,
            resolver=_public_resolver,
        )

    assert result.content_type == "application/pdf"
    assert result.evidence.title == "annual-report.pdf"
    assert result.evidence.content_hash == hashlib.sha256(pdf).hexdigest()
    assert result.locator_map == {
        "kind": "page",
        "count": 2,
        "start": 1,
        "end": 2,
    }
    assert "[Page 1]" in result.text
    assert "First page annual report evidence" in result.text
    assert "[Page 2]" in result.text
    assert "Second page procurement evidence" in result.text


@pytest.mark.asyncio
async def test_web_fetch_uses_dedicated_large_pdf_download_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = b"%PDF-1.7\n" + (b"x" * 3_000_000)

    monkeypatch.setattr(
        web_module,
        "extract_pdf_text",
        lambda **_kwargs: SimpleNamespace(
            status="completed",
            text="[Page 1]\nLarge PDF evidence",
            locator_map={"kind": "page", "count": 200, "start": 1, "end": 50},
            metadata={"hasMorePages": True, "truncatedByPageLimit": False},
        ),
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=pdf,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await web_fetch(
            "https://example.com/large-report.pdf",
            tool_execution_id="tool-fetch-large-pdf",
            client=client,
            resolver=_public_resolver,
        )

    assert result.text == "[Page 1]\nLarge PDF evidence"
    assert result.evidence.content_hash == hashlib.sha256(pdf).hexdigest()
    assert result.locator_map == {
        "kind": "page",
        "count": 200,
        "start": 1,
        "end": 50,
    }
    assert result.extraction_metadata == {
        "hasMorePages": True,
        "truncatedByPageLimit": False,
        "originalExtractedChars": len("[Page 1]\nLarge PDF evidence"),
        "textTruncated": False,
    }


@pytest.mark.asyncio
async def test_web_fetch_accepts_pdf_url_served_as_octet_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = b"%PDF-1.7\nmock-pdf"
    monkeypatch.setattr(
        web_module,
        "extract_pdf_text",
        lambda **_kwargs: SimpleNamespace(
            status="completed",
            text="[Page 1]\nRecovered PDF evidence",
            locator_map={"kind": "page", "count": 1, "start": 1, "end": 1},
            metadata={},
        ),
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            content=pdf,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await web_fetch(
            "https://example.com/report.pdf",
            tool_execution_id="tool-fetch-octet-pdf",
            client=client,
            resolver=_public_resolver,
        )

    assert result.content_type == "application/pdf"
    assert result.text == "[Page 1]\nRecovered PDF evidence"


@pytest.mark.asyncio
async def test_web_fetch_extracts_requested_pdf_page_range() -> None:
    buffer = BytesIO()
    canvas = Canvas(buffer)
    for page_number in range(1, 4):
        canvas.drawString(72, 720, f"Evidence from page {page_number}")
        canvas.showPage()
    canvas.save()

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=buffer.getvalue(),
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await web_fetch(
            "https://example.com/ranged-report.pdf",
            tool_execution_id="tool-fetch-ranged-pdf",
            page_start=2,
            page_end=3,
            client=client,
            resolver=_public_resolver,
        )

    assert "[Page 1]" not in result.text
    assert "[Page 2]" in result.text
    assert "Evidence from page 2" in result.text
    assert "[Page 3]" in result.text
    assert result.locator_map == {
        "kind": "page",
        "count": 3,
        "start": 2,
        "end": 3,
    }


@pytest.mark.asyncio
async def test_web_fetch_rejects_pdf_range_larger_than_fifty_pages() -> None:
    with pytest.raises(WebToolError) as captured:
        await web_fetch(
            "https://example.com/report.pdf",
            tool_execution_id="tool-fetch-invalid-range",
            page_start=1,
            page_end=51,
            resolver=_public_resolver,
        )

    assert captured.value.code == "invalid_pdf_page_range"
    assert captured.value.stage == "input"


@pytest.mark.asyncio
async def test_web_fetch_reports_pdf_without_text_layer() -> None:
    buffer = BytesIO()
    canvas = Canvas(buffer)
    canvas.showPage()
    canvas.save()

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=buffer.getvalue(),
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(WebToolError) as captured:
            await web_fetch(
                "https://example.com/scanned-report.pdf",
                tool_execution_id="tool-fetch-scanned-pdf",
                client=client,
                resolver=_public_resolver,
            )

    assert captured.value.code == "pdf_text_unavailable"
    assert captured.value.stage == "content"


@pytest.mark.parametrize(
    ("url", "expected_code"),
    [
        ("file:///etc/passwd", "invalid_url_scheme"),
        ("https://user:secret@example.com/", "embedded_credentials"),
        ("http://localhost/admin", "blocked_target"),
        ("http://127.0.0.1/admin", "blocked_target"),
        ("http://169.254.169.254/latest/meta-data", "blocked_target"),
        ("http://metadata.google.internal/computeMetadata/v1", "blocked_target"),
    ],
)
def test_url_validation_blocks_non_public_targets(url: str, expected_code: str) -> None:
    with pytest.raises(WebToolError) as captured:
        normalize_public_url(url)
    assert captured.value.code == expected_code


@pytest.mark.asyncio
async def test_dns_private_result_is_blocked_before_http_request() -> None:
    requested = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="no")

    async def private_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        return ("10.10.20.30",)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WebToolError) as captured:
            await web_fetch(
                "https://apparently-public.example/data",
                tool_execution_id="tool-fetch-private",
                client=client,
                resolver=private_resolver,
            )
    assert captured.value.code == "blocked_target"
    assert captured.value.stage == "ssrf"
    assert requested is False


@pytest.mark.asyncio
async def test_redirect_to_metadata_ip_is_revalidated_and_blocked() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://169.254.169.254/latest/meta-data"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WebToolError) as captured:
            await web_fetch(
                "https://example.com/redirect",
                tool_execution_id="tool-fetch-redirect",
                client=client,
                resolver=_public_resolver,
            )
    assert captured.value.code == "blocked_target"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_dns_rebinding_is_detected_after_response() -> None:
    resolution_count = 0

    async def rebinding_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        nonlocal resolution_count
        resolution_count += 1
        return ("93.184.216.34",) if resolution_count == 1 else ("192.168.10.10",)

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="must not be accepted",
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(WebToolError) as captured:
            await web_fetch(
                "https://example.com/rebind",
                tool_execution_id="tool-fetch-rebind",
                client=client,
                resolver=rebinding_resolver,
            )
    assert captured.value.code == "dns_rebinding_detected"
    assert resolution_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "content", "expected_code"),
    [
        (
            {"content-type": "text/plain", "content-length": "9999"},
            b"small body",
            "response_too_large",
        ),
        (
            {"content-type": "text/plain"},
            b"body larger than the policy limit",
            "response_too_large",
        ),
        (
            {"content-type": "application/octet-stream"},
            b"binary",
            "unsupported_content_type",
        ),
    ],
)
async def test_response_size_and_content_type_limits(
    headers: dict[str, str], content: bytes, expected_code: str
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, headers=headers, content=content)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(WebToolError) as captured:
            await web_fetch(
                "https://example.com/limited",
                tool_execution_id="tool-fetch-limits",
                policy=WebToolPolicy(max_response_bytes=12),
                client=client,
                resolver=_public_resolver,
            )
    assert captured.value.code == expected_code


@pytest.mark.asyncio
async def test_web_client_factory_keeps_tls_verification_and_explicit_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    profile = TrustProfile(
        ssl_context=ssl.create_default_context(),
        bundle_path=None,
        company_ca_path=None,
        source="test",
    )

    def fake_create_http_client(
        selected_profile: TrustProfile,
        *,
        options: HttpClientOptions | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.AsyncClient:
        captured["profile"] = selected_profile
        captured["options"] = options
        captured["headers"] = headers
        return httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200, headers={"content-type": "text/plain"}, text="ok"
                )
            )
        )

    monkeypatch.setattr(web_module, "create_http_client", fake_create_http_client)
    client = create_web_http_client(
        WebToolPolicy(proxy="http://approved-proxy.example:8080"),
        trust_profile=profile,
    )
    try:
        assert captured["profile"] is profile
        options = captured["options"]
        assert isinstance(options, HttpClientOptions)
        assert options.proxy == "http://approved-proxy.example:8080"
        assert options.trust_env is False
        assert options.follow_redirects is False
        assert options.timeout_seconds == 45.0
        headers = captured["headers"]
        assert isinstance(headers, dict)
        assert headers["User-Agent"].startswith("Mozilla/5.0 ")
        assert "application/rss+xml" in headers["Accept"]
        assert headers["Accept-Language"].startswith("ko-KR")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_query_limits_and_transport_timeout() -> None:
    with pytest.raises(WebToolError) as query_error:
        await web_search(
            "query that is too long",
            tool_execution_id="tool-search-limit",
            policy=WebToolPolicy(max_query_chars=5),
            resolver=_public_resolver,
        )
    assert query_error.value.code == "query_too_long"

    async def slow_handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="late")

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow_handler)) as client:
        with pytest.raises(WebToolError) as timeout_error:
            await web_fetch(
                "https://example.com/slow",
                tool_execution_id="tool-fetch-timeout",
                policy=WebToolPolicy(timeout_seconds=0.001),
                client=client,
                resolver=_public_resolver,
            )
    assert timeout_error.value.code == "request_timeout"
