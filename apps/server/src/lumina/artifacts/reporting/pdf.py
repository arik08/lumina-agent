from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    ListFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .model import ReportDocument
from .theme import COBALT_HEX, INK_HEX, LIGHT_BLUE_HEX, MUTED_HEX


_COBALT = colors.HexColor(f"#{COBALT_HEX}")
_INK = colors.HexColor(f"#{INK_HEX}")
_MUTED = colors.HexColor(f"#{MUTED_HEX}")
_LIGHT_BLUE = colors.HexColor(f"#{LIGHT_BLUE_HEX}")


def generate_pdf(report: ReportDocument) -> bytes:
    regular_font, bold_font = _register_fonts()
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=0.8 * inch,
        leftMargin=0.8 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.7 * inch,
        title=report.title,
        author="Lumina Agent",
        subject="Lumina professional report artifact",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "LuminaTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=22,
        leading=28,
        textColor=_INK,
        alignment=0,
        spaceAfter=10,
    )
    kicker_style = ParagraphStyle(
        "LuminaKicker",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=9,
        leading=12,
        textColor=_COBALT,
        spaceAfter=6,
    )
    heading_style = ParagraphStyle(
        "LuminaHeading",
        parent=styles["Heading2"],
        fontName=bold_font,
        fontSize=14,
        leading=18,
        textColor=_COBALT,
        spaceBefore=14,
        spaceAfter=7,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "LuminaBody",
        parent=styles["BodyText"],
        fontName=regular_font,
        fontSize=10.5,
        leading=16,
        textColor=_INK,
        spaceAfter=7,
    )
    muted_style = ParagraphStyle(
        "LuminaMuted",
        parent=body_style,
        fontSize=8,
        leading=11,
        textColor=_MUTED,
        alignment=TA_CENTER,
        spaceBefore=16,
    )

    story: list[Flowable] = [
        Paragraph("LUMINA · AGENT REPORT", kicker_style),
        Paragraph(_markup(report.title), title_style),
        Paragraph(_markup(report.executive_summary), body_style),
        Spacer(1, 0.08 * inch),
        Paragraph("핵심 지표", heading_style),
    ]
    metric_rows = [
        [
            Paragraph(
                "지표",
                ParagraphStyle("MetricHeader", parent=body_style, fontName=bold_font),
            ),
            Paragraph(
                "값",
                ParagraphStyle(
                    "MetricHeaderValue", parent=body_style, fontName=bold_font
                ),
            ),
        ]
    ]
    metric_rows.extend(
        [
            Paragraph(_markup(metric.label), body_style),
            Paragraph(_markup(metric.value), body_style),
        ]
        for metric in report.metrics
    )
    metric_table = Table(metric_rows, colWidths=[4.7 * inch, 1.5 * inch], repeatRows=1)
    metric_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _LIGHT_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, -1), _INK),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#DCE3EF")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            metric_table,
            Paragraph("원 요청", heading_style),
            Paragraph(_markup(report.request), body_style),
        ]
    )
    for section in report.sections:
        story.append(Paragraph(_markup(section.heading), heading_style))
        if section.body:
            story.append(Paragraph(_markup(section.body), body_style))
        if section.bullets:
            story.append(
                ListFlowable(
                    [Paragraph(_markup(item), body_style) for item in section.bullets],
                    bulletType="bullet",
                    leftIndent=18,
                    bulletFontName=regular_font,
                    bulletFontSize=8,
                )
            )
    if report.action_items:
        story.append(Paragraph("후속 조치", heading_style))
        story.append(
            ListFlowable(
                [Paragraph(_markup(item), body_style) for item in report.action_items],
                bulletType="1",
                leftIndent=24,
                bulletFontName=regular_font,
                bulletFontSize=9,
            )
        )
    story.append(Paragraph("Lumina가 생성한 편집 가능한 Artifact", muted_style))
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return output.getvalue()


def _register_fonts() -> tuple[str, str]:
    regular_name = "LuminaKorean"
    bold_name = "LuminaKoreanBold"
    if regular_name in pdfmetrics.getRegisteredFontNames():
        return regular_name, bold_name
    windir = Path(os.environ.get("WINDIR", "C:/Windows"))
    candidates = [
        (windir / "Fonts" / "malgun.ttf", windir / "Fonts" / "malgunbd.ttf"),
        (
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        ),
        (
            Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
            Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
        ),
    ]
    for regular_path, bold_path in candidates:
        if regular_path.is_file() and bold_path.is_file():
            try:
                pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
                pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
            except Exception:
                continue
            return regular_name, bold_name
    cid_name = "HYSMyeongJo-Medium"
    if cid_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(cid_name))
    return cid_name, cid_name


def _markup(value: str) -> str:
    return escape(value).replace("\n", "<br/>")


def _page_footer(canvas: Canvas, document: BaseDocTemplate) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(_MUTED)
    canvas.drawRightString(A4[0] - 0.8 * inch, 0.38 * inch, f"{document.page}")
    canvas.restoreState()
