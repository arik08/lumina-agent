#!/usr/bin/env python3
"""Lightweight static checks for a SKILL.md folder."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - MyHarness depends on PyYAML, but keep a clear error.
    yaml = None

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SUSPICIOUS_PATTERNS = [
    (re.compile(r"\brm\s+-rf\b", re.I), "destructive rm -rf command"),
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.I), "destructive git reset"),
    (re.compile(r"\bgit\s+push\b.*\b--force\b", re.I), "force push command"),
    (re.compile(r"\bcurl\b.*\|\s*(?:sh|bash|powershell)\b", re.I), "pipe remote script to shell"),
    (re.compile(r"\bInvoke-WebRequest\b.*\|\s*(?:iex|Invoke-Expression)\b", re.I), "PowerShell remote execution"),
    (re.compile(r"\bEncodedCommand\b", re.I), "encoded PowerShell command"),
    (re.compile(r"\bignore (?:all )?(?:previous|above) instructions\b", re.I), "prompt injection phrase"),
    (re.compile(r"\bsystem prompt\b.*\b(reveal|print|exfiltrate|dump)\b", re.I), "system prompt extraction"),
    (re.compile(r"\b(api[_-]?key|secret|token|password)\b", re.I), "credential-related text"),
]


def line_for(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def add(findings: list[dict[str, Any]], severity: str, message: str, path: Path, line: int | None = None) -> None:
    item: dict[str, Any] = {"severity": severity, "message": message, "path": str(path)}
    if line is not None:
        item["line"] = line
    findings.append(item)


def parse_frontmatter(content: str) -> tuple[dict[str, Any] | None, str | None]:
    if not content.startswith("---\n"):
        return None, "missing YAML frontmatter"
    end = content.find("\n---\n", 4)
    if end == -1:
        return None, "unterminated YAML frontmatter"
    if yaml is None:
        return None, "PyYAML is not installed"
    try:
        data = yaml.safe_load(content[4:end])
    except Exception as exc:  # noqa: BLE001 - report parser details.
        return None, f"invalid YAML frontmatter: {exc}"
    if not isinstance(data, dict):
        return None, "frontmatter must be a mapping"
    return data, None


def scan_text(path: Path, root: Path, findings: list[dict[str, Any]]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        add(findings, "P1", "file is not valid UTF-8", path.relative_to(root))
        return
    for pattern, message in SUSPICIOUS_PATTERNS:
        for match in pattern.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.start())
            if line_end == -1:
                line_end = len(text)
            line_text = text[line_start:line_end]
            if "re.compile(" in line_text or "SUSPICIOUS_PATTERNS" in line_text:
                continue
            add(findings, "P1", message, path.relative_to(root), line_for(text, match.start()))
    for line_number, line_text in enumerate(text.splitlines(), start=1):
        if "TODO" in line_text and "contains TODO placeholder text" not in line_text:
            add(findings, "P2", "contains TODO placeholder text", path.relative_to(root), line_number)
            break


def lint_skill(path: Path) -> dict[str, Any]:
    skill_dir = path.parent if path.name == "SKILL.md" else path
    skill_md = skill_dir / "SKILL.md"
    findings: list[dict[str, Any]] = []

    if not skill_md.exists():
        add(findings, "P0", "SKILL.md not found", skill_dir)
        return {"skill_dir": str(skill_dir), "verdict": "do not install", "findings": findings}

    try:
        content = skill_md.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        add(findings, "P0", "SKILL.md is not valid UTF-8", skill_md)
        return {"skill_dir": str(skill_dir), "verdict": "do not install", "findings": findings}

    frontmatter, error = parse_frontmatter(content)
    if error:
        add(findings, "P0", error, skill_md.relative_to(skill_dir))
    else:
        extra_keys = sorted(set(frontmatter or {}) - {"name", "description"})
        if extra_keys:
            add(findings, "P2", f"frontmatter has nonstandard keys: {', '.join(extra_keys)}", skill_md.relative_to(skill_dir))

        name = str((frontmatter or {}).get("name") or "")
        description = str((frontmatter or {}).get("description") or "")
        if not NAME_RE.match(name):
            add(findings, "P1", "name must be lowercase hyphen-case, <=64 chars", skill_md.relative_to(skill_dir), 2)
        if len(description.strip()) < 80:
            add(findings, "P2", "description is probably too short to trigger precisely", skill_md.relative_to(skill_dir), 3)
        if not re.search(r"\b(use|trigger|when)\b", description, re.I):
            add(findings, "P2", "description should say when to use the skill", skill_md.relative_to(skill_dir), 3)
        if len(description) > 900:
            add(findings, "P3", "description is very long; consider tightening trigger text", skill_md.relative_to(skill_dir), 3)

    lines = content.splitlines()
    if len(lines) > 500:
        add(findings, "P2", "SKILL.md is over 500 lines; move optional detail to references", skill_md.relative_to(skill_dir))
    scan_text(skill_md, skill_dir, findings)

    agents_yaml = skill_dir / "agents" / "openai.yaml"
    if not agents_yaml.exists():
        add(findings, "P3", "agents/openai.yaml is missing; UI metadata is recommended", agents_yaml.relative_to(skill_dir))
    else:
        scan_text(agents_yaml, skill_dir, findings)

    for child in skill_dir.iterdir():
        if child.name.upper() in {"README.md", "CHANGELOG.md", "INSTALLATION_GUIDE.md", "QUICK_REFERENCE.md"}:
            add(findings, "P3", f"auxiliary documentation may be unnecessary: {child.name}", child.relative_to(skill_dir))

    for folder_name in ("scripts", "references"):
        folder = skill_dir / folder_name
        if not folder.exists():
            continue
        for item in folder.rglob("*"):
            if item.is_file() and item.stat().st_size <= 2_000_000:
                scan_text(item, skill_dir, findings)
            elif item.is_file():
                add(findings, "P2", "large file should not be loaded into context casually", item.relative_to(skill_dir))

    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    findings.sort(key=lambda item: (severity_order.get(item["severity"], 9), item["path"], item.get("line", 0)))
    severities = {item["severity"] for item in findings}
    if "P0" in severities:
        verdict = "do not install"
    elif "P1" in severities or "P2" in severities:
        verdict = "needs changes"
    else:
        verdict = "ready"

    return {
        "skill_dir": str(skill_dir.resolve()),
        "verdict": verdict,
        "finding_count": len(findings),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint a MyHarness/Codex skill folder.")
    parser.add_argument("path", help="Skill directory or SKILL.md path")
    args = parser.parse_args()
    result = lint_skill(Path(args.path).expanduser().resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["verdict"] == "do not install" else 0


if __name__ == "__main__":
    raise SystemExit(main())
