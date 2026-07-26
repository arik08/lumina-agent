from __future__ import annotations

from lumina.artifacts.standalone_html import (
    MERMAID_CDN_VERSION,
    prepare_standalone_html_download,
)


def test_mermaid_html_download_adds_pinned_standalone_runtime() -> None:
    source = (
        b'<!doctype html><html><body><div class="mermaid">'
        b"flowchart TD\nA-->B"
        b"</div></body></html>"
    )

    downloaded = prepare_standalone_html_download(source, "text/html")

    assert downloaded != source
    assert (
        f"https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_CDN_VERSION}/dist/"
        "mermaid.min.js"
    ).encode() in downloaded
    assert b'data-lumina-standalone-mermaid="11.16.0"' in downloaded
    assert b'querySelector: ".mermaid"' in downloaded
    assert "Mermaid 다이어그램 크게 보기".encode() in downloaded
    assert downloaded.index(b"mermaid.min.js") < downloaded.index(b"</body>")


def test_standalone_download_transform_is_conditional_and_idempotent() -> None:
    plain_html = b"<!doctype html><html><body><p>plain</p></body></html>"
    markdown = b'<div class="mermaid">flowchart TD\nA-->B</div>'
    existing_runtime = (
        b'<div class="mermaid">flowchart TD\nA-->B</div>'
        b'<script src="https://example.com/mermaid.min.js"></script>'
    )

    assert prepare_standalone_html_download(plain_html, "text/html") is plain_html
    assert prepare_standalone_html_download(markdown, "text/markdown") is markdown
    assert (
        prepare_standalone_html_download(existing_runtime, "text/html")
        is existing_runtime
    )

    transformed = prepare_standalone_html_download(markdown, "text/html")
    assert prepare_standalone_html_download(transformed, "text/html") is transformed


def test_mermaid_html_fragment_receives_runtime_at_the_end() -> None:
    fragment = b'<section class="mermaid">flowchart LR\nA-->B</section>'

    downloaded = prepare_standalone_html_download(fragment, "text/html")

    assert downloaded.startswith(fragment)
    assert downloaded.rstrip().endswith(b"</script>")


def test_bare_pre_mermaid_download_is_recovered_and_rendered() -> None:
    source = (
        b"<!doctype html><html><body><pre>\n"
        b"flowchart TD\nA[Research] --> B[Report]\n"
        b"</pre></body></html>"
    )

    downloaded = prepare_standalone_html_download(source, "text/html")

    assert downloaded != source
    assert b'data-lumina-standalone-mermaid="11.16.0"' in downloaded
    assert b'const isMermaidSource = (source)' in downloaded
    assert b'document.querySelectorAll("pre")' in downloaded
    assert b'element.className = "mermaid"' in downloaded
