from __future__ import annotations

import base64
import json
import ssl
from pathlib import Path

import certifi
import pytest

from lumina.http_client import TrustConfigurationError, TrustManager
from lumina.providers import (
    MockProvider,
    MockToolCall,
    ProviderConfigurationError,
    ProviderMessage,
    ProviderRequest,
    initial_model_catalog,
)
from lumina.providers.openai_compatible import OpenAICompatibleAdapter
from lumina.providers.pgpt import (
    DEFAULT_PGPT_BASE_URL,
    PgptCredentials,
    PgptProfile,
    build_pgpt_auth_token,
    redact_pgpt_text,
)


def test_initial_model_catalog_matches_detailed_design_section_12_3() -> None:
    actual = [
        (
            item.provider_id,
            item.display_name,
            item.runtime_model_id,
            item.is_default,
        )
        for item in initial_model_catalog()
    ]
    assert actual == [
        ("pgpt", "GPT-5.4", "gpt-5.4", True),
        ("pgpt", "GPT-5.4-mini", "gpt-5.4-mini", False),
        ("codex", "GPT-5.5", "gpt-5.5", True),
        ("codex", "GPT-5.4", "gpt-5.4", False),
        ("google", "Gemini-3.1-Pro", "gemini-3.1-pro", True),
        ("google", "Gemini-3.5-flash", "gemini-3.5-flash", False),
        ("openai", "GPT-5.6-Sol", "gpt-5.6-sol", True),
        ("openai", "GPT-5.6-Terra", "gpt-5.6-terra", False),
        ("openai", "GPT-5.6-Luna", "gpt-5.6-luna", False),
        ("anthropic", "Claude Opus 4.8", "claude-opus-4-8", False),
        ("anthropic", "Claude Sonnet 5", "claude-sonnet-5", True),
        ("anthropic", "Claude Haiku 4.5", "claude-haiku-4-5", False),
    ]

    provider_ids = {item.provider_id for item in initial_model_catalog()}
    assert "openai_compatible" not in provider_ids
    for provider_id in provider_ids:
        items = initial_model_catalog(provider_id)
        assert sum(item.is_default for item in items) == 1
        assert [item.sort_order for item in items] == sorted(
            item.sort_order for item in items
        )


@pytest.mark.asyncio
async def test_mock_provider_has_stable_stream_and_tool_boundaries() -> None:
    provider = MockProvider(
        text_chunks=("자료를 ", "확인합니다."),
        tool_call=MockToolCall("read_file", {"path": "report.md"}),
    )
    request = ProviderRequest(
        model="mock-1",
        messages=(ProviderMessage(role="user", content="보고서를 읽어주세요."),),
    )

    first = [event async for event in provider.stream(request)]
    second = [event async for event in provider.stream(request)]

    assert first == second
    assert [event.type for event in first] == [
        "text_delta",
        "text_delta",
        "tool_call_started",
        "tool_call_delta",
        "tool_call_completed",
        "usage",
        "completed",
    ]
    assert first[2].tool_call_id == first[3].tool_call_id == first[4].tool_call_id
    assert json.loads(first[4].arguments_json or "") == {"path": "report.md"}
    assert first[-1].stop_reason == "tool_calls"


def test_pgpt_auth_envelope_and_profile_preserve_contract() -> None:
    token = build_pgpt_auth_token("가짜-api-key", "E12345", "POSCO")
    decoded = json.loads(base64.b64decode(token).decode("utf-8"))
    assert decoded == {
        "apiKey": "가짜-api-key",
        "companyCode": "POSCO",
        "systemCode": "E12345",
    }

    assert PgptProfile.from_env({}).base_url == DEFAULT_PGPT_BASE_URL
    profile = PgptProfile.from_env(
        {"PGPT_BASE_URL": "https://example.test/company/gpt/v1/"},
        deployment_mapping={"gpt-5.4": "deployment-54"},
    )
    assert (
        profile.chat_completions_url
        == "https://example.test/company/gpt/v1/chat/completions"
    )
    assert profile.resolve_runtime_model("gpt-5.4") == "deployment-54"


def test_pgpt_missing_credentials_fail_before_external_io() -> None:
    with pytest.raises(ProviderConfigurationError, match="PGPT_EMPLOYEE_NO"):
        PgptCredentials.from_env(
            {"PGPT_API_KEY": "key", "PGPT_COMPANY_CODE": "company"}
        )

    with pytest.raises(ProviderConfigurationError, match="Authorization"):
        OpenAICompatibleAdapter(
            provider_id="external",
            base_url="https://example.test/v1",
        )


def test_pgpt_redaction_hides_envelope_and_raw_fields() -> None:
    credentials = PgptCredentials("secret-key", "employee-123", "company-456")
    token = build_pgpt_auth_token(
        credentials.api_key,
        credentials.employee_no,
        credentials.company_code,
    )
    raw = (
        f"Authorization: Bearer {token} "
        f'{{"apiKey":"{credentials.api_key}","companyCode":"{credentials.company_code}",'
        f'"systemCode":"{credentials.employee_no}"}}'
    )
    redacted = redact_pgpt_text(raw, credentials)
    assert "secret-key" not in redacted
    assert "employee-123" not in redacted
    assert "company-456" not in redacted
    assert token not in redacted
    assert "[REDACTED]" in redacted


def test_trust_manager_combines_ca_and_exports_subprocess_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_TLS_COMPAT_MODE", raising=False)
    (tmp_path / ".env").write_text(
        "LUMINA_TLS_COMPAT_MODE=true\n",
        encoding="utf-8",
    )
    profile = TrustManager(
        repo_root=tmp_path,
        ca_cert=Path(certifi.where()),
        runtime_dir=tmp_path / "runtime",
    ).initialize(require_company_ca=True)

    assert isinstance(profile.ssl_context, ssl.SSLContext)
    assert profile.bundle_path is not None and profile.bundle_path.is_file()
    assert profile.company_ca_path == Path(certifi.where()).resolve()
    assert profile.tls_compat_mode is True
    assert profile.ssl_context.security_level == 1
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        assert profile.ssl_context.verify_flags & ssl.VERIFY_X509_STRICT == 0
    environment = profile.subprocess_environment()
    assert environment["SSL_CERT_FILE"] == str(profile.bundle_path)
    assert environment["NODE_EXTRA_CA_CERTS"] == str(profile.company_ca_path)
    assert environment["NODE_OPTIONS"] == "--tls-cipher-list=DEFAULT@SECLEVEL=1"


def test_trust_manager_never_silently_ignores_bad_config(tmp_path: Path) -> None:
    missing = tmp_path / "missing-company-ca.pem"
    with pytest.raises(TrustConfigurationError, match="does not exist"):
        TrustManager(repo_root=tmp_path, ca_cert=missing, env={}).initialize()

    invalid = tmp_path / "invalid-bundle.pem"
    invalid.write_text("not a certificate", encoding="utf-8")
    with pytest.raises(TrustConfigurationError, match="validation failed"):
        TrustManager(repo_root=tmp_path, ca_bundle=invalid, env={}).initialize()
