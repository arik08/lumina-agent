from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumina.api.dependencies import require_csrf
from lumina.api.errors import install_error_handlers
from lumina.api.routes import clipboard


PNG = b"\x89PNG\r\n\x1a\n" + b"test-png"


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(clipboard.router, prefix="/api")
    app.dependency_overrides[require_csrf] = lambda: object()
    return TestClient(app, client=("127.0.0.1", 50_000))


def test_clipboard_image_accepts_local_windows_png(monkeypatch) -> None:
    copied: list[bytes] = []
    monkeypatch.setattr(clipboard.os, "name", "nt")
    monkeypatch.setattr(clipboard, "_is_local_machine_client", lambda host: True)
    monkeypatch.setattr(clipboard, "_write_windows_clipboard_image", copied.append)

    response = _client().post(
        "/api/clipboard/image",
        content=PNG,
        headers={"content-type": "image/png"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert copied == [PNG]


def test_clipboard_image_rejects_non_png(monkeypatch) -> None:
    monkeypatch.setattr(clipboard.os, "name", "nt")
    monkeypatch.setattr(clipboard, "_is_local_machine_client", lambda host: True)

    response = _client().post(
        "/api/clipboard/image",
        content=b"not-png",
        headers={"content-type": "image/png"},
    )

    assert response.status_code == 415
    assert response.json()["code"] == "clipboard_png_invalid"


def test_clipboard_image_rejects_remote_client(monkeypatch) -> None:
    monkeypatch.setattr(clipboard.os, "name", "nt")
    checked_hosts: list[str | None] = []
    monkeypatch.setattr(
        clipboard,
        "_is_local_machine_client",
        lambda host: checked_hosts.append(host) or False,
    )

    response = _client().post(
        "/api/clipboard/image",
        content=PNG,
        headers={
            "content-type": "image/png",
            "x-forwarded-for": "203.0.113.9",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "clipboard_local_machine_required"
    assert checked_hosts == ["203.0.113.9"]


def test_local_machine_client_check_does_not_accept_public_address(monkeypatch) -> None:
    monkeypatch.setattr(
        clipboard,
        "_local_machine_addresses",
        lambda: {clipboard.ipaddress.ip_address("192.168.10.20")},
    )

    assert clipboard._is_local_machine_client("127.0.0.1")
    assert clipboard._is_local_machine_client("192.168.10.20")
    assert not clipboard._is_local_machine_client("203.0.113.9")
