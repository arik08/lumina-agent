from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from lumina.attachments import sniff_mime
from lumina.http_client import TrustManager, TrustProfile, create_http_client
from lumina.image_formats import IMAGE_MIME_BY_FORMAT

from ..errors import ProviderConfigurationError, ProviderRequestError
from ..openai import DEFAULT_OPENAI_BASE_URL
from ..openai.adapter import _validated_base_url


@dataclass(frozen=True, slots=True)
class ImageGenerationRequest:
    model: str
    image_model: str
    prompt: str
    size: str
    quality: str
    output_format: str
    background: str


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    content: bytes
    mime_type: str
    output_format: str
    actual_backend: str
    actual_model: str
    actual_model_reported: bool
    response_model: str
    revised_prompt_hash: str | None


class CodexImageGenerator:
    """Call the Responses hosted image tool and return validated image bytes."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        client: httpx.AsyncClient | None = None,
        trust_profile: TrustProfile | None = None,
        max_output_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        secret = api_key.strip()
        if not secret:
            raise ProviderConfigurationError(
                "Codex 이미지 생성을 사용하려면 OPENAI_API_KEY가 필요합니다."
            )
        if max_output_bytes < 1024:
            raise ValueError("max_output_bytes must be at least 1024")
        self.base_url = _validated_base_url(base_url)
        self.max_output_bytes = max_output_bytes
        self._authorization = f"Bearer {secret}"
        self._client = client
        self._trust_profile = trust_profile

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        client = self._client
        owns_client = client is None
        if client is None:
            profile = self._trust_profile or TrustManager().initialize()
            client = create_http_client(profile)

        try:
            response = await client.post(
                f"{self.base_url}/responses",
                headers={
                    "Authorization": self._authorization,
                    "Accept": "application/json",
                },
                json=_payload(request),
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ProviderRequestError(
                f"Codex 이미지 생성 요청이 실패했습니다 (HTTP {status}).",
                retryable=status in {408, 409, 425, 429} or status >= 500,
                stage=_stage_for_status(status),
                status_code=status,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderRequestError(
                "Codex 이미지 생성 네트워크 요청이 실패했습니다.",
                retryable=True,
                stage="network",
            ) from exc
        except ValueError as exc:
            raise ProviderRequestError(
                "Codex 이미지 생성 응답이 올바른 JSON이 아닙니다.",
                retryable=False,
                stage="response",
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        return _generated_image(body, max_output_bytes=self.max_output_bytes)


def _payload(request: ImageGenerationRequest) -> dict[str, Any]:
    image_tool = {
        "type": "image_generation",
        "model": request.image_model,
        "action": "generate",
        "size": request.size,
        "quality": request.quality,
        "output_format": request.output_format,
        "background": request.background,
    }
    return {
        "model": request.model,
        "input": request.prompt,
        "tools": [image_tool],
        "tool_choice": {"type": "image_generation"},
        "store": False,
    }


def _generated_image(body: object, *, max_output_bytes: int) -> GeneratedImage:
    if not isinstance(body, Mapping):
        raise _invalid_response("응답 본문이 객체가 아닙니다.")
    output = body.get("output")
    if not isinstance(output, list):
        raise _invalid_response("image_generation_call 결과가 없습니다.")
    calls = [
        item
        for item in output
        if isinstance(item, Mapping) and item.get("type") == "image_generation_call"
    ]
    if len(calls) != 1:
        raise _invalid_response("이미지 생성 결과는 정확히 한 장이어야 합니다.")
    call = calls[0]
    encoded = call.get("result")
    if not isinstance(encoded, str) or not encoded:
        raise _invalid_response("이미지 생성 결과가 비어 있습니다.")

    # Reject oversized payloads before allocating decoded bytes.
    encoded_limit = ((max_output_bytes + 2) // 3) * 4 + 4
    if len(encoded) > encoded_limit:
        raise ProviderRequestError(
            "생성된 이미지가 허용 크기를 초과했습니다.",
            retryable=False,
            stage="validation",
        )
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _invalid_response(
            "이미지 결과의 base64 인코딩이 올바르지 않습니다."
        ) from exc
    if not content or len(content) > max_output_bytes:
        raise ProviderRequestError(
            "생성된 이미지가 비어 있거나 허용 크기를 초과했습니다.",
            retryable=False,
            stage="validation",
        )

    mime_type = sniff_mime(content, "")
    output_format = next(
        (
            name
            for name, expected_mime in IMAGE_MIME_BY_FORMAT.items()
            if expected_mime == mime_type
        ),
        None,
    )
    if output_format is None:
        raise ProviderRequestError(
            "생성 결과가 지원하는 PNG, JPEG 또는 WebP 이미지가 아닙니다.",
            retryable=False,
            stage="validation",
        )

    response_model = body.get("model")
    reported_model = call.get("model")
    revised_prompt = call.get("revised_prompt")
    return GeneratedImage(
        content=content,
        mime_type=mime_type,
        output_format=output_format,
        actual_backend="openai_responses.image_generation",
        actual_model=(
            str(reported_model)
            if isinstance(reported_model, str) and reported_model
            else "not_reported"
        ),
        actual_model_reported=bool(isinstance(reported_model, str) and reported_model),
        response_model=(
            str(response_model)
            if isinstance(response_model, str) and response_model
            else "not_reported"
        ),
        revised_prompt_hash=(
            _sha256_text(revised_prompt)
            if isinstance(revised_prompt, str) and revised_prompt
            else None
        ),
    )


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _invalid_response(message: str) -> ProviderRequestError:
    return ProviderRequestError(message, retryable=False, stage="response")


def _stage_for_status(status: int) -> str:
    if status in {401, 403}:
        return "authentication"
    if status == 404:
        return "endpoint"
    if status == 429:
        return "rate_limit"
    return "request"


__all__ = [
    "CodexImageGenerator",
    "GeneratedImage",
    "ImageGenerationRequest",
]
