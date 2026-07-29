from __future__ import annotations

import asyncio
import ipaddress
import os
import shutil
import socket
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from ..dependencies import AuthContext, require_csrf
from ..errors import ApiProblem


router = APIRouter(prefix="/clipboard", tags=["clipboard"])

_MAX_PNG_BYTES = 25 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _local_machine_addresses() -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = {
        ipaddress.ip_address("127.0.0.1"),
        ipaddress.ip_address("::1"),
    }
    names = {socket.gethostname(), socket.getfqdn(), "localhost"}
    for name in names:
        try:
            for info in socket.getaddrinfo(name, None):
                candidate = str(info[4][0]).split("%", 1)[0]
                addresses.add(ipaddress.ip_address(candidate))
        except (OSError, ValueError):
            continue
    return addresses


def _is_local_machine_client(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_loopback or address in _local_machine_addresses()


def _request_client_host(request: Request) -> str | None:
    peer_host = request.client.host if request.client else None
    if not peer_host:
        return None
    try:
        peer_address = ipaddress.ip_address(peer_host.split("%", 1)[0])
    except ValueError:
        return peer_host
    if not peer_address.is_loopback:
        return peer_host
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",", 1)[0].strip() or peer_host


def _windows_powershell() -> str | None:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidates = (
        system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe",
        Path(shutil.which("powershell.exe") or ""),
        Path(shutil.which("powershell") or ""),
    )
    for candidate in candidates:
        if str(candidate) and candidate.is_file():
            return str(candidate.resolve())
    return None


def _write_windows_clipboard_image(png: bytes) -> None:
    powershell = _windows_powershell()
    if powershell is None:
        raise ApiProblem(
            501,
            "clipboard_powershell_unavailable",
            "Windows 이미지 클립보드를 실행할 PowerShell을 찾지 못했습니다.",
        )
    script = "; ".join(
        (
            "$ErrorActionPreference = 'Stop'",
            "Add-Type -AssemblyName System.Windows.Forms",
            "Add-Type -AssemblyName System.Drawing",
            "$inputStream = [Console]::OpenStandardInput()",
            "$memory = New-Object System.IO.MemoryStream",
            "$inputStream.CopyTo($memory)",
            "$memory.Position = 0",
            "$image = [System.Drawing.Image]::FromStream($memory)",
            "try {",
            "  $bitmap = New-Object System.Drawing.Bitmap($image)",
            "  try {",
            "    [System.Windows.Forms.Clipboard]::SetImage($bitmap)",
            "    if (-not [System.Windows.Forms.Clipboard]::ContainsImage())"
            " { throw 'Windows clipboard did not retain the image.' }",
            "  } finally { $bitmap.Dispose() }",
            "} finally { $image.Dispose(); $memory.Dispose() }",
        )
    )
    try:
        completed = subprocess.run(  # noqa: S603 - fixed resolved PowerShell executable
            [
                powershell,
                "-STA",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            input=png,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ApiProblem(
            500,
            "clipboard_write_failed",
            "Windows 이미지 클립보드에 복사하지 못했습니다.",
        ) from exc
    if completed.returncode != 0:
        raise ApiProblem(
            500,
            "clipboard_write_failed",
            "Windows 이미지 클립보드에 복사하지 못했습니다.",
        )


async def _read_png(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "image/png":
        raise ApiProblem(415, "clipboard_png_required", "PNG 이미지만 클립보드에 복사할 수 있습니다.")
    declared_length = request.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) > _MAX_PNG_BYTES:
                raise ApiProblem(413, "clipboard_image_too_large", "클립보드 이미지가 너무 큽니다.")
        except ValueError:
            raise ApiProblem(400, "content_length_invalid", "요청 크기 정보가 올바르지 않습니다.") from None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_PNG_BYTES:
            raise ApiProblem(413, "clipboard_image_too_large", "클립보드 이미지가 너무 큽니다.")
        chunks.append(chunk)
    png = b"".join(chunks)
    if not png.startswith(_PNG_SIGNATURE):
        raise ApiProblem(415, "clipboard_png_invalid", "올바른 PNG 이미지가 아닙니다.")
    return png


@router.post("/image")
async def copy_image_to_clipboard(
    request: Request,
    _context: AuthContext = Depends(require_csrf),
) -> dict[str, bool]:
    if os.name != "nt":
        raise ApiProblem(
            501,
            "clipboard_windows_only",
            "HTTP 전체 이미지 복사는 Windows에서만 지원됩니다.",
        )
    client_host = _request_client_host(request)
    if not _is_local_machine_client(client_host):
        raise ApiProblem(
            403,
            "clipboard_local_machine_required",
            "HTTP 전체 이미지 복사는 Lumina를 실행 중인 같은 Windows PC에서만 사용할 수 있습니다.",
        )
    png = await _read_png(request)
    await asyncio.to_thread(_write_windows_clipboard_image, png)
    return {"ok": True}
