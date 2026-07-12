from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Sequence
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from PIL import Image, ImageDraw
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from lumina.artifacts.render_validation import (
    RenderCommandResult,
    local_renderer_availability,
)
from lumina.artifacts.reporting import generate_report
from lumina.artifacts.service import validate_artifact_content


def _report_arguments(report_format: str) -> dict[str, object]:
    return {
        "format": report_format,
        "title": "Render validation report",
        "executive_summary": "A deterministic report for render verification.",
        "key_metrics": [{"label": "Items", "value": "2"}],
        "sections": [
            {
                "heading": "Findings",
                "body": "The generated page contains visible text.",
                "bullets": ["First", "Second"],
            }
        ],
        "action_items": ["Review the rendered output."],
    }


class _UnavailableBackend:
    def find_executable(self, _candidates: Sequence[str]) -> str | None:
        return None

    def run(
        self, _arguments: Sequence[str], *, cwd: Path, timeout_seconds: float
    ) -> RenderCommandResult:
        del cwd, timeout_seconds
        raise AssertionError("an unavailable renderer must not run")


class _FakeBackend:
    def __init__(
        self,
        *,
        office_pdf: bytes | None = None,
        blank_pages: bool = False,
        returncode: int = 0,
        timed_out: bool = False,
        image_size: tuple[int, int] = (800, 1100),
        extra_pages: int = 0,
    ) -> None:
        self.office_pdf = office_pdf
        self.blank_pages = blank_pages
        self.returncode = returncode
        self.timed_out = timed_out
        self.image_size = image_size
        self.extra_pages = extra_pages
        self.commands: list[list[str]] = []
        self.temporary_roots: list[Path] = []
        self.macro_policy_seen = False

    def find_executable(self, candidates: Sequence[str]) -> str | None:
        if "pdftoppm" in candidates:
            return "fake-pdftoppm"
        if "soffice" in candidates:
            return "fake-soffice"
        return None

    def run(
        self, arguments: Sequence[str], *, cwd: Path, timeout_seconds: float
    ) -> RenderCommandResult:
        assert timeout_seconds > 0
        assert cwd.is_dir()
        command = list(arguments)
        self.commands.append(command)
        self.temporary_roots.append(cwd)
        if self.timed_out:
            return RenderCommandResult(None, timed_out=True)
        if self.returncode:
            return RenderCommandResult(self.returncode)
        if command[0] == "fake-soffice":
            assert self.office_pdf is not None
            assert "--headless" in command
            assert "--norestore" in command
            profile_argument = next(
                item for item in command if item.startswith("-env:UserInstallation=")
            )
            assert profile_argument.startswith("-env:UserInstallation=file:")
            policy = cwd / "libreoffice-profile" / "user" / "registrymodifications.xcu"
            self.macro_policy_seen = policy.is_file() and "<value>3</value>" in (
                policy.read_text(encoding="utf-8")
            )
            output_dir = Path(command[command.index("--outdir") + 1])
            source = Path(command[-1])
            assert output_dir.resolve().is_relative_to(cwd.resolve())
            assert source.resolve().is_relative_to(cwd.resolve())
            (output_dir / f"{source.stem}.pdf").write_bytes(self.office_pdf)
            return RenderCommandResult(0)
        assert command[0] == "fake-pdftoppm"
        rendered_pdf = Path(command[-2])
        prefix = Path(command[-1])
        assert rendered_pdf.resolve().is_relative_to(cwd.resolve())
        assert prefix.resolve().is_relative_to(cwd.resolve())
        page_count = len(PdfReader(rendered_pdf).pages) + self.extra_pages
        for page_number in range(1, page_count + 1):
            image = Image.new("RGB", self.image_size, "white")
            if not self.blank_pages:
                draw = ImageDraw.Draw(image)
                draw.rectangle((80, 80, 720, 1020), outline="black", width=4)
                draw.text((120, 120), f"Rendered page {page_number}", fill="black")
            image.save(prefix.parent / f"{prefix.name}-{page_number}.png", "PNG")
        return RenderCommandResult(0)


