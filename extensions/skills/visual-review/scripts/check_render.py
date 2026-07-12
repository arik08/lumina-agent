#!/usr/bin/env python3
"""Basic browser-rendered QA checks for HTML visual artifacts."""

from __future__ import annotations

import argparse
import json
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
    parser = argparse.ArgumentParser(description="Check rendered HTML for common visual issues")
    parser.add_argument("source", help="Local HTML file path or URL")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--settle-ms", type=int, default=500)
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("Playwright is not installed. Install with: python -m pip install playwright && python -m playwright install chromium", file=sys.stderr)
        return 2

    console_errors: list[str] = []
    page_errors: list[str] = []
    url = to_url(args.source)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.goto(url, wait_until="networkidle")
        if args.settle_ms > 0:
            time.sleep(args.settle_ms / 1000)

        result = page.evaluate(
            """
            () => {
              const doc = document.documentElement;
              const body = document.body;
              const vw = window.innerWidth;
              const vh = window.innerHeight;
              const scrollWidth = Math.max(doc.scrollWidth, body ? body.scrollWidth : 0);
              const scrollHeight = Math.max(doc.scrollHeight, body ? body.scrollHeight : 0);
              const offenders = [];
              for (const el of document.querySelectorAll('body *')) {
                const r = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                if (r.width <= 0 || r.height <= 0 || style.display === 'none' || style.visibility === 'hidden') continue;
                if (r.right > scrollWidth + 2 || r.left < -2 || r.bottom > scrollHeight + 2) {
                  offenders.push({ tag: el.tagName.toLowerCase(), className: el.className || '', text: (el.innerText || '').slice(0, 80), rect: { left: r.left, right: r.right, top: r.top, bottom: r.bottom }});
                  if (offenders.length >= 20) break;
                }
              }
              const emptyImages = Array.from(document.images).filter(img => !img.complete || img.naturalWidth === 0).map(img => img.src).slice(0, 20);
              return { viewport: { width: vw, height: vh }, scrollWidth, scrollHeight, horizontalOverflow: scrollWidth > vw + 2, offenders, emptyImages };
            }
            """
        )
        browser.close()

    result["consoleErrors"] = console_errors[:20]
    result["pageErrors"] = page_errors[:20]
    print(json.dumps(result, ensure_ascii=False, indent=2))

    has_issue = bool(result["horizontalOverflow"] or result["offenders"] or result["emptyImages"] or console_errors or page_errors)
    return 1 if has_issue else 0


if __name__ == "__main__":
    raise SystemExit(main())
