from __future__ import annotations


class ProviderError(RuntimeError):
    """Base error exposed by provider adapters."""


class ProviderConfigurationError(ProviderError):
    """Raised before I/O when a provider is not safely configured."""


class ProviderRequestError(ProviderError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        stage: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.stage = stage
        self.status_code = status_code
