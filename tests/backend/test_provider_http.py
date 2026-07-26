from __future__ import annotations

import pytest

from lumina.providers import ProviderConfigurationError
from lumina.providers.http import validate_http_base_url
from lumina.providers.openai import OpenAIResponsesAdapter
from lumina.providers.openai_compatible import OpenAICompatibleAdapter
from lumina.providers.pgpt import PgptProfile


def test_provider_base_urls_share_normalization() -> None:
    assert (
        validate_http_base_url("  https://provider.test/v1/  ", "Provider")
        == "https://provider.test/v1"
    )
    assert OpenAIResponsesAdapter(
        api_key="secret", base_url="https://openai.test/v1/"
    ).base_url == "https://openai.test/v1"
    assert OpenAICompatibleAdapter(
        provider_id="compatible",
        base_url="https://compatible.test/v1/",
        headers={"Authorization": "Bearer secret"},
    ).base_url == "https://compatible.test/v1"
    assert PgptProfile(base_url="https://pgpt.test/v1/").base_url == (
        "https://pgpt.test/v1"
    )


@pytest.mark.parametrize(
    "value",
    [
        "provider.test/v1",
        "ftp://provider.test/v1",
        "https://user:secret@provider.test/v1",
        "https://provider.test/v1?key=value",
        "https://provider.test/v1#fragment",
        "https://provider.test:bad/v1",
        "https://provider.test:70000/v1",
        "https://provider.test:/v1",
        "https://[::1",
        "https://provider.test/line\nbreak",
        "https://provider.test\\alternate/v1",
    ],
)
def test_provider_base_url_rejects_ambiguous_or_invalid_values(value: str) -> None:
    with pytest.raises(ProviderConfigurationError):
        validate_http_base_url(value, "Provider")
