from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.main import create_app


def test_admin_model_discovery_requires_explicit_activation(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login_admin(client)

        pgpt_models = client.get("/api/admin/providers/pgpt/models")
        assert pgpt_models.status_code == 200
        gpt_54 = next(model for model in pgpt_models.json() if model["modelKey"] == "gpt-5.4")
        assert gpt_54["defaultContextWindow"] == 1_050_000
        assert gpt_54["maxOutputTokens"] == 128_000
        assert gpt_54["defaultMaxOutputTokens"] == 42_000
        assert gpt_54["configuredMaxOutputTokens"] == 42_000
        assert gpt_54["outputTokenStep"] == 1_000

        configured = client.patch(
            "/api/admin/providers/pgpt/models/gpt-5.4",
            headers={"X-CSRF-Token": csrf},
            json={
                "capabilities": {
                    **gpt_54["capabilities"],
                    "configured_max_output_tokens": 64_000,
                }
            },
        )
        assert configured.status_code == 200, configured.text
        assert configured.json()["configuredMaxOutputTokens"] == 64_000

        rejected_output_limit = client.patch(
            "/api/admin/providers/pgpt/models/gpt-5.4",
            headers={"X-CSRF-Token": csrf},
            json={
                "capabilities": {
                    **configured.json()["capabilities"],
                    "configured_max_output_tokens": 129_000,
                }
            },
        )
        assert rejected_output_limit.status_code == 422
        assert (
            rejected_output_limit.json()["code"]
            == "model_output_token_limit_exceeded"
        )

        discovered = client.post(
            "/api/admin/providers/pgpt/models/discover",
            headers={"X-CSRF-Token": csrf},
        )
        assert discovered.status_code == 200
        assert discovered.json()["autoActivated"] is False
        assert discovered.json()["items"]

        created = client.post(
            "/api/admin/providers/internal/models",
            headers={"X-CSRF-Token": csrf},
            json={
                "modelKey": "internal-analysis-v1",
                "displayName": "Internal Analysis V1",
                "runtimeModelId": "deployment-analysis-v1",
                "enabled": False,
                "isDefault": False,
                "capabilities": {"tools": True},
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["enabled"] is False
        assert created.json()["defaultContextWindow"] is None
        assert created.json()["maxOutputTokens"] is None

        activated = client.patch(
            "/api/admin/providers/internal/models/internal-analysis-v1",
            headers={"X-CSRF-Token": csrf},
            json={"enabled": True, "isDefault": True},
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["enabled"] is True
        assert activated.json()["isDefault"] is True

        rejected = client.patch(
            "/api/admin/providers/internal/models/internal-analysis-v1",
            headers={"X-CSRF-Token": csrf},
            json={"enabled": False},
        )
        assert rejected.status_code == 409
        assert rejected.json()["code"] == "cannot_disable_default_model"


def _login_admin(client: TestClient) -> str:
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
