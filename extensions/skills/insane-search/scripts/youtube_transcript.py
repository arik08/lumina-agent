#!/usr/bin/env python3
"""Extract a YouTube transcript with yt-dlp metadata.

This is intentionally a small reusable helper for agent workflows:
pass a video URL, get clean transcript text and basic metadata without
PowerShell redirection or one-off inline Python.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any


DEFAULT_LANGS = ("ko-orig", "ko", "en")
DEFAULT_EXTS = ("json3", "vtt", "srv3", "srv2", "srv1")


def run_ytdlp(url: str, timeout: int) -> dict[str, Any]:
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp is not installed or not on PATH")

    proc = subprocess.run(
        ["yt-dlp", "--dump-json", "--skip-download", url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"yt-dlp failed with exit {proc.returncode}: {detail[:1000]}")

    stdout = proc.stdout.strip()
    if not stdout:
        raise RuntimeError("yt-dlp produced no JSON")

    # yt-dlp normally emits one JSON object. Be tolerant if multiple JSON lines
    # appear and use the first object-like line.
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    return json.loads(stdout)


def choose_track(data: dict[str, Any], langs: tuple[str, ...], exts: tuple[str, ...]) -> tuple[str, str, dict[str, Any]] | None:
    pools = (
        ("subtitles", data.get("subtitles") or {}),
        ("automatic_captions", data.get("automatic_captions") or {}),
    )

    for lang in langs:
        for source, captions in pools:
            tracks = captions.get(lang) or []
            if not tracks:
                continue
            for ext in exts:
                for track in tracks:
                    if track.get("ext") == ext and track.get("url"):
                        return source, lang, track
            for track in tracks:
                if track.get("url"):
                    return source, lang, track
    return None


def fetch_text(url: str, timeout: int) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", "replace")


def parse_json3(raw: str) -> list[str]:
    obj = json.loads(raw)
    parts: list[str] = []
    for event in obj.get("events", []):
        text = "".join(seg.get("utf8", "") for seg in event.get("segs") or [])
        text = normalize_text(text)
        if text:
            parts.append(text)
    return parts


def parse_vtt(raw: str) -> list[str]:
    parts: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line or re.match(r"^\d+$", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = normalize_text(html.unescape(line))
        if line:
            parts.append(line)
    return parts


def parse_srv(raw: str) -> list[str]:
    parts: list[str] = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return parse_vtt(raw)
    for node in root.iter():
        if node.text:
            text = normalize_text(html.unescape(node.text))
            if text:
                parts.append(text)
    return parts


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\n", " ")).strip()


def dedupe_consecutive(parts: list[str]) -> list[str]:
    clean: list[str] = []
    for part in parts:
        if part and (not clean or clean[-1] != part):
            clean.append(part)
    return clean


def build_payload(url: str, langs: tuple[str, ...], exts: tuple[str, ...], timeout: int) -> dict[str, Any]:
    data = run_ytdlp(url, timeout=timeout)
    selected = choose_track(data, langs=langs, exts=exts)
    if not selected:
        return {
            "ok": False,
            "reason": "NO_CAPTIONS",
            "url": url,
            "title": data.get("title"),
            "duration": data.get("duration"),
            "uploader": data.get("uploader"),
            "available_subtitles": sorted((data.get("subtitles") or {}).keys()),
            "available_automatic_captions": sorted((data.get("automatic_captions") or {}).keys()),
            "transcript": "",
        }

    source, lang, track = selected
    raw = fetch_text(track["url"], timeout=timeout)
    ext = track.get("ext") or ""
    if ext == "json3":
        parts = parse_json3(raw)
    elif ext == "vtt":
        parts = parse_vtt(raw)
    elif ext.startswith("srv"):
        parts = parse_srv(raw)
    else:
        parts = parse_vtt(raw)
    parts = dedupe_consecutive(parts)

    return {
        "ok": bool(parts),
        "reason": None if parts else "EMPTY_CAPTIONS",
        "url": url,
        "webpage_url": data.get("webpage_url"),
        "id": data.get("id"),
        "title": data.get("title"),
        "duration": data.get("duration"),
        "uploader": data.get("uploader"),
        "caption_source": source,
        "caption_language": lang,
        "caption_ext": ext,
        "caption_name": track.get("name"),
        "line_count": len(parts),
        "transcript": "\n".join(parts),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract YouTube transcript text via yt-dlp.")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--langs", default=",".join(DEFAULT_LANGS), help="Comma-separated language priority")
    parser.add_argument("--exts", default=",".join(DEFAULT_EXTS), help="Comma-separated caption format priority")
    parser.add_argument("--timeout", type=int, default=120, help="Network/subprocess timeout seconds")
    parser.add_argument("--json", action="store_true", help="Emit full JSON payload")
    parser.add_argument("--max-chars", type=int, default=0, help="Truncate transcript in text mode")
    parser.add_argument("--output", help="Write output to this UTF-8 file instead of stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    langs = tuple(x.strip() for x in args.langs.split(",") if x.strip())
    exts = tuple(x.strip() for x in args.exts.split(",") if x.strip())

    try:
        payload = build_payload(args.url, langs=langs, exts=exts, timeout=args.timeout)
    except Exception as exc:
        print(f"youtube_transcript error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        output = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        lines = [
            f"TITLE: {payload.get('title') or ''}",
            f"DURATION: {payload.get('duration') or ''}",
            f"UPLOADER: {payload.get('uploader') or ''}",
        ]
        if not payload.get("ok"):
            lines.append(f"NO_TRANSCRIPT: {payload.get('reason') or 'UNKNOWN'}")
        else:
            lines.extend(
                [
                    "CAPTION: "
                    f"{payload.get('caption_language')} "
                    f"{payload.get('caption_source')} "
                    f"{payload.get('caption_ext')}",
                    "",
                ]
            )
            transcript = payload.get("transcript") or ""
            if args.max_chars and len(transcript) > args.max_chars:
                transcript = transcript[: args.max_chars].rstrip() + "\n...[truncated]"
            lines.append(transcript)
        output = "\n".join(lines)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)

    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
