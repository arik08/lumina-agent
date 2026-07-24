from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select

from lumina.api.errors import ApiProblem, install_error_handlers
from lumina.api.routes import auth, composer, mcp, projects
from lumina.api.schemas import (
    MessageReferenceInput,
    RunCreate,
    RunMessageInput,
)
from lumina.auth import bootstrap_database, create_user
from lumina.config import Settings, get_settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.migrations import SERVER_ROOT, upgrade_database
from lumina.agent.executor import local_run_executor
from lumina.mcp.runtime import (
    McpRuntime,
    McpRuntimeError,
    PreparedMcpTool,
    load_pinned_server_configs,
)
from lumina.mcp.service import validate_configuration
from lumina.models import (
    AuditEvent,
    Conversation,
    McpConfigurationRevision,
    McpSecretBinding,
    Organization,
    Project,
    ProjectMembership,
    ProviderModel,
    Run,
    RunEvent,
    User,
)
from lumina.providers import MockProvider, MockToolCall
from lumina.runs.service import create_run, run_snapshot


def _setup(tmp_path: Path) -> tuple[FastAPI, dict[str, str]]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    with SessionLocal() as db:
        organization = db.scalar(select(Organization))
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert organization is not None and admin is not None
        project = db.scalar(
            select(Project).where(
                Project.owner_user_id == admin.id,
                Project.is_default.is_(True),
            )
        )
        assert project is not None
        alice = create_user(
            db,
            login_name="alice",
            password="alice-pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        bob = create_user(
            db,
            login_name="bob",
            password="bob-pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        db.add_all(
            [
                ProjectMembership(
                    project_id=project.id,
                    user_id=alice.id,
                    role="member",
                    status="active",
                    created_by_user_id=admin.id,
                ),
                ProjectMembership(
                    project_id=project.id,
                    user_id=bob.id,
                    role="member",
                    status="active",
                    created_by_user_id=admin.id,
                ),
            ]
        )
        conversation = Conversation(
            organization_id=organization.id,
            project_id=project.id,
            owner_user_id=alice.id,
            title="MCP 격리 검증",
        )
        admin_conversation = Conversation(
            organization_id=organization.id,
            project_id=project.id,
            owner_user_id=admin.id,
            title="MCP 관리자 실행 검증",
        )
        db.add_all([conversation, admin_conversation])
        db.commit()
        ids = {
            "admin_id": admin.id,
            "alice_id": alice.id,
            "bob_id": bob.id,
            "project_id": project.id,
            "conversation_id": conversation.id,
            "admin_conversation_id": admin_conversation.id,
        }

    application = FastAPI()
    application.state.settings = settings
    application.dependency_overrides[get_settings] = lambda: settings
    install_error_handlers(application)
    for module in (auth, projects, mcp, composer):
        application.include_router(module.router, prefix="/api")
    return application, ids


