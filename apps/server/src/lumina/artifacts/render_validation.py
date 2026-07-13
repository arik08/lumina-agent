from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence, cast

from PIL import Image, ImageChops, UnidentifiedImageError
from pypdf import PdfReader

from ..document_limits import MAX_DOCUMENT_PAGES


OFFICE_MIME_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)
_OFFICE_EXTENSIONS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}
_MAX_RENDERED_PAGE_PIXELS = 40_000_000
_MAX_RENDERED_BYTES = 256 * 1024 * 1024
_MIN_RENDERED_DIMENSION = 96
_MAX_RENDERED_DIMENSION = 10_000
_RENDER_DPI = 96
_DEFAULT_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class RenderCommandResult:
    returncode: int | None
    timed_out: bool = False
    launch_error: str | None = None


class ArtifactRenderBackend(Protocol):
    def find_executable(self, candidates: Sequence[str]) -> str | None: ...

    def run(
        self, arguments: Sequence[str], *, cwd: Path, timeout_seconds: float
    ) -> RenderCommandResult: ...


@dataclass(slots=True)
class RenderVerification:
    render_verified: bool = False
    renderer: str | None = None
    pages: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)


class LocalArtifactRenderBackend:
    """Run approved local renderers without a shell or inherited application secrets."""

    def find_executable(self, candidates: Sequence[str]) -> str | None:
        for candidate in candidates:
            located = shutil.which(candidate)
            if not located:
                continue
            try:
                resolved = Path(located).resolve(strict=True)
            except OSError:
                continue
            if resolved.is_file() and (
                os.name != "nt" or resolved.suffix.casefold() in {".exe", ".com"}
            ):
                return str(resolved)
        return None

    def run(
        self, arguments: Sequence[str], *, cwd: Path, timeout_seconds: float
    ) -> RenderCommandResult:
        if not arguments:
            return RenderCommandResult(None, launch_error="empty_command")
        environment = _renderer_environment(cwd)
        creation_flags = 0
        start_new_session = os.name != "nt"
        if os.name == "nt":
            creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        try:
            process = subprocess.Popen(  # noqa: S603 - executable is resolved without shell
                list(arguments),
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=creation_flags,
                start_new_session=start_new_session,
            )
        except OSError as exc:
            return RenderCommandResult(None, launch_error=type(exc).__name__)
        try:
            return RenderCommandResult(process.wait(timeout=timeout_seconds))
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process)
            return RenderCommandResult(None, timed_out=True)


