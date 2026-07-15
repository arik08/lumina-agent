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
        retry_after_seconds: float | None = None,
        context_window_tokens: int | None = None,
        attempt_count: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.stage = stage
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.context_window_tokens = context_window_tokens
        self.attempt_count = attempt_count