def _login(client: TestClient, name: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": name,
            "loginDomain": "posco.com",
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrfToken"])


def _configuration(*, timeout_seconds: int = 30) -> dict[str, object]:
    return {
        "transport": "streamable_http",
        "urlTemplate": "https://mcp.corp.example/v1/mcp",
        "allowedHosts": ["mcp.corp.example"],
        "headerTemplates": {"Authorization": "Bearer ${INTERNAL_API_TOKEN}"},
        "tools": [
            {
                "name": "search_docs",
                "description": "승인된 문서를 검색합니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "get_doc",
                "description": "문서 한 건을 조회합니다.",
                "inputSchema": {"type": "object"},
            },
        ],
        "requiredSecretNames": ["INTERNAL_API_TOKEN"],
        "timeoutSeconds": timeout_seconds,
    }


def test_mcp_catalog_binding_snapshot_and_cross_user_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids = _setup(tmp_path)
    alice_ref = "vault://users/alice/mcp/internal-search"
    bob_ref = "vault://users/bob/mcp/internal-search"
    admin_ref = "env://LUMINA_TEST_MCP_TOKEN"
    with (
        TestClient(app) as admin_client,
        TestClient(app) as alice_client,
        TestClient(app) as bob_client,
    ):
        admin_csrf = _login(admin_client, "admin", "1")
        alice_csrf = _login(alice_client, "alice", "alice-pw")
        bob_csrf = _login(bob_client, "bob", "bob-pw")

        forbidden = alice_client.post(
            "/api/admin/mcp-definitions",
            headers={"X-CSRF-Token": alice_csrf},
            json={
                "name": "허용되지 않은 MCP",
                "configuration": _configuration(),
            },
        )
        assert forbidden.status_code == 403

        invalid_command = admin_client.post(
            "/api/admin/mcp-definitions",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "name": "위험 명령",
                "configuration": {
                    "transport": "stdio",
                    "command": ["powershell", "-Command", "whoami"],
                    "tools": [{"name": "unsafe", "inputSchema": {"type": "object"}}],
                },
            },
        )
        assert invalid_command.status_code == 422
        assert invalid_command.json()["code"] == "mcp_command_not_allowed"

        inline_secret = admin_client.post(
            "/api/admin/mcp-definitions",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "name": "비밀값 직접 입력",
                "configuration": {
                    "transport": "stdio",
                    "command": ["node", "server.js", "sk-this-must-not-be-stored"],
                    "tools": [{"name": "unsafe", "inputSchema": {"type": "object"}}],
                },
            },
        )
        assert inline_secret.status_code == 422
        assert inline_secret.json()["code"] == "mcp_inline_secret_forbidden"

        invalid_host = admin_client.post(
            "/api/admin/mcp-definitions",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "name": "허용되지 않은 URL",
                "configuration": {
                    **_configuration(),
                    "allowedHosts": ["other.corp.example"],
                },
            },
        )
        assert invalid_host.status_code == 422
        assert invalid_host.json()["code"] == "mcp_host_not_allowed"

        created = admin_client.post(
            "/api/admin/mcp-definitions",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "name": "사내 문서 검색",
                "slug": "internal-search",
                "description": "승인된 사내 문서를 검색합니다.",
                "configuration": _configuration(),
            },
        )
        assert created.status_code == 201, created.text
        definition = created.json()
        assert definition["status"] == "draft"
        revision_one = definition["revisions"][0]
        assert revision_one["validationStatus"] == "validated"
        assert revision_one["healthStatus"] == "not_connected"
        assert revision_one["schemaStatus"] == "declared"
        assert alice_client.get("/api/mcp/catalog").json() == []

        approved = admin_client.post(
            f"/api/admin/mcp-definitions/{definition['id']}/approve",
            headers={"X-CSRF-Token": admin_csrf},
            json={"configurationRevisionId": revision_one["id"]},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        catalog = alice_client.get("/api/mcp/catalog")
        assert catalog.status_code == 200
        assert catalog.json()[0]["skillWrapper"] == {
            "wrapped": False,
            "name": None,
        }
        assert catalog.json()[0]["revisions"][0]["target"] == "mcp.corp.example"
        assert "configuration" not in catalog.json()[0]["revisions"][0]

        installed = admin_client.post(
            "/api/mcp/installations",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "definitionId": definition["id"],
                "configurationRevisionId": revision_one["id"],
                "scopeType": "project",
                "scopeId": ids["project_id"],
                "toolAllowlist": ["search_docs"],
            },
        )
        assert installed.status_code == 201, installed.text
        installation = installed.json()
        assert installation["configurationRevision"] == 1
        assert installation["boundSecrets"] == [
            {
                "name": "INTERNAL_API_TOKEN",
                "bound": False,
                "resolvable": False,
                "resolverStatus": "binding_required",
                "canBind": True,
            }
        ]
        assert installation["secretResolutionStatus"] == "binding_required"
        assert installation["supportedSecretSchemes"] == ["env"]
        assert installation["secretBindingRole"] == "admin"
        assert installation["ready"] is False

        user_installation = admin_client.post(
            "/api/mcp/installations",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "definitionId": definition["id"],
                "configurationRevisionId": revision_one["id"],
                "scopeType": "user",
                "toolAllowlist": ["search_docs"],
            },
        )
        assert user_installation.status_code == 201, user_installation.text
        assert user_installation.json()["projectIds"] is None
        user_installation_id = user_installation.json()["id"]
        user_scope_disabled = admin_client.patch(
            f"/api/mcp/installations/{user_installation_id}",
            headers={"X-CSRF-Token": admin_csrf},
            json={"projectIds": []},
        )
        assert user_scope_disabled.status_code == 200, user_scope_disabled.text
        assert user_scope_disabled.json()["projectIds"] == []
        assert all(
            item["id"] != user_installation_id
            for item in admin_client.get(
                "/api/mcp/installations",
                params={"project_id": ids["project_id"]},
            ).json()
        )

        no_candidate = alice_client.get(
            "/api/composer/suggestions",
            params={"project_id": ids["project_id"], "trigger": "$"},
        )
        assert no_candidate.status_code == 200
        assert all(item["kind"] != "mcp" for item in no_candidate.json()["items"])

        environment_binding = alice_client.put(
            f"/api/mcp/installations/{installation['id']}/secrets/INTERNAL_API_TOKEN",
            headers={"X-CSRF-Token": alice_csrf},
            json={"secretRef": "env://OPENAI_API_KEY"},
        )
        assert environment_binding.status_code == 403
        assert environment_binding.json()["code"] == (
            "mcp_environment_secret_admin_required"
        )

        alice_bound = alice_client.put(
            f"/api/mcp/installations/{installation['id']}/secrets/INTERNAL_API_TOKEN",
            headers={"X-CSRF-Token": alice_csrf},
            json={"secretRef": alice_ref},
        )
        assert alice_bound.status_code == 200, alice_bound.text
        assert alice_bound.json()["boundSecrets"] == [
            {
                "name": "INTERNAL_API_TOKEN",
                "bound": True,
                "resolvable": False,
                "resolverStatus": "resolver_unavailable",
                "canBind": False,
            }
        ]
        assert alice_bound.json()["secretResolutionStatus"] == ("resolver_unavailable")
        assert alice_bound.json()["ready"] is False
        assert alice_ref not in alice_bound.text

        bob_view = bob_client.get(
            "/api/mcp/installations", params={"project_id": ids["project_id"]}
        )
        assert bob_view.status_code == 200
        assert bob_view.json()[0]["boundSecrets"] == [
            {
                "name": "INTERNAL_API_TOKEN",
                "bound": False,
                "resolvable": False,
                "resolverStatus": "administrator_required",
                "canBind": False,
            }
        ]
        assert bob_view.json()[0]["secretResolutionStatus"] == (
            "administrator_required"
        )
        assert bob_view.json()[0]["ready"] is False
        bob_remove_alice = bob_client.delete(
            f"/api/mcp/installations/{installation['id']}/secrets/INTERNAL_API_TOKEN",
            headers={"X-CSRF-Token": bob_csrf},
        )
        assert bob_remove_alice.status_code == 404

        bob_bound = bob_client.put(
            f"/api/mcp/installations/{installation['id']}/secrets/INTERNAL_API_TOKEN",
            headers={"X-CSRF-Token": bob_csrf},
            json={"secretRef": bob_ref},
        )
        assert bob_bound.status_code == 200
        assert bob_bound.json()["ready"] is False
        assert bob_bound.json()["secretResolutionStatus"] == ("resolver_unavailable")
        assert bob_ref not in bob_bound.text

        unsupported_suggestions = alice_client.get(
            "/api/composer/suggestions",
            params={"project_id": ids["project_id"], "trigger": "$"},
        )
        assert all(
            item["kind"] != "mcp" for item in unsupported_suggestions.json()["items"]
        )

        admin_bound = admin_client.put(
            f"/api/mcp/installations/{installation['id']}/secrets/INTERNAL_API_TOKEN",
            headers={"X-CSRF-Token": admin_csrf},
            json={"secretRef": admin_ref},
        )
        assert admin_bound.status_code == 200, admin_bound.text
        assert admin_bound.json()["ready"] is False
        assert admin_bound.json()["secretResolutionStatus"] == "ready"
        assert admin_bound.json()["boundSecrets"][0]["resolvable"] is True
        assert admin_ref not in admin_bound.text

        answer_test_without_real_provider = admin_client.post(
            f"/api/mcp/installations/{installation['id']}/answer-test",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "projectId": ids["project_id"],
                "prompt": "검색 연결이 실제로 동작하는지 확인해 주세요.",
            },
        )
        assert answer_test_without_real_provider.status_code == 409
        assert (
            answer_test_without_real_provider.json()["code"]
            == "real_provider_required"
        )

        with SessionLocal() as db:
            organization = db.scalar(select(Organization))
            test_model = next(
                model
                for model in db.scalars(select(ProviderModel))
                if model.enabled and model.capabilities_json.get("tools") is True
            )
            assert organization is not None
            organization.initial_execution_settings_json = {
                "providerId": test_model.provider_id,
                "modelKey": test_model.model_key,
                "effortId": "auto",
            }
            db.commit()

        async def prepare_answer_test(
            _runtime: McpRuntime, configs: object
        ) -> tuple[PreparedMcpTool, ...]:
            config = tuple(configs)[0]  # type: ignore[arg-type]
            return (
                PreparedMcpTool(
                    provider_name="mcp_answer_test_search",
                    server_slug=config.slug,
                    original_name="search_docs",
                    description="Search documents",
                    input_schema={"type": "object"},
                    config=config,
                ),
            )

        async def call_answer_test_tool(
            _runtime: McpRuntime, _tool: PreparedMcpTool, arguments: object
        ) -> dict[str, object]:
            assert arguments == {"query": "연결 확인"}
            return {"content": [{"type": "text", "text": "실제 MCP 결과"}]}

        class AnswerTestProvider:
            async def stream(self, request: object):  # type: ignore[no-untyped-def]
                provider_request = request  # keep the test provider protocol explicit
                delegate = (
                    MockProvider(
                        text_chunks=(),
                        tool_call=MockToolCall(
                            name="mcp_answer_test_search",
                            arguments={"query": "연결 확인"},
                        ),
                    )
                    if provider_request.tools
                    else MockProvider(text_chunks=("실제 MCP 결과로 답변했습니다.",))
                )
                async for event in delegate.stream(provider_request):
                    yield event

        monkeypatch.setattr(McpRuntime, "prepare_servers", prepare_answer_test)
        monkeypatch.setattr(McpRuntime, "call_tool", call_answer_test_tool)
        monkeypatch.setattr(
            local_run_executor,
            "provider_for_probe",
            lambda _provider_id: AnswerTestProvider(),
        )
        answer_test = admin_client.post(
            f"/api/mcp/installations/{installation['id']}/answer-test",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "projectId": ids["project_id"],
                "prompt": "검색 연결이 실제로 동작하는지 확인해 주세요.",
            },
        )
        assert answer_test.status_code == 200, answer_test.text
        assert answer_test.json()["answer"] == "실제 MCP 결과로 답변했습니다."
        assert answer_test.json()["toolName"] == "search_docs"

        async def prepare_success(
            _runtime: McpRuntime, _configs: object
        ) -> tuple[object, ...]:
            return ()

        monkeypatch.setattr(McpRuntime, "prepare_servers", prepare_success)
        verified = admin_client.post(
            f"/api/mcp/installations/{installation['id']}/verify",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["healthStatus"] == "connected"
        assert verified.json()["schemaStatus"] == "valid"
        assert verified.json()["ready"] is True
        assert verified.json()["connectionErrorCode"] is None

        async def prepare_failure(
            _runtime: McpRuntime, _configs: object
        ) -> tuple[object, ...]:
            raise McpRuntimeError(
                "mcp_transport_failed",
                "MCP 서버에 안전하게 연결할 수 없습니다.",
                stage="network",
            )

        monkeypatch.setattr(McpRuntime, "prepare_servers", prepare_failure)
        unavailable = admin_client.post(
            f"/api/mcp/installations/{installation['id']}/verify",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert unavailable.status_code == 200, unavailable.text
        assert unavailable.json()["healthStatus"] == "failed"
        assert unavailable.json()["schemaStatus"] == "pending"
        assert unavailable.json()["ready"] is False
        assert unavailable.json()["connectionErrorCode"] == "mcp_transport_failed"

        suggestions = admin_client.get(
            "/api/composer/suggestions",
            params={"project_id": ids["project_id"], "trigger": "$"},
        )
        assert suggestions.status_code == 200
        mcp_candidate = next(
            item for item in suggestions.json()["items"] if item["kind"] == "mcp"
        )
        assert mcp_candidate["referenceId"] == definition["id"]
        assert mcp_candidate["versionOrDigest"] == revision_one["digest"]
        assert mcp_candidate["description"] == "승인된 사내 문서를 검색합니다."

        with SessionLocal() as db:
            admin = db.get(User, ids["admin_id"])
            assert admin is not None
            run, message, was_created = create_run(
                db,
                user=admin,
                conversation_id=ids["admin_conversation_id"],
                payload=RunCreate(
                    message=RunMessageInput(
                        text="$mcp:internal-search 최신 규정을 찾아주세요.",
                        prompt_references=[
                            MessageReferenceInput(
                                kind="mcp",
                                reference_id=definition["id"],
                                version_or_digest=revision_one["digest"],
                            )
                        ],
                    )
                ),
                idempotency_key="mcp-snapshot-0001",
            )
            assert was_created is True and message.run_id == run.id
            frozen = run.snapshot_json["mcp_servers"][0]
            assert frozen["configuration_revision_id"] == revision_one["id"]
            assert frozen["configuration_revision"] == 1
            assert frozen["digest"] == revision_one["digest"]
            assert frozen["tool_allowlist"] == ["search_docs"]

            inferred_run, inferred_message, inferred_created = create_run(
                db,
                user=admin,
                conversation_id=ids["admin_conversation_id"],
                payload=RunCreate(
                    message=RunMessageInput(
                        text="$mcp:internal-search 최신 규정을 다시 찾아주세요.",
                        prompt_references=[],
                    )
                ),
                idempotency_key="mcp-snapshot-inferred-0001",
            )
            assert inferred_created is True
            inferred_reference = inferred_run.snapshot_json["prompt_references"][0]
            assert inferred_reference["kind"] == "mcp"
            assert inferred_reference["reference_id"] == definition["id"]
            assert inferred_reference["version_or_digest"] == revision_one["digest"]
            assert inferred_reference["token_start"] == 0
            assert inferred_reference["token_end"] == len("$mcp:internal-search")
            assert inferred_message.metadata_json["prompt_references"] == [
                inferred_reference
            ]
            assert inferred_run.snapshot_json["mcp_servers"][0]["slug"] == (
                "internal-search"
            )

            serialized_snapshot = json.dumps(
                run.snapshot_json, ensure_ascii=False, default=str
            )
            assert alice_ref not in serialized_snapshot
            assert bob_ref not in serialized_snapshot
            assert admin_ref not in serialized_snapshot
            exposed = json.dumps(run_snapshot(db, run), ensure_ascii=False, default=str)
            assert all(ref not in exposed for ref in (alice_ref, bob_ref, admin_ref))
            run_id = run.id
            db.commit()

        revision_two_response = admin_client.post(
            f"/api/admin/mcp-definitions/{definition['id']}/revisions",
            headers={"X-CSRF-Token": admin_csrf},
            json={"configuration": _configuration(timeout_seconds=45)},
        )
        assert revision_two_response.status_code == 201
        revision_two = revision_two_response.json()["revisions"][1]
        assert revision_two["revision"] == 2
        assert revision_two["digest"] != revision_one["digest"]
        approved_two = admin_client.post(
            f"/api/admin/mcp-definitions/{definition['id']}/approve",
            headers={"X-CSRF-Token": admin_csrf},
            json={"configurationRevisionId": revision_two["id"]},
        )
        assert approved_two.status_code == 200

        still_pinned = admin_client.get(
            "/api/composer/suggestions",
            params={"project_id": ids["project_id"], "trigger": "$"},
        )
        pinned_candidate = next(
            item for item in still_pinned.json()["items"] if item["kind"] == "mcp"
        )
        assert pinned_candidate["versionOrDigest"] == revision_one["digest"]

        disabled = admin_client.patch(
            f"/api/admin/mcp-definitions/{definition['id']}/status",
            headers={"X-CSRF-Token": admin_csrf},
            json={"status": "disabled", "reason": "운영 검토"},
        )
        assert disabled.status_code == 200
        after_disable = admin_client.get(
            "/api/composer/suggestions",
            params={"project_id": ids["project_id"], "trigger": "$"},
        )
        assert all(item["kind"] != "mcp" for item in after_disable.json()["items"])

        revoked = admin_client.patch(
            f"/api/admin/mcp-definitions/{definition['id']}/status",
            headers={"X-CSRF-Token": admin_csrf},
            json={"status": "revoked", "reason": "보안 폐기"},
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        reapproval = admin_client.post(
            f"/api/admin/mcp-definitions/{definition['id']}/approve",
            headers={"X-CSRF-Token": admin_csrf},
            json={"configurationRevisionId": revision_two["id"]},
        )
        assert reapproval.status_code == 409
        assert reapproval.json()["code"] == "mcp_revoked"

        with SessionLocal() as db:
            admin = db.get(User, ids["admin_id"])
            frozen_run = db.get(Run, run_id)
            assert admin is not None and frozen_run is not None
            assert (
                frozen_run.snapshot_json["mcp_servers"][0]["digest"]
                == revision_one["digest"]
            )
            pinned_configs = load_pinned_server_configs(db, frozen_run)
            assert len(pinned_configs) == 1
            assert pinned_configs[0].configuration_revision_id == revision_one["id"]
            assert pinned_configs[0].digest == revision_one["digest"]
            assert pinned_configs[0].tool_allowlist == ("search_docs",)
            original_snapshot = frozen_run.snapshot_json
            tampered_server = {
                **original_snapshot["mcp_servers"][0],
                "digest": "0" * 64,
            }
            frozen_run.snapshot_json = {
                **original_snapshot,
                "mcp_servers": [tampered_server],
            }
            with pytest.raises(McpRuntimeError) as snapshot_error:
                load_pinned_server_configs(db, frozen_run)
            assert snapshot_error.value.code == "mcp_snapshot_mismatch"
            frozen_run.snapshot_json = original_snapshot
            with pytest.raises(ApiProblem) as disabled_error:
                create_run(
                    db,
                    user=admin,
                    conversation_id=ids["admin_conversation_id"],
                    payload=RunCreate(
                        message=RunMessageInput(
                            text="비활성 MCP를 다시 사용해 주세요.",
                            prompt_references=[
                                MessageReferenceInput(
                                    kind="mcp",
                                    reference_id=definition["id"],
                                    version_or_digest=revision_one["digest"],
                                )
                            ],
                        )
                    ),
                    idempotency_key="mcp-disabled-0001",
                )
            assert disabled_error.value.code == "extension_not_installed"

            bindings = list(
                db.scalars(
                    select(McpSecretBinding).where(
                        McpSecretBinding.installation_id == installation["id"]
                    )
                )
            )
            assert {(item.user_id, item.secret_ref) for item in bindings} == {
                (ids["alice_id"], alice_ref),
                (ids["bob_id"], bob_ref),
                (ids["admin_id"], admin_ref),
            }
            revision_one_row = db.get(McpConfigurationRevision, revision_one["id"])
            assert revision_one_row is not None
            assert revision_one_row.config_digest == revision_one["digest"]
            events = list(
                db.scalars(select(AuditEvent).where(AuditEvent.action.like("mcp_%")))
            )
            audit_json = json.dumps(
                [event.metadata_json for event in events],
                ensure_ascii=False,
                default=str,
            )
            run_event_json = json.dumps(
                list(
                    db.scalars(
                        select(RunEvent.payload_json).where(RunEvent.run_id == run_id)
                    )
                ),
                ensure_ascii=False,
                default=str,
            )
            assert all(ref not in audit_json for ref in (alice_ref, bob_ref, admin_ref))
            assert all(
                ref not in run_event_json for ref in (alice_ref, bob_ref, admin_ref)
            )


def test_user_mcp_installation_can_be_scoped_by_project(tmp_path: Path) -> None:
    app, ids = _setup(tmp_path)
    with TestClient(app) as admin_client, TestClient(app) as alice_client:
        admin_csrf = _login(admin_client, "admin", "1")
        alice_csrf = _login(alice_client, "alice", "alice-pw")

        created = admin_client.post(
            "/api/admin/mcp-definitions",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "name": "프로젝트별 MCP",
                "slug": "project-scoped-mcp",
                "description": "프로젝트별 사용 여부를 검증합니다.",
                "configuration": _configuration(),
            },
        )
        assert created.status_code == 201, created.text
        definition = created.json()
        revision = definition["revisions"][0]
        approved = admin_client.post(
            f"/api/admin/mcp-definitions/{definition['id']}/approve",
            headers={"X-CSRF-Token": admin_csrf},
            json={"configurationRevisionId": revision["id"]},
        )
        assert approved.status_code == 200, approved.text

        second_project = alice_client.post(
            "/api/projects",
            headers={"X-CSRF-Token": alice_csrf},
            json={"name": "MCP 제외 프로젝트"},
        )
        assert second_project.status_code == 201, second_project.text
        installed = alice_client.post(
            "/api/mcp/installations",
            headers={"X-CSRF-Token": alice_csrf},
            json={
                "definitionId": definition["id"],
                "configurationRevisionId": revision["id"],
                "scopeType": "user",
                "toolAllowlist": ["search_docs"],
            },
        )
        assert installed.status_code == 201, installed.text
        assert installed.json()["projectIds"] is None

        scoped = alice_client.patch(
            f"/api/mcp/installations/{installed.json()['id']}",
            headers={"X-CSRF-Token": alice_csrf},
            json={"projectIds": [ids["project_id"]]},
        )
        assert scoped.status_code == 200, scoped.text
        assert scoped.json()["projectIds"] == [ids["project_id"]]
        assert any(
            item["id"] == installed.json()["id"]
            for item in alice_client.get(
                "/api/mcp/installations", params={"project_id": ids["project_id"]}
            ).json()
        )
        assert all(
            item["id"] != installed.json()["id"]
            for item in alice_client.get(
                "/api/mcp/installations",
                params={"project_id": second_project.json()["id"]},
            ).json()
        )


def test_mcp_migration_0006_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "mcp-round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url)
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url

    command.downgrade(config, "0005")
    engine = create_engine(database_url)
    try:
        assert {
            "mcp_definitions",
            "mcp_configuration_revisions",
            "mcp_installations",
            "mcp_secret_bindings",
        }.isdisjoint(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0005"
            )
    finally:
        engine.dispose()

    command.upgrade(config, "0006")
    engine = create_engine(database_url)
    try:
        assert {
            "mcp_definitions",
            "mcp_configuration_revisions",
            "mcp_installations",
            "mcp_secret_bindings",
        } <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0006"
            )
    finally:
        engine.dispose()
    command.upgrade(config, "head")


def test_mcp_header_templates_reject_unsafe_secret_locations() -> None:
    base: dict[str, object] = {
        "transport": "streamable_http",
        "url_template": "https://mcp.example.test/v1/mcp",
        "allowed_hosts": ["mcp.example.test"],
        "header_templates": {"Authorization": "Bearer ${API_TOKEN}"},
        "tools": [{"name": "echo", "inputSchema": {"type": "object"}}],
        "required_secret_names": ["API_TOKEN"],
    }
    normalized, _digest = validate_configuration(base)
    assert normalized["header_templates"] == {"Authorization": "Bearer ${API_TOKEN}"}
    corporate = {
        **base,
        "url_template": "https://10.20.30.40/v1/mcp",
        "allowed_hosts": ["10.20.30.40"],
        "allowed_ip_ranges": ["10.0.0.0/8"],
    }
    normalized_corporate, _corporate_digest = validate_configuration(corporate)
    assert normalized_corporate["allowed_ip_ranges"] == ["10.0.0.0/8"]

    unsafe_cases = (
        (
            {**base, "url_template": "https://mcp.example.test/${API_TOKEN}"},
            "mcp_secret_in_target_forbidden",
        ),
        (
            {
                "transport": "stdio",
                "command": ["python", "server.py", "${API_TOKEN}"],
                "tools": base["tools"],
                "required_secret_names": ["API_TOKEN"],
            },
            "mcp_secret_in_target_forbidden",
        ),
        (
            {**base, "header_templates": {"Cookie": "${API_TOKEN}"}},
            "mcp_header_not_allowed",
        ),
        (
            {
                **base,
                "header_templates": {
                    "Authorization": "Bearer ${API_TOKEN}\r\nX-Evil: yes"
                },
            },
            "mcp_header_template_invalid",
        ),
        (
            {**base, "header_templates": {"Authorization": "Bearer literal"}},
            "mcp_header_template_invalid",
        ),
        (
            {**base, "allowed_ip_ranges": ["8.8.8.0/24"]},
            "mcp_ip_range_invalid",
        ),
        (
            {**base, "allowed_ip_ranges": ["169.254.0.0/16"]},
            "mcp_ip_range_invalid",
        ),
        (
            {**base, "allowed_ip_ranges": ["10.1.2.3/8"]},
            "mcp_ip_range_invalid",
        ),
    )
    for configuration, expected_code in unsafe_cases:
        with pytest.raises(ApiProblem) as error:
            validate_configuration(configuration)
        assert error.value.code == expected_code


def test_mcp_migration_0009_adds_header_templates(tmp_path: Path) -> None:
    database = tmp_path / "mcp-runtime-headers.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url)
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.downgrade(config, "0008")
    engine = create_engine(database_url)
    try:
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("mcp_configuration_revisions")
        }
        assert "header_templates_json" not in columns
        assert "allowed_ip_ranges_json" not in columns
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0008"
            )
    finally:
        engine.dispose()
    command.upgrade(config, "0009")
    engine = create_engine(database_url)
    try:
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("mcp_configuration_revisions")
        }
        assert {"header_templates_json", "allowed_ip_ranges_json"} <= columns
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0009"
            )
    finally:
        engine.dispose()
    command.upgrade(config, "head")
