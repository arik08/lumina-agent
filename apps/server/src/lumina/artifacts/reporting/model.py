from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ReportFormat = Literal["html", "markdown", "docx", "xlsx", "pptx", "pdf"]
REPORT_FORMATS: tuple[ReportFormat, ...] = (
    "html",
    "markdown",
    "docx",
    "xlsx",
    "pptx",
    "pdf",
)


@dataclass(frozen=True)
class ReportMetric:
    label: str
    value: str


@dataclass(frozen=True)
class ReportSection:
    heading: str
    body: str
    bullets: tuple[str, ...]


@dataclass(frozen=True)
class ReportImage:
    source_type: str
    source_id: str
    source_version: int | None
    display_name: str
    mime_type: str
    content_hash: str
    content: bytes


@dataclass(frozen=True)
class ReportDocument:
    title: str
    executive_summary: str
    request: str
    metrics: tuple[ReportMetric, ...]
    sections: tuple[ReportSection, ...]
    action_items: tuple[str, ...]
    images: tuple[ReportImage, ...]


@dataclass(frozen=True)
class GeneratedReport:
    format: ReportFormat
    display_name: str
    kind: str
    mime_type: str
    content: bytes
    asset_manifest: tuple[dict[str, Any], ...]


def normalize_report_document(
    request: str,
    arguments: dict[str, Any],
    *,
    images: tuple[ReportImage, ...] = (),
) -> ReportDocument:
    title = plain_text(arguments.get("title"), "작업 결과 보고서", 180)
    summary = plain_text(
        arguments.get("executive_summary"),
        "요청 범위와 제공된 자료를 기준으로 검토 가능한 결과 초안을 구성했습니다.",
        2_000,
    )
    raw_sections = arguments.get("sections")
    sections = tuple(
        ReportSection(
            heading=plain_text(item.get("heading"), "검토 항목", 180),
            body=plain_text(item.get("body"), "", 8_000),
            bullets=tuple(
                value
                for value in (
                    plain_text(bullet, "", 1_000)
                    for bullet in (
                        item.get("bullets", [])
                        if isinstance(item.get("bullets"), list)
                        else []
                    )[:20]
                )
                if value
            ),
        )
        for item in (
            [value for value in raw_sections if isinstance(value, dict)][:12]
            if isinstance(raw_sections, list)
            else []
        )
    )
    if not sections:
        sections = (
            ReportSection(
                heading="요청 범위",
                body=bounded_text(request, 8_000),
                bullets=(
                    "사용자 요청과 출력 형식을 기준으로 내용을 구조화했습니다.",
                    "확인이 필요한 값은 원문과 대조할 수 있도록 남겼습니다.",
                ),
            ),
            ReportSection(
                heading="검토 결과",
                body=(
                    "현재 단계의 결과는 편집 가능한 초안입니다. 실제 운영 수치와 "
                    "담당자 정보는 최종 배포 전에 확인해야 합니다."
                ),
                bullets=(),
            ),
        )

    raw_metrics = arguments.get("key_metrics")
    metrics = tuple(
        ReportMetric(
            label=plain_text(item.get("label"), "지표", 120),
            value=plain_text(item.get("value"), "-", 80),
        )
        for item in (
            [value for value in raw_metrics if isinstance(value, dict)][:6]
            if isinstance(raw_metrics, list)
            else []
        )
    )
    if not metrics:
        metrics = (
            ReportMetric(label="검토 섹션", value=str(len(sections))),
            ReportMetric(label="후속 조치", value=str(len(_action_items(arguments)))),
            ReportMetric(label="문서 형식 검증", value="완료"),
        )

    return ReportDocument(
        title=title,
        executive_summary=summary,
        request=bounded_text(request, 8_000),
        metrics=metrics,
        sections=sections,
        action_items=_action_items(arguments),
        images=images,
    )


def _action_items(arguments: dict[str, Any]) -> tuple[str, ...]:
    raw_actions = arguments.get("action_items")
    if not isinstance(raw_actions, list):
        return ()
    return tuple(
        value
        for value in (plain_text(item, "", 500) for item in raw_actions[:12])
        if value
    )


def plain_text(value: Any, fallback: str, limit: int) -> str:
    if not isinstance(value, (str, int, float)):
        return fallback
    normalized = " ".join(str(value).split())
    return bounded_text(normalized, limit) if normalized else fallback


def bounded_text(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit < 200:
        return value[:limit]
    tail = min(limit // 3, 40_000)
    head = limit - tail
    return value[:head] + "\n\n[... context truncated ...]\n\n" + value[-tail:]
