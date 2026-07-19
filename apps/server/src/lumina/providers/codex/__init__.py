from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from ..constants import CODEX_PROVIDER_ID
from ..errors import ProviderConfigurationError
from ..types import ProviderCapabilities, ProviderEvent, ProviderRequest

if TYPE_CHECKING:
    from .adapter import PROVIDER_ID, CodexResponsesAdapter, codex_oauth_available
else:
    try:
        from .adapter import PROVIDER_ID, CodexResponsesAdapter, codex_oauth_available
    except ModuleNotFoundError as exc:
        if exc.name != "openai_codex":
            raise

        PROVIDER_ID = CODEX_PROVIDER_ID

        def codex_oauth_available() -> bool:
            return False

        class CodexResponsesAdapter:
            """Adapter used when optional Codex support was not installed."""

            provider_id = PROVIDER_ID
            capabilities = ProviderCapabilities(
                tools=True,
                structured_output=True,
                reasoning_effort=True,
            )

            async def close(self) -> None:
                return None

            async def warmup(self) -> None:
                raise self._unavailable()

            async def stream(
                self, _request: ProviderRequest
            ) -> AsyncIterator[ProviderEvent]:
                raise self._unavailable()
                yield  # pragma: no cover

            @staticmethod
            def _unavailable() -> ProviderConfigurationError:
                return ProviderConfigurationError(
                    "Codex Provider support is not installed. Run installer.bat "
                    "-InstallCodex to add it."
                )

from .image_generation import (
    CodexImageGenerator,
    GeneratedImage,
    ImageGenerationRequest,
)

__all__ = [
    "PROVIDER_ID",
    "CodexImageGenerator",
    "CodexResponsesAdapter",
    "codex_oauth_available",
    "GeneratedImage",
    "ImageGenerationRequest",
]
