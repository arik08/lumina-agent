from __future__ import annotations

import html
import base64

from .model import ReportDocument, ReportSection


def generate_html(document: ReportDocument) -> bytes:
    metric_markup = "".join(
        '<div class="metric"><strong>'
        + html.escape(metric.value)
        + "</strong>"
        + html.escape(metric.label)
        + "</div>"
        for metric in document.metrics
    )
    section_markup = "".join(_section_html(section) for section in document.sections)
    action_markup = (
        "<section><h2>후속 조치</h2><ol>"
        + "".join(f"<li>{html.escape(item)}</li>" for item in document.action_items)
        + "</ol></section>"
        if document.action_items
        else ""
    )
    image_markup = (
        '<section class="images"><h2>이미지 자산</h2>'
        + "".join(
            '<figure><img src="data:'
            + image.mime_type
            + ";base64,"
            + base64.b64encode(image.content).decode("ascii")
            + '" alt="'
            + html.escape(image.display_name)
            + '"><figcaption>'
            + html.escape(image.display_name)
            + "</figcaption></figure>"
            for image in document.images
        )
        + "</section>"
        if document.images
        else ""
    )
    source = f"""<!doctype html>
<html lang=\"ko\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{html.escape(document.title)}</title>
  <style>
    :root {{ color-scheme: light; --blue:#315fbd; --ink:#202631; --muted:#6b7280; }}
    body {{ margin:0; padding:48px; font-family:Arial,'Noto Sans KR',sans-serif; color:var(--ink); background:#fff; }}
    header {{ border-bottom:2px solid var(--blue); padding-bottom:24px; }}
    h1 {{ margin:8px 0; font-size:30px; }} h2 {{ margin-top:32px; font-size:18px; }}
    .kicker {{ color:var(--blue); font-weight:700; }}
    .summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:28px 0; }}
    .metric {{ border-top:1px solid #dce3ef; padding:16px 0; }}
    .metric strong {{ display:block; font-size:24px; color:var(--blue); }}
    blockquote {{ margin:16px 0; padding:16px; background:#f4f7fc; border-left:3px solid var(--blue); }}
    section {{ max-width:920px; }} p,li {{ line-height:1.72; }}
    .meta {{ color:var(--muted); font-size:13px; }}
    .images {{ display:grid; gap:20px; }}
    figure {{ margin:0; }} figure img {{ display:block; max-width:100%; max-height:680px; object-fit:contain; }}
    figcaption {{ margin-top:7px; color:var(--muted); font-size:13px; }}
  </style>
</head>
<body>
  <header><div class=\"kicker\">LUMINA · AGENT REPORT</div><h1>{html.escape(document.title)}</h1><p>{html.escape(document.executive_summary)}</p></header>
  <section class=\"summary\">{metric_markup}</section>
  <section><h2>원 요청</h2><blockquote>{html.escape(document.request)}</blockquote></section>
  {section_markup}
  {action_markup}
  {image_markup}
  <p class=\"meta\">이 문서는 Lumina가 생성한 편집 가능한 Artifact이며 저장된 각 버전은 별도로 검증됩니다.</p>
</body>
</html>"""
    return source.encode("utf-8")


def _section_html(section: ReportSection) -> str:
    body_markup = f"<p>{html.escape(section.body)}</p>" if section.body else ""
    bullet_markup = (
        "<ul>"
        + "".join(f"<li>{html.escape(item)}</li>" for item in section.bullets)
        + "</ul>"
        if section.bullets
        else ""
    )
    return (
        f"<section><h2>{html.escape(section.heading)}</h2>"
        f"{body_markup}{bullet_markup}</section>"
    )
