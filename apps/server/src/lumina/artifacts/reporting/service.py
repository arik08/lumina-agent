from __future__ import annotations

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
    document = normalize_report_document(request, arguments, images=images)
    extension, kind, mime_type = _FORMAT_METADATA[report_format]
    return GeneratedReport(
        format=report_format,
        display_name=f"Lumina_작업_보고서.{extension}",
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
