from __future__ import annotations

import re
from typing import Any, cast

from .model import (
    REPORT_FORMATS,
    GeneratedReport,
    ReportDocument,
    ReportFormat,
    ReportImage,
    normalize_report_document,
)


_FORMAT_METADATA: dict[ReportFormat, tuple[str, str, str]] = {
    "html": ("html", "html", "text/html"),
    "markdown": ("md", "markdown", "text/markdown"),
    "docx": (
        "docx",
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "xlsx": (
        "xlsx",
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "pptx": (
        "pptx",
        "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    "pdf": ("pdf", "pdf", "application/pdf"),
}


def _report_display_name(title: str, extension: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)
    stem = re.sub(r"\s+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip(" ._")
    suffix = f".{extension}"
    if stem.casefold().endswith(suffix.casefold()):
        stem = stem[: -len(suffix)].rstrip(" ._")
    return f"{stem or '작업_결과_보고서'}.{extension}"


def generate_report(
    request: str,
    arguments: dict[str, Any],
    *,
    images: tuple[ReportImage, ...] = (),
) -> GeneratedReport:
    raw_format = arguments.get("format", "html")
    if not isinstance(raw_format, str) or raw_format not in REPORT_FORMATS:
        allowed = ", ".join(REPORT_FORMATS)
        raise ValueError(f"지원하지 않는 보고서 형식입니다. 허용 형식: {allowed}")
    report_format = cast(ReportFormat, raw_format)
    if images and report_format not in {"html", "docx"}:
        raise ValueError(
            "본문 이미지 자산은 현재 HTML 또는 DOCX 보고서에서 지원합니다."
        )
    raw_html_source = arguments.get("html_source")
    if raw_html_source is not None:
        if report_format != "html":
            raise ValueError("html_source는 HTML 보고서에서만 사용할 수 있습니다.")
        if not isinstance(raw_html_source, str) or not raw_html_source.strip():
            raise ValueError("html_source는 비어 있지 않은 문자열이어야 합니다.")
        if images:
            raise ValueError(
                "html_source와 이미지 참조를 함께 사용할 수 없습니다. "
                "완성 HTML에는 허용된 이미지 데이터를 직접 포함해야 합니다."
            )
        from ..service import validate_artifact_content

        source = raw_html_source.encode("utf-8")
        status, validation = validate_artifact_content(
            kind="html", mime_type="text/html", content=source
        )
        if status == "failed":
            errors = ", ".join(str(item) for item in validation["errors"])
            raise ValueError(f"HTML 보고서 안전성 검증에 실패했습니다: {errors}")
        title = str(arguments.get("title") or "작업 결과 보고서")
        return GeneratedReport(
            format="html",
            display_name=_report_display_name(title, "html"),
            kind="html",
            mime_type="text/html",
            content=source,
            asset_manifest=(),
        )
    document = normalize_report_document(request, arguments, images=images)
    extension, kind, mime_type = _FORMAT_METADATA[report_format]
    return GeneratedReport(
        format=report_format,
        display_name=_report_display_name(document.title, extension),
        kind=kind,
        mime_type=mime_type,
        content=_generate_content(report_format, document),
        asset_manifest=tuple(
            {
                "sourceType": image.source_type,
                "sourceId": image.source_id,
                "sourceVersion": image.source_version,
                "displayName": image.display_name,
                "mimeType": image.mime_type,
                "contentHash": image.content_hash,
                "embedded": True,
            }
            for image in images
        ),
    )


def _generate_content(report_format: ReportFormat, document: ReportDocument) -> bytes:
    if report_format == "html":
        from .html import generate_html

        return generate_html(document)
    if report_format == "markdown":
        from .markdown import generate_markdown

        return generate_markdown(document)
    if report_format == "docx":
        from .docx import generate_docx

        return generate_docx(document)
    if report_format == "xlsx":
        from .xlsx import generate_xlsx

        return generate_xlsx(document)
    if report_format == "pptx":
        from .pptx import generate_pptx

        return generate_pptx(document)
    from .pdf import generate_pdf

    return generate_pdf(document)