def test_missing_renderers_remain_structural_and_pending() -> None:
    report = generate_report("Create a PDF report", _report_arguments("pdf"))

    status, validation = validate_artifact_content(
        kind=report.kind,
        mime_type=report.mime_type,
        content=report.content,
        render_backend=_UnavailableBackend(),
    )

    assert status == "structural_passed"
    assert validation["renderVerified"] is False
    assert validation["renderer"] is None
    assert validation["pages"] == []
    assert validation["errors"] == []
    assert validation["warnings"] == [
        "render_verification_pending",
        "renderer_unavailable:pdftoppm",
    ]


def test_fake_pdf_renderer_records_verified_page_metadata_and_cleans_temp() -> None:
    report = generate_report("Create a PDF report", _report_arguments("pdf"))
    backend = _FakeBackend()

    status, validation = validate_artifact_content(
        kind=report.kind,
        mime_type=report.mime_type,
        content=report.content,
        render_backend=backend,
    )

    assert status == "passed"
    assert validation["verificationLevel"] == "render"
    assert validation["renderVerified"] is True
    assert validation["renderer"] == "pdftoppm"
    assert validation["warnings"] == []
    assert validation["errors"] == []
    assert validation["pages"] == [
        {
            "number": 1,
            "width": 800,
            "height": 1100,
            "blank": False,
            "sizeBytes": validation["pages"][0]["sizeBytes"],
        }
    ]
    assert validation["pages"][0]["sizeBytes"] > 0
    assert all(not path.exists() for path in backend.temporary_roots)


@pytest.mark.parametrize("report_format", ["docx", "xlsx", "pptx"])
def test_fake_office_renderer_uses_isolated_profile_and_verifies_pages(
    report_format: str,
) -> None:
    office = generate_report(
        f"Create a {report_format} report", _report_arguments(report_format)
    )
    pdf = generate_report("Create a PDF report", _report_arguments("pdf"))
    backend = _FakeBackend(office_pdf=pdf.content)

    status, validation = validate_artifact_content(
        kind=office.kind,
        mime_type=office.mime_type,
        content=office.content,
        render_backend=backend,
    )

    assert status == "passed", validation
    assert validation["renderVerified"] is True
    assert validation["renderer"] == "libreoffice+pdftoppm"
    assert len(validation["pages"]) == 1
    assert backend.macro_policy_seen
    assert [command[0] for command in backend.commands] == [
        "fake-soffice",
        "fake-pdftoppm",
    ]
    assert all(not path.exists() for path in backend.temporary_roots)


def test_renderer_failure_and_timeout_never_become_full_pass() -> None:
    report = generate_report("Create a PDF report", _report_arguments("pdf"))
    failed_status, failed = validate_artifact_content(
        kind=report.kind,
        mime_type=report.mime_type,
        content=report.content,
        render_backend=_FakeBackend(returncode=7),
    )
    timeout_status, timed_out = validate_artifact_content(
        kind=report.kind,
        mime_type=report.mime_type,
        content=report.content,
        render_backend=_FakeBackend(timed_out=True),
    )

    assert failed_status == "failed"
    assert failed["renderVerified"] is False
    assert failed["errors"] == ["renderer_failed:pdftoppm:7"]
    assert timeout_status == "failed"
    assert timed_out["renderVerified"] is False
    assert timed_out["errors"] == ["renderer_timeout:pdftoppm"]


def test_fully_blank_rendered_document_fails_with_explicit_warning() -> None:
    report = generate_report("Create a PDF report", _report_arguments("pdf"))

    status, validation = validate_artifact_content(
        kind=report.kind,
        mime_type=report.mime_type,
        content=report.content,
        render_backend=_FakeBackend(blank_pages=True),
    )

    assert status == "failed"
    assert validation["renderVerified"] is False
    assert validation["pages"][0]["blank"] is True
    assert validation["warnings"] == ["blank_rendered_page:1"]
    assert validation["errors"] == ["all_rendered_pages_blank"]


def test_abnormally_small_rendered_page_fails_verification() -> None:
    report = generate_report("Create a PDF report", _report_arguments("pdf"))

    status, validation = validate_artifact_content(
        kind=report.kind,
        mime_type=report.mime_type,
        content=report.content,
        render_backend=_FakeBackend(image_size=(40, 40)),
    )

    assert status == "failed"
    assert validation["renderVerified"] is False
    assert validation["errors"] == ["rendered_page_size_out_of_range:1:40x40"]