def verify_artifact_render(
    *,
    kind: str,
    mime_type: str,
    content: bytes,
    expected_page_count: int | None,
    backend: ArtifactRenderBackend | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> RenderVerification:
    """Render PDF/Office bytes to temporary PNG pages and inspect the raster output."""
    normalized_kind = kind.casefold()
    if mime_type == "application/pdf" or normalized_kind == "pdf":
        extension = "pdf"
        office = False
    elif mime_type in OFFICE_MIME_TYPES or normalized_kind in {"docx", "xlsx", "pptx"}:
        extension = _OFFICE_EXTENSIONS.get(mime_type, normalized_kind)
        office = True
    else:
        return RenderVerification(warnings=["render_verification_pending"])

    selected_backend = backend or LocalArtifactRenderBackend()
    pdf_renderer = selected_backend.find_executable(("pdftoppm",))
    office_renderer = (
        selected_backend.find_executable(("soffice", "libreoffice")) if office else None
    )
    unavailable: list[str] = []
    if office and office_renderer is None:
        unavailable.append("renderer_unavailable:libreoffice")
    if pdf_renderer is None:
        unavailable.append("renderer_unavailable:pdftoppm")
    if unavailable:
        return RenderVerification(
            warnings=["render_verification_pending", *unavailable],
            checks=["renderer_availability"],
        )

    renderer_name = "libreoffice+pdftoppm" if office else "pdftoppm"
    result = RenderVerification(
        renderer=renderer_name,
        checks=[
            "renderer_availability",
            "page_render",
            "rendered_page_count",
            "rendered_page_dimensions",
            "rendered_page_blankness",
        ],
    )
    with tempfile.TemporaryDirectory(prefix="lumina-artifact-render-") as temporary:
        root = Path(temporary).resolve(strict=True)
        input_path = _safe_child(root, root / f"source.{extension}")
        input_path.write_bytes(content)
        rendered_pdf = input_path
        if office:
            assert office_renderer is not None
            rendered_pdf = _render_office_to_pdf(
                backend=selected_backend,
                office_renderer=office_renderer,
                input_path=input_path,
                root=root,
                timeout_seconds=timeout_seconds,
                result=result,
            )
            if result.errors:
                return result
            expected_page_count = _pdf_page_count(rendered_pdf, result)
            if result.errors:
                return result

        assert pdf_renderer is not None
        page_prefix = _safe_child(root, root / "page")
        command = [
            pdf_renderer,
            "-png",
            "-r",
            str(_RENDER_DPI),
            "-f",
            "1",
            "-l",
            str(MAX_DOCUMENT_PAGES),
            str(rendered_pdf),
            str(page_prefix),
        ]
        command_result = selected_backend.run(
            command, cwd=root, timeout_seconds=timeout_seconds
        )
        _record_command_failure(command_result, "pdftoppm", result)
        if result.errors:
            return result

        page_files = _rendered_page_files(root)
        if not page_files:
            result.errors.append("renderer_output_missing:pdftoppm")
            return result
        if expected_page_count is not None and len(page_files) != expected_page_count:
            result.errors.append(
                f"rendered_page_count_mismatch:{expected_page_count}:{len(page_files)}"
            )
        if len(page_files) > MAX_DOCUMENT_PAGES:
            result.errors.append("rendered_page_limit_exceeded")
        if [number for number, _ in page_files] != list(range(1, len(page_files) + 1)):
            result.errors.append("rendered_page_sequence_invalid")

        rendered_bytes = 0
        for page_number, page_file in page_files:
            try:
                safe_page = _safe_child(root, page_file)
            except ValueError:
                result.errors.append(f"renderer_output_path_unsafe:{page_number}")
                continue
            rendered_bytes += safe_page.stat().st_size
            if rendered_bytes > _MAX_RENDERED_BYTES:
                result.errors.append("rendered_output_too_large")
                break
            page = _inspect_page(safe_page, page_number, result)
            if page is not None:
                result.pages.append(page)

        if result.pages and all(page.get("blank") is True for page in result.pages):
            result.errors.append("all_rendered_pages_blank")

    result.errors = list(dict.fromkeys(result.errors))
    result.warnings = list(dict.fromkeys(result.warnings))
    result.render_verified = not result.errors and bool(result.pages)
    return result


def local_renderer_availability() -> dict[str, str | None]:
    backend = LocalArtifactRenderBackend()
    return {
        "libreoffice": backend.find_executable(("soffice", "libreoffice")),
        "pdftoppm": backend.find_executable(("pdftoppm",)),
    }


def _render_office_to_pdf(
    *,
    backend: ArtifactRenderBackend,
    office_renderer: str,
    input_path: Path,
    root: Path,
    timeout_seconds: float,
    result: RenderVerification,
) -> Path:
    profile = _safe_child(root, root / "libreoffice-profile")
    profile.mkdir()
    _write_macro_security_policy(profile)
    output_dir = _safe_child(root, root / "converted")
    output_dir.mkdir()
    command = [
        office_renderer,
        "--headless",
        "--nologo",
        "--nodefault",
        "--nolockcheck",
        "--norestore",
        "--invisible",
        f"-env:UserInstallation={profile.as_uri()}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(input_path),
    ]
    command_result = backend.run(command, cwd=root, timeout_seconds=timeout_seconds)
    _record_command_failure(command_result, "libreoffice", result)
    try:
        pdf_path = _safe_child(root, output_dir / f"{input_path.stem}.pdf")
    except ValueError:
        result.errors.append("renderer_output_path_unsafe:libreoffice")
        return root / "unsafe-renderer-output"
    if not result.errors and (not pdf_path.is_file() or pdf_path.stat().st_size == 0):
        result.errors.append("renderer_output_missing:libreoffice")
    return pdf_path


def _write_macro_security_policy(profile: Path) -> None:
    policy = _safe_child(profile, profile / "user" / "registrymodifications.xcu")
    policy.parent.mkdir(parents=True)
    policy.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
        '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
        '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
        "</item></oor:items>",
        encoding="utf-8",
    )


