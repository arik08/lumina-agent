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
        pgpt_api_key="test-api-key",
        pgpt_employee_no="test-employee",
        pgpt_company_code="30",
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login_admin(client)

        initial_execution = client.get("/api/admin/providers/initial-execution")
        assert initial_execution.status_code == 200
        assert initial_execution.json()["source"] == "application"

        configured_initial_execution = client.patch(
            "/api/admin/providers/initial-execution",
            headers={"X-CSRF-Token": csrf},
            json={
                "execution": {
                    "providerId": "pgpt",
                    "modelKey": "gpt-5.4",
                    "effortId": "high",
                }
            },
        )
        assert configured_initial_execution.status_code == 200
        assert configured_initial_execution.json() == {
            "execution": {
                "providerId": "pgpt",
                "modelKey": "gpt-5.4",
                "effortId": "high",
            },
            "source": "organization",
        }
        current_settings = client.get("/api/settings/current").json()
        assert (
            current_settings["execution"]
            == configured_initial_execution.json()["execution"]
        )
        assert current_settings["source"]["execution"] == "organization"

        for invalid_settings in (
            {},
            {"theme": None},
            {"conversationWidth": None},
            {"conversationFontSize": None},
            {"outputMode": None},
            {"analysisDepth": None},
            {"answerLength": None},
            {"clarificationMode": None},
            {"execution": None},
            {"modelCandidates": None},
        ):
            rejected_settings = client.patch(
                "/api/settings/current",
                headers={"X-CSRF-Token": csrf},
                json={
                    **invalid_settings,
                    "expectedRevision": current_settings["revision"],
                },
            )
            assert rejected_settings.status_code == 422, (
                invalid_settings,
                rejected_settings.text,
            )
        assert client.get("/api/settings/current").json()["revision"] == (
            current_settings["revision"]
        )

        personal_execution = client.patch(
            "/api/settings/current",
            headers={"X-CSRF-Token": csrf},
            json={
                "execution": {
                    "providerId": "pgpt",
                    "modelKey": "gpt-5.4-mini",
                    "effortId": "low",
                },
                "expectedRevision": current_settings["revision"],
            },
        )
        assert personal_execution.status_code == 200, personal_execution.text
        assert personal_execution.json()["source"]["execution"] == "user"
        changed_organization_default = client.patch(
            "/api/admin/providers/initial-execution",
            headers={"X-CSRF-Token": csrf},
            json={
                "execution": {
                    "providerId": "codex",
                    "modelKey": "gpt-5.4",
                    "effortId": "medium",
                }
            },
        )
        assert changed_organization_default.status_code == 200
        restored_personal = client.get("/api/settings/current").json()
        assert restored_personal["execution"] == personal_execution.json()["execution"]
        assert restored_personal["source"]["execution"] == "user"

        invalid_initial_effort = client.patch(
            "/api/admin/providers/initial-execution",
            headers={"X-CSRF-Token": csrf},
            json={
                "execution": {
                    "providerId": "pgpt",
                    "modelKey": "gpt-5.4",
                    "effortId": "extreme",
                }
            },
        )
        assert invalid_initial_effort.status_code == 409
        assert invalid_initial_effort.json()["code"] == "initial_execution_unavailable"

        pgpt_models = client.get("/api/admin/providers/pgpt/models")
        assert pgpt_models.status_code == 200
        assert [model["modelKey"] for model in pgpt_models.json()] == [
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.5",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
        ]
        gpt_54 = next(
            model for model in pgpt_models.json() if model["modelKey"] == "gpt-5.4"
        )
        assert gpt_54["defaultContextWindow"] == 272_000
        assert gpt_54["defaultContextUsageRatio"] == 0.85
        assert gpt_54["contextCapacityMode"] == "standard"
        assert gpt_54["maximumContextWindow"] == 1_050_000
        assert gpt_54["maximumInputTokens"] == 911_900
        assert gpt_54["maximumContextUsageRatio"] == 0.75
        assert gpt_54["contextPolicyLocked"] is False
        assert gpt_54["maxInputTokens"] == 272_000
        assert gpt_54["defaultMaxInputTokens"] == 272_000
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

        configured_maximum_context = client.patch(
            "/api/admin/providers/pgpt/models/gpt-5.4",
            headers={"X-CSRF-Token": csrf},
            json={
                "capabilities": {
                    **configured.json()["capabilities"],
                    "context_capacity_mode": "maximum",
                    "context_window": 1_050_000,
                    "max_input_tokens": 911_900,
                    "context_compaction_threshold": 0.75,
                }
            },
        )
        assert configured_maximum_context.status_code == 200, (
            configured_maximum_context.text
        )
        assert configured_maximum_context.json()["contextCapacityMode"] == "maximum"
        assert (
            configured_maximum_context.json()["capabilities"]["context_window"]
            == 1_050_000
        )
        assert configured_maximum_context.json()["maxInputTokens"] == 911_900
        assert configured_maximum_context.json()["defaultMaxInputTokens"] == 272_000

        configured_ratio = client.patch(
            "/api/admin/providers/pgpt/models/gpt-5.4",
            headers={"X-CSRF-Token": csrf},
            json={
                "capabilities": {
                    **configured_maximum_context.json()["capabilities"],
                    "context_compaction_threshold": 0.8,
                }
            },
        )
        assert configured_ratio.status_code == 422, configured_ratio.text
        assert (
            configured_ratio.json()["code"] == "context_capacity_profile_mismatch"
        )

        rejected_ratio = client.patch(
            "/api/admin/providers/pgpt/models/gpt-5.4",
            headers={"X-CSRF-Token": csrf},
            json={
                "capabilities": {
                    **configured_maximum_context.json()["capabilities"],
                    "context_compaction_threshold": 1.01,
                }
            },
        )
        assert rejected_ratio.status_code == 422
        assert rejected_ratio.json()["code"] == "invalid_context_usage_ratio"

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
            rejected_output_limit.json()["code"] == "model_output_token_limit_exceeded"
        )

        codex_models = client.get("/api/admin/providers/codex/models")
        assert codex_models.status_code == 200
        codex_gpt_54 = next(
            model for model in codex_models.json() if model["modelKey"] == "gpt-5.4"
        )
        assert codex_gpt_54["defaultContextWindow"] == 272_000
        assert codex_gpt_54["defaultContextUsageRatio"] == 0.85
        assert codex_gpt_54["contextPolicyLocked"] is True
        assert codex_gpt_54["maxInputTokens"] is None
        assert codex_gpt_54["defaultMaxInputTokens"] is None

        rejected_codex_policy = client.patch(
            "/api/admin/providers/codex/models/gpt-5.4",
            headers={"X-CSRF-Token": csrf},
            json={
                "capabilities": {
                    **codex_gpt_54["capabilities"],
                    "context_window": 200_000,
                    "context_compaction_threshold": 0.75,
                }
            },
        )
        assert rejected_codex_policy.status_code == 422
        assert rejected_codex_policy.json()["code"] == "model_context_policy_locked"

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

        for invalid_patch in (
            {"displayName": None},
            {"runtimeModelId": None},
            {"aliases": None},
            {"enabled": None},
            {"isDefault": None},
            {"sortOrder": None},
            {"capabilities": None},
        ):
            rejected_null = client.patch(
                "/api/admin/providers/internal/models/internal-analysis-v1",
                headers={"X-CSRF-Token": csrf},
                json=invalid_patch,
            )
            assert rejected_null.status_code == 422, (
                invalid_patch,
                rejected_null.text,
            )

        activated = client.patch(
            "/api/admin/providers/internal/models/internal-analysis-v1",
            headers={"X-CSRF-Token": csrf},
            json={"enabled": True, "isDefault": True},
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["enabled"] is True
        assert activated.json()["isDefault"] is True

        disabled = client.patch(
            "/api/admin/providers/internal/models/internal-analysis-v1",
            headers={"X-CSRF-Token": csrf},
            json={"enabled": False},
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["enabled"] is False
        assert disabled.json()["isDefault"] is False
        assert all(
            item["id"] != "internal" for item in client.get("/api/providers").json()
        )

        enabled_provider = client.patch(
            "/api/admin/providers/internal",
            headers={"X-CSRF-Token": csrf},
            json={"enabled": True},
        )
        assert enabled_provider.status_code == 200, enabled_provider.text
        assert enabled_provider.json()["enabled"] is True
        assert enabled_provider.json()["enabledModelCount"] == 1

        admin_providers = client.get("/api/admin/providers")
        assert admin_providers.status_code == 200
        internal = next(
            item for item in admin_providers.json() if item["id"] == "internal"
        )
        assert internal["enabled"] is True
        assert internal["modelCount"] == 1


def test_provider_availability_management_requires_admin(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        admin_csrf = _login_admin(client)
        created = client.post(
            "/api/admin/users",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "loginName": "general-user",
                "loginDomain": "posco.com",
                "password": "pw",
                "role": "user",
                "status": "active",
            },
        )
        assert created.status_code == 201, created.text
        client.post("/api/auth/logout", headers={"X-CSRF-Token": admin_csrf})
        login = client.post(
            "/api/auth/login",
            json={
                "loginName": "general-user",
                "loginDomain": "posco.com",
                "password": "pw",
            },
        )
        assert login.status_code == 200
        csrf = login.json()["csrfToken"]

        assert client.get("/api/admin/providers").status_code == 403
        assert (
            client.patch(
                "/api/admin/providers/codex",
                headers={"X-CSRF-Token": csrf},
                json={"enabled": False},
            ).status_code
            == 403
        )


def _login_admin(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1111",
        },
    )
    assert response.status_code == 200
    return response.json()["csrfToken"]
