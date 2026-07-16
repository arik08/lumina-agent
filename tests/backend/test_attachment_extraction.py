from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pptx import Presentation

from lumina.api.routes.attachments import _sniff_mime
from lumina.attachments import extract_attachment_text
from lumina.config import Settings
from lumina.main import create_app


def test_text_extraction_tracks_lines() -> None:
    result = extract_attachment_text(
        filename="inspection.md",
        mime_type="text/markdown",
        content="첫 줄\n둘째 줄".encode(),
    )
    assert result.status == "completed"
    assert result.text == "첫 줄\n둘째 줄"
    assert result.locator_map == {"kind": "line", "count": 2}


def test_office_formats_extract_without_writing_temporary_files() -> None:
    document = Document()
    document.add_heading("설비 점검", level=1)
    document.add_paragraph("베어링 온도를 확인했습니다.")
    docx_buffer = BytesIO()
    document.save(docx_buffer)
    docx = extract_attachment_text(
        filename="inspection.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=docx_buffer.getvalue(),
    )
    assert docx.status == "completed"
    assert "베어링 온도" in docx.text

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "점검"
    sheet.append(["설비", "상태"])
    sheet.append(["압연기", "정상"])
    xlsx_buffer = BytesIO()
    workbook.save(xlsx_buffer)
    workbook.close()
    xlsx = extract_attachment_text(
        filename="inspection.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=xlsx_buffer.getvalue(),
    )
    assert xlsx.status == "completed"
    assert "[Sheet: 점검]" in xlsx.text
    assert "압연기\t정상" in xlsx.text

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "2분기 결과"
    slide.placeholders[1].text = "예방 정비 완료"
    pptx_buffer = BytesIO()
    presentation.save(pptx_buffer)
    pptx = extract_attachment_text(
        filename="inspection.pptx",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        content=pptx_buffer.getvalue(),
    )
    assert pptx.status == "completed"
    assert "예방 정비 완료" in pptx.text

    assert _sniff_mime(docx_buffer.getvalue(), ".docx").endswith(
        "wordprocessingml.document"
    )
    assert _sniff_mime(xlsx_buffer.getvalue(), ".xlsx").endswith("spreadsheetml.sheet")
    assert _sniff_mime(pptx_buffer.getvalue(), ".pptx").endswith(
        "presentationml.presentation"
    )


def test_zip_header_alone_is_not_trusted_as_an_office_document() -> None:
    fake_zip = b"PK\x03\x04not-an-openxml-container"

    assert _sniff_mime(fake_zip, ".docx") == "application/octet-stream"
    assert _sniff_mime(fake_zip, ".xlsx") == "application/octet-stream"
    assert _sniff_mime(fake_zip, ".pptx") == "application/octet-stream"


def test_attachment_api_rejects_fake_office_and_persists_valid_extraction(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'attachments.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "loginName": "admin",
                "loginDomain": "posco.com",
                "password": "1",
            },
        )
        csrf = login.json()["csrfToken"]
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "첨부 검증"},
        ).json()
        endpoint = f"/api/conversations/{conversation['id']}/attachments"

        rejected = client.post(
            endpoint,
            headers={"X-CSRF-Token": csrf},
            files={
                "file": (
                    "fake.docx",
                    b"PK\x03\x04not-openxml",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert rejected.status_code == 415
        assert rejected.json()["code"] == "mime_mismatch"

        empty = client.post(
            endpoint,
            headers={"X-CSRF-Token": csrf},
            data={"pasted_text": "  \n  ", "source": "paste"},
        )
        assert empty.status_code == 422
        assert empty.json()["code"] == "attachment_empty"

        document = Document()
        document.add_paragraph("실제 문서 본문")
        buffer = BytesIO()
        document.save(buffer)
        uploaded = client.post(
            endpoint,
            headers={"X-CSRF-Token": csrf},
            files={
                "file": (
                    "real.docx",
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        assert uploaded.json()["extractionStatus"] == "completed"
        assert uploaded.json()["metadata"]["extractedSize"] > 0

        stored_attachment = next(
            path
            for path in (settings.files_dir / "attachments").rglob("*")
            if path.is_file()
        )
        stored_attachment.write_bytes(b"tampered attachment")
        unavailable = client.get(
            f"/api/attachments/{uploaded.json()['id']}/content"
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["code"] == "attachment_content_missing"