def test_rendered_page_count_mismatch_fails_verification() -> None:
    report = generate_report("Create a PDF report", _report_arguments("pdf"))

    status, validation = validate_artifact_content(
        kind=report.kind,
        mime_type=report.mime_type,
        content=report.content,
        render_backend=_FakeBackend(extra_pages=1),
    )

    assert status == "failed"
    assert validation["renderVerified"] is False
    assert validation["errors"] == ["rendered_page_count_mismatch:1:2"]
    assert len(validation["pages"]) == 2


def test_pdf_link_and_page_geometry_are_structurally_validated() -> None:
    safe_pdf = BytesIO()
    canvas = Canvas(safe_pdf, pagesize=(595, 842))
    canvas.drawString(72, 760, "Linked report")
    canvas.linkURL("https://example.com/report", (72, 740, 240, 770))
    canvas.save()
    safe_status, safe_validation = validate_artifact_content(
        kind="pdf",
        mime_type="application/pdf",
        content=safe_pdf.getvalue(),
        render_backend=_UnavailableBackend(),
    )

    tiny_pdf = BytesIO()
    canvas = Canvas(tiny_pdf, pagesize=(20, 20))
    canvas.drawString(1, 10, "tiny")
    canvas.save()
    tiny_status, tiny_validation = validate_artifact_content(
        kind="pdf",
        mime_type="application/pdf",
        content=tiny_pdf.getvalue(),
        render_backend=_UnavailableBackend(),
    )

    assert safe_status == "structural_passed", safe_validation
    assert safe_validation["details"]["linkCount"] == 1
    assert tiny_status == "failed"
    assert any(
        error.startswith("pdf_page_size_out_of_range:1:")
        for error in tiny_validation["errors"]
    )


def test_unsafe_openxml_hyperlink_is_rejected_before_render() -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    sheet["A1"] = "unsafe"
    sheet["A1"].hyperlink = "file:///C:/sensitive.xlsx"
    content = BytesIO()
    workbook.save(content)
    workbook.close()
    backend = _FakeBackend(office_pdf=b"not used")

    status, validation = validate_artifact_content(
        kind="xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=content.getvalue(),
        render_backend=backend,
    )

    assert status == "failed"
    assert "unsafe_external_link" in validation["errors"]
    assert backend.commands == []


def test_macro_enabled_openxml_payload_is_rejected_before_renderer_runs() -> None:
    report = generate_report("Create a DOCX report", _report_arguments("docx"))
    source = BytesIO()
    with (
        ZipFile(BytesIO(report.content)) as original,
        ZipFile(source, "w", ZIP_DEFLATED) as modified,
    ):
        for entry in original.infolist():
            modified.writestr(entry, original.read(entry))
        modified.writestr("word/vbaProject.bin", b"macro")
    backend = _FakeBackend(office_pdf=b"not used")

    status, validation = validate_artifact_content(
        kind=report.kind,
        mime_type=report.mime_type,
        content=source.getvalue(),
        render_backend=backend,
    )

    assert status == "failed"
    assert "openxml_macros_forbidden" in validation["errors"]
    assert validation["renderVerified"] is False
    assert backend.commands == []


def test_installed_poppler_verifies_generated_pdf() -> None:
    if local_renderer_availability()["pdftoppm"] is None:
        pytest.skip("an executable pdftoppm binary is not installed")
    report = generate_report("Create a PDF report", _report_arguments("pdf"))

    status, validation = validate_artifact_content(
        kind=report.kind, mime_type=report.mime_type, content=report.content
    )

    assert status == "passed", validation
    assert validation["renderVerified"] is True
    assert validation["renderer"] == "pdftoppm"
    assert validation["pages"]


def test_installed_office_pipeline_verifies_generated_docx() -> None:
    availability = local_renderer_availability()
    if availability["libreoffice"] is None or availability["pdftoppm"] is None:
        pytest.skip("LibreOffice and executable pdftoppm binaries are not installed")
    report = generate_report("Create a DOCX report", _report_arguments("docx"))

    status, validation = validate_artifact_content(
        kind=report.kind, mime_type=report.mime_type, content=report.content
    )

    assert status == "passed", validation
    assert validation["renderVerified"] is True
    assert validation["renderer"] == "libreoffice+pdftoppm"
    assert validation["pages"]
