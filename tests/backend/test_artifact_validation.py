import pytest

from lumina.agent.executor import _report_html
from lumina.artifacts.service import validate_artifact_content


def test_structured_report_uses_model_fields_and_escapes_active_content() -> None:
    source = _report_html(
        "설비 상태를 정리해 주세요.",
        {
            "title": "광양 설비 점검 보고서",
            "executive_summary": "핵심 설비 2건을 확인했습니다.",
            "key_metrics": [{"label": "점검 설비", "value": "2건"}],
            "sections": [
                {
                    "heading": "점검 결과",
                    "body": "이상 징후 <script>alert(1)</script> 1건",
                    "bullets": ["베어링 온도 확인", "담당자 재점검"],
                }
            ],
            "action_items": ["48시간 안에 재점검"],
        },
    )

    assert "광양 설비 점검 보고서" in source
    assert "핵심 설비 2건" in source
    assert "48시간 안에 재점검" in source
    assert "<script>alert(1)</script>" not in source
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in source

    status, validation = validate_artifact_content(
        kind="html", mime_type="text/html", content=source.encode()
    )
    assert status == "structural_passed"
    assert validation["errors"] == []
    assert validation["renderVerified"] is False
    assert validation["warnings"] == ["render_verification_pending"]


def test_html_validation_allows_executable_javascript() -> None:
    status, validation = validate_artifact_content(
        kind="html",
        mime_type="text/html",
        content=(
            b"<!doctype html><html><head><title>x</title></head>"
            b'<body onload="run()"><button onclick="run()">Run</button>'
            b"<script>function run(){document.body.dataset.ran='true'}</script></body></html>"
        ),
    )

    assert status == "structural_passed"
    assert validation["errors"] == []
    assert "executable_content" in validation["checks"]


def test_binary_validation_checks_real_file_signature() -> None:
    status, validation = validate_artifact_content(
        kind="pdf", mime_type="application/pdf", content=b"not a pdf"
    )
    assert status == "failed"
    assert validation["errors"] == ["invalid_pdf_signature"]


@pytest.mark.parametrize(
    ("kind", "mime_type", "content", "expected_error"),
    [
        (
            "docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK-not-a-docx",
            "invalid_docx_structure",
        ),
        (
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            b"PK-not-an-xlsx",
            "invalid_xlsx_structure",
        ),
        (
            "pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            b"PK-not-a-pptx",
            "invalid_pptx_structure",
        ),
        (
            "pdf",
            "application/pdf",
            b"%PDF-not-a-pdf",
            "invalid_pdf_structure",
        ),
    ],
)
def test_binary_validation_reopens_declared_document_format(
    kind: str, mime_type: str, content: bytes, expected_error: str
) -> None:
    status, validation = validate_artifact_content(
        kind=kind, mime_type=mime_type, content=content
    )

    assert status == "failed"
    assert expected_error in validation["errors"]
