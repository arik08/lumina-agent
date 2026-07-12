from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from lumina.agent.executor import _REPORT_TOOL_SCHEMA, local_run_executor
from lumina.artifacts.render_validation import LocalArtifactRenderBackend
from lumina.artifacts.reporting import REPORT_FORMATS, generate_report
from lumina.artifacts.service import validate_artifact_content
from lumina.config import Settings
from lumina.main import create_app
from lumina.providers import MockProvider, MockToolCall


_EXPECTED_METADATA = {
    "html": ("Lumina_작업_보고서.html", "html", "text/html"),
    "markdown": ("Lumina_작업_보고서.md", "markdown", "text/markdown"),
    "docx": (
        "Lumina_작업_보고서.docx",
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "xlsx": (
        "Lumina_작업_보고서.xlsx",
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "pptx": (
        "Lumina_작업_보고서.pptx",
        "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    "pdf": ("Lumina_작업_보고서.pdf", "pdf", "application/pdf"),
}


@pytest.fixture(autouse=True)
def _disable_host_renderers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit/API expectations deterministic; installed tools have separate tests."""
    monkeypatch.setattr(
        LocalArtifactRenderBackend,
        "find_executable",
        lambda _self, _candidates: None,
    )


def _arguments(report_format: str) -> dict[str, object]:
    return {
        "format": report_format,
        "title": "광양 설비 점검 보고서",
        "executive_summary": "핵심 설비 2건을 확인했습니다.",
        "key_metrics": [{"label": "점검 설비", "value": "2건"}],
        "sections": [
            {
                "heading": "점검 결과",
                "body": "이상 징후 1건을 확인했습니다.",
                "bullets": ["베어링 온도를 확인합니다.", "담당자가 재점검합니다."],
            }
        ],
        "action_items": ["48시간 안에 재점검합니다."],
    }


@pytest.mark.parametrize("report_format", REPORT_FORMATS)
def test_report_formats_reopen_and_retain_korean_content(report_format: str) -> None:
    report = generate_report("설비 상태를 정리해 주세요.", _arguments(report_format))
    expected_name, expected_kind, expected_mime = _EXPECTED_METADATA[report_format]

    assert report.display_name == expected_name
    assert report.kind == expected_kind
    assert report.mime_type == expected_mime
    _assert_reopened(report_format, report.content)

    status, validation = validate_artifact_content(
        kind=report.kind,
        mime_type=report.mime_type,
        content=report.content,
    )
    expected_status = "passed" if report_format == "markdown" else "structural_passed"
    assert status == expected_status, validation
    assert validation["errors"] == []
    assert validation["renderVerified"] is False
    assert validation["renderVerificationRequired"] is (report_format != "markdown")
    detail_keys = {
        "html": "htmlTitle",
        "docx": "paragraphCount",
        "xlsx": "populatedCells",
        "pptx": "slideCount",
        "pdf": "pageCount",
    }
    if report_format in detail_keys:
        assert validation["details"][detail_keys[report_format]]


def test_create_report_schema_advertises_every_supported_format() -> None:
    schema = _REPORT_TOOL_SCHEMA["function"]["parameters"]["properties"]["format"]
    assert schema["enum"] == list(REPORT_FORMATS)


def test_xlsx_keeps_formula_like_model_text_as_plain_text() -> None:
    arguments = _arguments("xlsx")
    arguments["sections"] = [
        {
            "heading": "검토 결과",
            "body": '=HYPERLINK("https://example.com", "열기")',
            "bullets": ["=1+1"],
        }
    ]
    report = generate_report("수식처럼 보이는 텍스트를 정리해 주세요.", arguments)
    workbook = load_workbook(BytesIO(report.content), data_only=False)
    formula_cells = [
        cell.coordinate
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.data_type == "f"
    ]
    values = [
        cell.value
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None
    ]
    workbook.close()

    assert formula_cells == []
    assert '=HYPERLINK("https://example.com", "열기")' in values
    assert "• =1+1" in values


def test_unknown_report_format_is_rejected() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 보고서 형식"):
        generate_report("요청", _arguments("rtf"))


@pytest.mark.parametrize("report_format", REPORT_FORMATS)
def test_create_report_tool_persists_and_downloads_selected_format(
    report_format: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / f'{report_format}.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )

    def fake_provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        del wants_artifact
        if first_turn:
            return MockProvider(
                text_chunks=("보고서를 구성하겠습니다.",),
                tool_call=MockToolCall(
                    name="create_report",
                    arguments=_arguments(report_format),
                    call_id=f"call_create_{report_format}",
                ),
            )
        return MockProvider(text_chunks=("보고서를 생성하고 형식을 검증했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", fake_provider)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": f"{report_format} 생성 테스트"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": f"create-{report_format}-report-0001",
            },
            json={
                "message": {
                    "text": f"점검 결과를 {report_format} 보고서 Artifact로 만들어 주세요.",
                    "attachmentIds": [],
                    "promptReferences": [],
                },
                "execution": {
                    "providerId": "mock",
                    "modelKey": "mock-agent",
                    "effortId": "medium",
                },
            },
        )
        assert started.status_code == 202, started.text
        snapshot = _wait_for_terminal(client, started.json()["run"]["runId"])
        assert snapshot["status"] == "completed"
        artifact = snapshot["artifacts"][0]
        expected_name, expected_kind, expected_mime = _EXPECTED_METADATA[report_format]
        assert artifact["displayName"] == expected_name
        assert artifact["kind"] == expected_kind
        assert artifact["mimeType"] == expected_mime
        assert artifact["validationStatus"] == (
            "passed" if report_format == "markdown" else "structural_passed"
        )

        version = client.get(f"/api/artifacts/{artifact['id']}/versions/1")
        assert version.status_code == 200
        version_payload = version.json()
        if report_format != "markdown":
            assert version_payload["validation"]["renderVerified"] is False
            assert version_payload["validation"]["renderer"] is None
            assert version_payload["validation"]["pages"] == []
            assert (
                "render_verification_pending"
                in version_payload["validation"]["warnings"]
            )
        if report_format in {"docx", "xlsx", "pptx", "pdf"}:
            assert version_payload["sourceText"] is None
            blocked_version = client.post(
                f"/api/artifacts/{artifact['id']}/versions",
                headers={
                    "X-CSRF-Token": csrf,
                    "If-Match": version_payload["etag"],
                    "Idempotency-Key": f"blocked-{report_format}-edit-0001",
                },
                json={
                    "baseVersion": 1,
                    "sourceText": "",
                    "changeSummary": "binary edit must be rejected",
                },
            )
            assert blocked_version.status_code == 409
            assert blocked_version.json()["code"] == "artifact_binary_edit_unsupported"
            blocked_draft = client.put(
                f"/api/artifacts/{artifact['id']}/draft",
                headers={"X-CSRF-Token": csrf},
                json={"baseVersion": 1, "content": ""},
            )
            assert blocked_draft.status_code == 409
            assert blocked_draft.json()["code"] == "artifact_binary_edit_unsupported"
        elif report_format == "markdown":
            assert version_payload["sourceText"] is not None
            draft = client.put(
                f"/api/artifacts/{artifact['id']}/draft",
                headers={"X-CSRF-Token": csrf},
                json={
                    "baseVersion": 1,
                    "content": version_payload["sourceText"] + "\n\n초안 수정",
                },
            )
            assert draft.status_code == 200, draft.text
            draft_files = list(
                (tmp_path / "artifacts" / "artifact-drafts").rglob("*.md")
            )
            assert len(draft_files) == 1

        downloaded = client.get(f"/api/artifacts/{artifact['id']}/download")
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"].split(";", 1)[0] == expected_mime
        assert downloaded.headers["content-disposition"].startswith(
            "attachment; filename*=UTF-8''Lumina_"
        )
        assert downloaded.headers["content-disposition"].endswith(
            f".{expected_name.rsplit('.', 1)[-1]}"
        )
        _assert_reopened(report_format, downloaded.content)


def _assert_reopened(report_format: str, content: bytes) -> None:
    if report_format in {"html", "markdown"}:
        source = content.decode("utf-8", errors="strict")
        assert "광양 설비 점검 보고서" in source
        assert "이상 징후 1건" in source
        return
    if report_format == "docx":
        document = Document(BytesIO(content))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        text += "\n".join(
            cell.text
            for table in document.tables
            for row in table.rows
            for cell in row.cells
        )
        assert "광양 설비 점검 보고서" in text
        assert "이상 징후 1건" in text
        return
    if report_format == "xlsx":
        workbook = load_workbook(BytesIO(content), data_only=False)
        values = "\n".join(
            str(cell.value)
            for sheet in workbook.worksheets
            for row in sheet.iter_rows()
            for cell in row
            if cell.value is not None
        )
        assert "광양 설비 점검 보고서" in values
        assert "이상 징후 1건" in values
        workbook.close()
        return
    if report_format == "pptx":
        presentation = Presentation(BytesIO(content))
        text = "\n".join(
            shape.text
            for slide in presentation.slides
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False)
        )
        assert "광양 설비 점검 보고서" in text
        assert "이상 징후 1건" in text
        return
    if report_format == "pdf":
        reader = PdfReader(BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        assert "광양 설비 점검 보고서" in text
        assert "이상 징후 1건" in text
        assert float(reader.pages[0].mediabox.width) == pytest.approx(595.28, abs=0.5)
        assert float(reader.pages[0].mediabox.height) == pytest.approx(841.89, abs=0.5)
        return
    raise AssertionError(f"Unhandled report format: {report_format}")


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1",
        },
    )
    assert response.status_code == 200
    return response.json()["csrfToken"]


def _wait_for_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {
            "completed",
            "failed",
            "cancelled",
            "limit_reached",
            "interrupted",
        }:
            return payload
        time.sleep(0.03)
    raise AssertionError("Run did not reach a terminal state")
