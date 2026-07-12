from __future__ import annotations

from .model import ReportDocument


def generate_markdown(document: ReportDocument) -> bytes:
    lines = [
        f"# {document.title}",
        "",
        "**LUMINA · AGENT REPORT**",
        "",
        document.executive_summary,
        "",
        "## 핵심 지표",
        "",
        "| 지표 | 값 |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {_table_text(metric.label)} | {_table_text(metric.value)} |"
        for metric in document.metrics
    )
    lines.extend(["", "## 원 요청", "", f"> {_quote_text(document.request)}", ""])
    for section in document.sections:
        lines.extend([f"## {section.heading}", ""])
        if section.body:
            lines.extend([section.body, ""])
        lines.extend(f"- {item}" for item in section.bullets)
        if section.bullets:
            lines.append("")
    if document.action_items:
        lines.extend(["## 후속 조치", ""])
        lines.extend(
            f"{index}. {item}"
            for index, item in enumerate(document.action_items, start=1)
        )
        lines.append("")
    lines.extend(
        [
            "---",
            "",
            "이 문서는 Lumina가 생성한 편집 가능한 Artifact입니다.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def _table_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _quote_text(value: str) -> str:
    return value.replace("\n", "\n> ")
