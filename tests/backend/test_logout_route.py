from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.main import create_app


def test_logout_returns_concrete_204_and_clears_session_cookies(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'logout.db').as_posix()}",
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
                "password": "1111",
            },
        )
        assert login.status_code == 200, login.text

        logout = client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": login.json()["csrfToken"]},
        )

        assert logout.status_code == 204
        assert logout.content == b""
        assert client.get("/api/auth/session").status_code == 401
        expired = logout.headers.get_list("set-cookie")
        assert any(
            "lumina_session=" in value and "Max-Age=0" in value for value in expired
        )
        assert any(
            "lumina_csrf=" in value and "Max-Age=0" in value for value in expired
        )
