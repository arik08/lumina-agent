from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from lumina.agent.executor import local_run_executor
from lumina.agent.image_tool import ImageToolError, prepare_image_tool
from lumina.artifacts.reporting import ReportImage, generate_report
from lumina.artifacts.service import validate_artifact_content
from lumina.auth import bootstrap_database, create_user
from lumina.config import Settings
from lumina.db import Base, SessionLocal
from lumina.main import create_app
from lumina.models import (
    ArtifactVersion,
    Attachment,
    Conversation,
    Project,
    ProviderModel,
    Run,
    RunEvent,
    ToolExecution,
    User,
)
from lumina.providers import (
    MockProvider,
    MockToolCall,
    ProviderCapabilities,
    ProviderEvent,
    ProviderRequest,
    ProviderRequestError,
    initial_model_catalog,
)
from lumina.providers.codex import (
    CodexImageGenerator,
    CodexResponsesAdapter,
    GeneratedImage,
    ImageGenerationRequest,
)
from lumina.storage import ManagedLocalStorage


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl8sAAAAASUVORK5CYII="
)


@pytest.mark.asyncio
async def test_codex_image_generator_uses_responses_hosted_tool_and_validates_png() -> (
    None
):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.test/v1/responses"
        assert request.headers["Authorization"] == "Bearer test-openai-key"
        payload = json.loads(request.content)
        assert payload == {
            "model": "gpt-5.6-sol",
            "input": "코발트 블루 설비 다이어그램을 그려 주세요.",
            "tools": [
                {
                    "type": "image_generation",
                    "model": "gpt-image-2",
                    "action": "generate",
                    "size": "1024x1024",
                    "quality": "medium",
                    "output_format": "png",
                    "background": "opaque",
                }
            ],
            "tool_choice": {"type": "image_generation"},
            "store": False,
        }
        return httpx.Response(
            200,
            json={
                "id": "resp_image_1",
                "model": "gpt-5.6-sol-2026-07-01",
                "output": [
                    {
                        "id": "ig_1",
                        "type": "image_generation_call",
                        "status": "completed",
                        "model": "gpt-image-2",
                        "revised_prompt": "A cobalt industrial equipment diagram.",
                        "result": base64.b64encode(_PNG).decode("ascii"),
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = CodexImageGenerator(
            api_key="test-openai-key",
            base_url="https://api.openai.test/v1",
            client=client,
            max_output_bytes=1024,
        )
        generated = await generator.generate(
            ImageGenerationRequest(
                model="gpt-5.6-sol",
                image_model="gpt-image-2",
                prompt="코발트 블루 설비 다이어그램을 그려 주세요.",
                size="1024x1024",
                quality="medium",
                output_format="png",
                background="opaque",
            )
        )

    assert generated.content == _PNG
    assert generated.mime_type == "image/png"
    assert generated.actual_model == "gpt-image-2"
    assert generated.actual_model_reported is True
    assert generated.revised_prompt_hash is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "maximum", "stage"),
    [
        (b"not-an-image", 1024, "validation"),
        (b"\x89PNG\r\n\x1a\n" + b"x" * 2048, 1024, "validation"),
    ],
)
async def test_codex_image_generator_rejects_invalid_mime_and_size(
    content: bytes, maximum: int, stage: str
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "gpt-5.6-sol",
                "output": [
                    {
                        "type": "image_generation_call",
                        "result": base64.b64encode(content).decode("ascii"),
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = CodexImageGenerator(
            api_key="secret",
            base_url="https://api.openai.test/v1",
            client=client,
            max_output_bytes=maximum,
        )
        with pytest.raises(ProviderRequestError) as captured:
            await generator.generate(
                ImageGenerationRequest(
                    model="gpt-5.6-sol",
                    image_model="gpt-image-2",
                    prompt="draw",
                    size="auto",
                    quality="auto",
                    output_format="png",
                    background="opaque",
                )
            )
    assert captured.value.stage == stage
    assert base64.b64encode(content).decode("ascii") not in str(captured.value)


def test_codex_catalog_and_legacy_seed_merge_preserve_adapter_capabilities(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "catalog.db")
    engine = create_engine(
        settings.database_url, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        bootstrap_database(db, settings=settings)
        codex = db.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_id == "codex",
                ProviderModel.model_key == "gpt-5.5",
            )
        )
        pgpt = db.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_id == "pgpt",
                ProviderModel.model_key == "gpt-5.4",
            )
        )
        assert codex is not None and pgpt is not None
        codex.capabilities_json = {
            "text": True,
            "streaming": True,
            "verification_status": "adapter_merge_required",
        }
        pgpt.capabilities_json = {
            "text": True,
            "streaming": True,
            "verification_status": "adapter_merge_required",
        }
        db.commit()

        bootstrap_database(db, settings=settings)
        db.commit()
        assert codex.capabilities_json["image_generation"] is False
        assert codex.capabilities_json["tools"] is True
        assert pgpt.capabilities_json["tools"] is True
        assert pgpt.capabilities_json["structured_output"] is True

        custom = dict(codex.capabilities_json)
        custom["image_generation"] = False
        custom["verification_status"] = "adapter_merge_required"
        codex.capabilities_json = custom
        codex.source = "admin_manual"
        db.commit()
        bootstrap_database(db, settings=settings)
        db.commit()
        assert codex.capabilities_json == custom

    catalog = initial_model_catalog("codex")
    assert [item.capabilities.image_generation for item in catalog] == [False, False]
    engine.dispose()


def test_image_assets_are_embedded_in_html_and_docx_outputs() -> None:
    image = ReportImage(
        source_type="artifact",
        source_id="image-artifact-1",
        source_version=1,
        display_name="설비 배치도.png",
        mime_type="image/png",
        content_hash=hashlib.sha256(_PNG).hexdigest(),
        content=_PNG,
    )
    common = {
        "title": "설비 이미지 보고서",
        "executive_summary": "설비 배치 이미지를 본문 자산으로 포함합니다.",
        "sections": [],
        "action_items": [],
        "image_artifact_ids": [image.source_id],
    }

    html_report = generate_report(
        "이미지를 포함해 주세요.", {**common, "format": "html"}, images=(image,)
    )
    encoded = base64.b64encode(_PNG)
    assert b"data:image/png;base64," + encoded in html_report.content
    assert html_report.asset_manifest[0]["contentHash"] == image.content_hash
    status, validation = validate_artifact_content(
        kind="html", mime_type="text/html", content=html_report.content
    )
    assert status == "structural_passed", validation
    assert validation["renderVerified"] is False

    docx_report = generate_report(
        "이미지를 포함해 주세요.", {**common, "format": "docx"}, images=(image,)
    )
    with ZipFile(BytesIO(docx_report.content)) as archive:
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
        assert media
        assert archive.read(media[0]) == _PNG


def test_prepare_image_tool_rejects_non_codex_missing_capability_and_attachments(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "prepare.db")
    engine = create_engine(
        settings.database_url, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = ManagedLocalStorage(tmp_path / "files")
    with factory() as db:
        bootstrap_database(db, settings=settings)
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        project = db.scalar(select(Project).where(Project.owner_user_id == admin.id))
        assert admin is not None and project is not None

        non_codex = _manual_run(db, admin, project, provider_id="openai", image=True)
        with pytest.raises(ImageToolError) as error:
            prepare_image_tool(
                db,
                storage,
                run_id=non_codex.id,
                tool_call_id="call_non_codex",
                arguments={"prompt": "draw"},
            )
        assert error.value.code == "codex_provider_required"

        no_capability = _manual_run(
            db, admin, project, provider_id="codex", image=False
        )
        with pytest.raises(ImageToolError) as error:
            prepare_image_tool(
                db,
                storage,
                run_id=no_capability.id,
                tool_call_id="call_no_capability",
                arguments={"prompt": "draw"},
            )
        assert error.value.code == "image_generation_unavailable"

        capable = _manual_run(db, admin, project, provider_id="codex", image=True)
        with pytest.raises(ImageToolError) as error:
            prepare_image_tool(
                db,
                storage,
                run_id=capable.id,
                tool_call_id="call_transparent",
                arguments={"prompt": "draw", "background": "transparent"},
            )
        assert error.value.code == "transparent_background_unsupported"

        outsider = create_user(
            db,
            login_name="outsider",
            password="password",
            organization_id=admin.organization_id,
        )
        other_project = db.scalar(
            select(Project).where(Project.owner_user_id == outsider.id)
        )
        assert other_project is not None
        other_conversation = Conversation(
            organization_id=admin.organization_id,
            project_id=other_project.id,
            owner_user_id=outsider.id,
            title="other",
        )
        db.add(other_conversation)
        db.flush()
        foreign_attachment = Attachment(
            organization_id=admin.organization_id,
            project_id=other_project.id,
            conversation_id=other_conversation.id,
            owner_user_id=outsider.id,
            kind="image",
            original_filename="foreign.png",
            sniffed_mime_type="image/png",
            size_bytes=len(_PNG),
            content_hash="a" * 64,
            storage_backend="local",
            storage_key="attachments/foreign.png",
            status="ready",
        )
        db.add(foreign_attachment)
        db.flush()
        with pytest.raises(ImageToolError) as error:
            prepare_image_tool(
                db,
                storage,
                run_id=capable.id,
                tool_call_id="call_foreign",
                arguments={
                    "prompt": "draw",
                    "reference_attachment_ids": [foreign_attachment.id],
                },
            )
        assert error.value.code == "image_attachment_unavailable"

        digest = hashlib.sha256(_PNG).hexdigest()
        stored = storage.put_bytes(
            f"attachments/{capable.id}/{digest}.png",
            _PNG,
            expected_sha256=digest,
        )
        local_attachment = Attachment(
            organization_id=admin.organization_id,
            project_id=project.id,
            conversation_id=capable.conversation_id,
            owner_user_id=admin.id,
            kind="image",
            original_filename="local.png",
            sniffed_mime_type="image/png",
            size_bytes=len(_PNG),
            content_hash=digest,
            storage_backend="local",
            storage_key=stored.key,
            status="ready",
        )
        db.add(local_attachment)
        db.flush()
        with pytest.raises(ImageToolError) as error:
            prepare_image_tool(
                db,
                storage,
                run_id=capable.id,
                tool_call_id="call_reference",
                arguments={
                    "prompt": "draw",
                    "reference_attachment_ids": [local_attachment.id],
                },
            )
        assert error.value.code == "image_reference_unsupported"
    engine.dispose()


def test_codex_image_tool_persists_immutable_versions_without_raw_payloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'image-tool.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        openai_api_key="test-openai-key",
        openai_base_url="https://api.openai.test/v1",
        cookie_secure=False,
    )
    captured_tools: list[list[str]] = []
    destination_artifact_id: str | None = None

    class RecordingProvider:
        provider_id = "codex"
        capabilities = ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            image_generation=True,
        )

        def __init__(self, delegate: MockProvider) -> None:
            self.delegate = delegate

        async def stream(
            self, request: ProviderRequest
        ) -> AsyncIterator[ProviderEvent]:
            captured_tools.append(
                [
                    str(tool.get("function", {}).get("name"))
                    for tool in request.tools
                    if isinstance(tool.get("function"), dict)
                ]
            )
            async for event in self.delegate.stream(request):
                yield event

    def fake_provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> RecordingProvider:
        del wants_artifact
        if first_turn:
            arguments: dict[str, object] = {
                "prompt": "DB에 원문으로 저장되면 안 되는 이미지 지시문",
                "size": "1024x1024",
                "quality": "medium",
                "output_format": "png",
                "background": "opaque",
            }
            if destination_artifact_id:
                arguments["destination_artifact_id"] = destination_artifact_id
            delegate = MockProvider(
                tool_call=MockToolCall(
                    name="generate_image",
                    arguments=arguments,
                    call_id="call_generate_image",
                )
            )
        else:
            delegate = MockProvider(text_chunks=("이미지를 생성했습니다.",))
        return RecordingProvider(delegate)

    class FakeImageGenerator:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
            self.calls += 1
            assert request.image_model == "gpt-image-2"
            assert request.model == "gpt-5.5"
            content = _PNG + (b"second-version" if self.calls == 2 else b"")
            return GeneratedImage(
                content=content,
                mime_type="image/png",
                output_format="png",
                actual_backend="openai_responses.image_generation",
                actual_model="gpt-image-2",
                actual_model_reported=True,
                response_model="gpt-5.5",
                revised_prompt_hash="b" * 64,
            )

    generator = FakeImageGenerator()
    monkeypatch.setattr(local_run_executor, "_provider", fake_provider)
    monkeypatch.setattr(local_run_executor, "_codex_image_generator", lambda: generator)

    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        with SessionLocal() as db:
            model = db.scalar(
                select(ProviderModel).where(
                    ProviderModel.provider_id == "codex",
                    ProviderModel.model_key == "gpt-5.5",
                )
            )
            assert model is not None
            capabilities = dict(model.capabilities_json)
            capabilities["image_generation"] = True
            model.capabilities_json = capabilities
            model.source = "admin_manual"
            db.commit()
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation_id = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "Codex image"},
        ).json()["id"]

        first = _start_codex_run(client, csrf, conversation_id, "codex-image-run-1")
        first_snapshot = _wait_for_terminal(client, first)
        assert first_snapshot["status"] == "completed"
        assert "generate_image" in captured_tools[0]
        assert len(first_snapshot["artifacts"]) == 1
        destination_artifact_id = first_snapshot["artifacts"][0]["id"]
        first_tool = first_snapshot["toolExecutions"][0]
        assert first_tool["status"] == "completed"
        assert "storage_key" not in first_tool["result"]
        first_tools_step = next(
            step for step in first_snapshot["plan"]["steps"] if step["key"] == "tools"
        )
        assert [subtask["status"] for subtask in first_tools_step["subtasks"]] == [
            "completed"
        ]
        assert "prompt" not in first_tool["input"]
        assert first_tool["input"]["prompt_hash"]
        serialized_tool = json.dumps(first_tool, ensure_ascii=False)
        assert "DB에 원문으로 저장되면 안 되는 이미지 지시문" not in serialized_tool
        assert base64.b64encode(_PNG).decode("ascii") not in serialized_tool
        assert "test-openai-key" not in serialized_tool

        first_version = client.get(
            f"/api/artifacts/{destination_artifact_id}/versions/1"
        )
        assert first_version.status_code == 200
        assert first_version.json()["previewUrl"].endswith("version=1")
        assert first_version.json()["metadata"]["sourceRunId"] == first
        preview = client.get(first_version.json()["previewUrl"])
        assert preview.status_code == 200
        assert preview.content == _PNG
        assert preview.headers["content-type"].startswith("image/png")

        second = _start_codex_run(client, csrf, conversation_id, "codex-image-run-2")
        second_snapshot = _wait_for_terminal(client, second)
        assert second_snapshot["status"] == "completed"
        assert second_snapshot["artifacts"][0]["currentVersion"] == 2
        assert second_snapshot["toolExecutions"][0]["result"]["version"] == 2

        version_one = client.get(
            f"/api/artifacts/{destination_artifact_id}/download?version=1"
        )
        version_two = client.get(
            f"/api/artifacts/{destination_artifact_id}/download?version=2"
        )
        assert version_one.content == _PNG
        assert version_two.content == _PNG + b"second-version"

        with SessionLocal() as db:
            tool_rows = list(
                db.scalars(
                    select(ToolExecution).where(
                        ToolExecution.tool_name == "generate_image"
                    )
                )
            )
            event_rows = list(db.scalars(select(RunEvent)))
            versions = list(
                db.scalars(
                    select(ArtifactVersion).where(
                        ArtifactVersion.artifact_id == destination_artifact_id
                    )
                )
            )
            assert [version.version_number for version in versions] == [1, 2]
            stored_json = json.dumps(
                {
                    "inputs": [row.validated_input_json for row in tool_rows],
                    "results": [row.result_json for row in tool_rows],
                    "events": [row.payload_json for row in event_rows],
                    "metadata": [row.renderer_manifest_json for row in versions],
                },
                ensure_ascii=False,
                default=str,
            )
            assert "DB에 원문으로 저장되면 안 되는 이미지 지시문" not in stored_json
            assert base64.b64encode(_PNG).decode("ascii") not in stored_json
            assert "test-openai-key" not in stored_json

    assert isinstance(CodexResponsesAdapter(), CodexResponsesAdapter)


