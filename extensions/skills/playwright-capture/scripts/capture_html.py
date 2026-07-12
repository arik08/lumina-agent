#!/usr/bin/env python3
"""Render an HTML file or URL to PNG and/or PDF with Playwright."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


def to_url(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https", "file"}:
        return source
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {path}")
    return path.as_uri()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture HTML/URL to PNG and/or PDF")
    parser.add_argument("source", help="Local HTML file path or http(s)/file URL")
    parser.add_argument("--png", help="Output PNG path")
    parser.add_argument("--pdf", help="Output PDF path")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--no-full-page", action="store_true", help="Capture only viewport for PNG")
    parser.add_argument("--settle-ms", type=int, default=500, help="Extra wait after load")
    args = parser.parse_args()

    if not args.png and not args.pdf:
        parser.error("Provide --png and/or --pdf")

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("Playwright is not installed. Install with: python -m pip install playwright && python -m playwright install chromium", file=sys.stderr)
        return 2

    url = to_url(args.source)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height}, device_scale_factor=1)
        page.goto(url, wait_until="networkidle")
        if args.settle_ms > 0:
            time.sleep(args.settle_ms / 1000)

        if args.png:
            out = Path(args.png).expanduser().resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out), full_page=not args.no_full_page)
            print(f"PNG: {out}")

        if args.pdf:
            out = Path(args.pdf).expanduser().resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            page.pdf(path=str(out), print_background=True, prefer_css_page_size=True)
            print(f"PDF: {out}")

        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