def _pdf_page_count(path: Path, result: RenderVerification) -> int | None:
    try:
        reader = PdfReader(path)
        count = len(reader.pages)
        for page_number, page in enumerate(reader.pages, start=1):
            width = abs(float(page.mediabox.width)) * _RENDER_DPI / 72
            height = abs(float(page.mediabox.height)) * _RENDER_DPI / 72
            if (
                width < _MIN_RENDERED_DIMENSION
                or height < _MIN_RENDERED_DIMENSION
                or width > _MAX_RENDERED_DIMENSION
                or height > _MAX_RENDERED_DIMENSION
                or width * height > _MAX_RENDERED_PAGE_PIXELS
            ):
                result.errors.append(
                    "renderer_pdf_page_size_out_of_range:"
                    f"{page_number}:{width:g}x{height:g}"
                )
    except Exception:
        result.errors.append("invalid_renderer_pdf_output")
        return None
    if count == 0:
        result.errors.append("empty_renderer_pdf_output")
        return None
    if count > MAX_DOCUMENT_PAGES:
        result.errors.append("rendered_page_limit_exceeded")
        return None
    if result.errors:
        return None
    return count


def _rendered_page_files(root: Path) -> list[tuple[int, Path]]:
    pages: list[tuple[int, Path]] = []
    for candidate in root.glob("page-*.png"):
        suffix = candidate.stem.removeprefix("page-")
        if suffix.isdigit():
            pages.append((int(suffix), candidate))
    pages.sort(key=lambda item: item[0])
    return pages


def _inspect_page(
    path: Path, page_number: int, result: RenderVerification
) -> dict[str, object] | None:
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                result.errors.append(f"rendered_page_invalid_format:{page_number}")
                return None
            width, height = image.size
            invalid_size = (
                width < _MIN_RENDERED_DIMENSION
                or height < _MIN_RENDERED_DIMENSION
                or width > _MAX_RENDERED_DIMENSION
                or height > _MAX_RENDERED_DIMENSION
                or width * height > _MAX_RENDERED_PAGE_PIXELS
            )
            if invalid_size:
                result.errors.append(
                    f"rendered_page_size_out_of_range:{page_number}:{width}x{height}"
                )
                return {
                    "number": page_number,
                    "width": width,
                    "height": height,
                    "blank": None,
                    "sizeBytes": path.stat().st_size,
                }
            image.load()
            sample = image.convert("RGB")
            sample.thumbnail((128, 128))
            difference = ImageChops.difference(
                sample, Image.new("RGB", sample.size, "white")
            )
            extrema = cast(tuple[tuple[float, float], ...], difference.getextrema())
            blank = all(maximum <= 8 for _, maximum in extrema)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
        result.errors.append(f"rendered_page_unreadable:{page_number}")
        return None
    if blank:
        result.warnings.append(f"blank_rendered_page:{page_number}")
    return {
        "number": page_number,
        "width": width,
        "height": height,
        "blank": blank,
        "sizeBytes": path.stat().st_size,
    }


def _record_command_failure(
    command: RenderCommandResult, renderer: str, result: RenderVerification
) -> None:
    if command.timed_out:
        result.errors.append(f"renderer_timeout:{renderer}")
    elif command.launch_error:
        result.errors.append(
            f"renderer_launch_failed:{renderer}:{command.launch_error}"
        )
    elif command.returncode != 0:
        result.errors.append(f"renderer_failed:{renderer}:{command.returncode}")


def _safe_child(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("renderer path escaped its temporary directory") from exc
    return resolved


def _renderer_environment(temporary_root: Path) -> dict[str, str]:
    allowed = (
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "WINDIR",
        "LANG",
        "LC_ALL",
        "LD_LIBRARY_PATH",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    temporary = str(temporary_root)
    environment.update(
        {
            "HOME": temporary,
            "USERPROFILE": temporary,
            "TMP": temporary,
            "TEMP": temporary,
            "TMPDIR": temporary,
            "SAL_DISABLE_SYNCHRONOUS_PRINTER_DETECTION": "1",
        }
    )
    return environment


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        taskkill = Path(system_root) / "System32" / "taskkill.exe"
        if taskkill.is_file():
            try:
                subprocess.run(  # noqa: S603 - fixed system executable and integer PID
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        try:
            kill_process_group = getattr(os, "killpg")
            kill_process_group(process.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except (AttributeError, OSError, ProcessLookupError):
            pass
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


__all__ = [
    "ArtifactRenderBackend",
    "LocalArtifactRenderBackend",
    "RenderCommandResult",
    "RenderVerification",
    "local_renderer_availability",
    "verify_artifact_render",
]