def _manual_run(
    db: Session,
    user: User,
    project: Project,
    *,
    provider_id: str,
    image: bool,
) -> Run:
    conversation = Conversation(
        organization_id=user.organization_id,
        project_id=project.id,
        owner_user_id=user.id,
        title=f"{provider_id}-{image}",
    )
    db.add(conversation)
    db.flush()
    run = Run(
        organization_id=user.organization_id,
        project_id=project.id,
        conversation_id=conversation.id,
        user_id=user.id,
        status="queued",
        provider_id=provider_id,
        model_key="test-model",
        runtime_model_id="test-model",
        model_display_name="Test",
        snapshot_json={
            "execution": {
                "capabilities": {"image_generation": image},
                "image_backend_model": "gpt-image-2",
            }
        },
    )
    db.add(run)
    db.flush()
    return run


def _settings(tmp_path: Path, database_name: str) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / database_name).as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


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


def _start_codex_run(
    client: TestClient, csrf: str, conversation_id: str, key: str
) -> str:
    response = client.post(
        f"/api/conversations/{conversation_id}/runs",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
        json={
            "message": {
                "text": "설비 이미지를 생성해 주세요.",
                "attachmentIds": [],
                "promptReferences": [],
            },
            "execution": {
                "providerId": "codex",
                "modelKey": "gpt-5.5",
                "effortId": "medium",
            },
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["run"]["runId"]


def _wait_for_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 8
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
