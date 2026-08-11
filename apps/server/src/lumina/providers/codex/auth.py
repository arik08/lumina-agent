from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ..errors import ProviderConfigurationError, ProviderRequestError


_CODEX_JWT_AUTH_CLAIM = "https://api.openai.com/auth"
_CODEX_REFRESH_TOKEN_URL = "https://auth.openai.com/oauth/token"
_CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_REFRESH_WINDOW_SECONDS = 5 * 60
_refresh_lock = asyncio.Lock()


@dataclass(frozen=True)
class CodexAuthCredentials:
    access_token: str
    account_id: str
    refresh_token: str | None
    expires_at: float | None


def codex_oauth_available() -> bool:
    """Return whether local ChatGPT OAuth can serve or refresh a request."""

    try:
        credentials = load_codex_auth()
    except ProviderConfigurationError:
        return False
    return not _token_expired(credentials) or credentials.refresh_token is not None


def load_codex_auth() -> CodexAuthCredentials:
    payload = _read_auth_payload()
    auth_mode = payload.get("auth_mode")
    if auth_mode is not None and auth_mode != "chatgpt":
        raise ProviderConfigurationError(
            "Codex Provider는 ChatGPT OAuth 로그인이 필요합니다. "
            "서버 사용자 계정에서 `codex login`을 실행해 주세요."
        )
    tokens = payload.get("tokens")
    access_token = (
        tokens.get("access_token") if isinstance(tokens, Mapping) else None
    )
    if not isinstance(access_token, str) or not access_token:
        raise ProviderConfigurationError(
            "Codex ChatGPT OAuth access token을 찾을 수 없습니다."
        )
    assert isinstance(tokens, Mapping)

    claims = _jwt_claims(access_token)
    auth = claims.get(_CODEX_JWT_AUTH_CLAIM)
    account_id = auth.get("chatgpt_account_id") if isinstance(auth, Mapping) else None
    if not isinstance(account_id, str) or not account_id:
        raise ProviderConfigurationError(
            "Codex OAuth access token에 ChatGPT 계정 정보가 없습니다."
        )

    refresh_token = tokens.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        refresh_token = None
    expires_at = claims.get("exp")
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        expires_at = None
    return CodexAuthCredentials(
        access_token=access_token,
        account_id=account_id,
        refresh_token=refresh_token,
        expires_at=float(expires_at) if expires_at is not None else None,
    )


async def ready_codex_auth(client: httpx.AsyncClient) -> CodexAuthCredentials:
    credentials = load_codex_auth()
    if not _token_needs_refresh(credentials):
        return credentials
    if credentials.refresh_token is None and not _token_expired(credentials):
        return credentials
    return await refresh_codex_auth(
        client, observed_access_token=credentials.access_token
    )


async def refresh_codex_auth(
    client: httpx.AsyncClient,
    *,
    observed_access_token: str,
    trigger_status_code: int | None = None,
) -> CodexAuthCredentials:
    """Reload shared auth state, then refresh and atomically persist if unchanged."""

    async with _refresh_lock:
        credentials = load_codex_auth()
        if credentials.access_token != observed_access_token:
            return credentials
        if credentials.refresh_token is None:
            raise _login_required_error(status_code=trigger_status_code)

        endpoint = os.environ.get(
            "CODEX_REFRESH_TOKEN_URL_OVERRIDE", _CODEX_REFRESH_TOKEN_URL
        )
        client_id = os.environ.get(
            "CODEX_APP_SERVER_LOGIN_CLIENT_ID", _CODEX_OAUTH_CLIENT_ID
        ).strip() or _CODEX_OAUTH_CLIENT_ID
        try:
            response = await client.post(
                endpoint,
                headers={"Content-Type": "application/json"},
                json={
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": credentials.refresh_token,
                },
            )
        except httpx.HTTPError as exc:
            raise ProviderRequestError(
                "Codex OAuth 토큰 갱신 서버에 연결하지 못했습니다.",
                retryable=True,
                stage="authentication",
            ) from exc

        if not response.is_success:
            concurrent = _credentials_refreshed_by_another_process(credentials)
            if concurrent is not None:
                return concurrent
            if response.status_code in {400, 401, 403}:
                raise _login_required_error(status_code=response.status_code)
            raise ProviderRequestError(
                "Codex OAuth 토큰을 갱신하지 못했습니다.",
                retryable=response.status_code == 429 or response.status_code >= 500,
                stage="authentication",
                status_code=response.status_code,
            )
        try:
            refreshed = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderRequestError(
                "Codex OAuth 토큰 갱신 응답 형식이 올바르지 않습니다.",
                retryable=True,
                stage="authentication",
                status_code=response.status_code,
            ) from exc
        if not isinstance(refreshed, Mapping):
            raise ProviderRequestError(
                "Codex OAuth 토큰 갱신 응답 형식이 올바르지 않습니다.",
                retryable=True,
                stage="authentication",
                status_code=response.status_code,
            )
        return _persist_refreshed_auth(credentials, refreshed)


def _codex_auth_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "auth.json"


def _read_auth_payload() -> dict[str, Any]:
    try:
        payload = json.loads(_codex_auth_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderConfigurationError(
            "Codex ChatGPT OAuth 인증 파일을 읽을 수 없습니다. "
            "서버 사용자 계정에서 `codex login`을 실행해 주세요."
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderConfigurationError(
            "Codex ChatGPT OAuth 인증 파일 형식이 올바르지 않습니다."
        )
    return payload


def _jwt_claims(token: str) -> Mapping[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ProviderConfigurationError(
            "Codex OAuth access token 형식이 올바르지 않습니다."
        )
    try:
        encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderConfigurationError(
            "Codex OAuth access token의 계정 정보를 읽을 수 없습니다."
        ) from exc
    if not isinstance(payload, Mapping):
        raise ProviderConfigurationError(
            "Codex OAuth access token의 계정 정보가 올바르지 않습니다."
        )
    return payload


def _token_expired(credentials: CodexAuthCredentials) -> bool:
    return credentials.expires_at is not None and credentials.expires_at <= time.time()


def _token_needs_refresh(credentials: CodexAuthCredentials) -> bool:
    return (
        credentials.expires_at is not None
        and credentials.expires_at <= time.time() + _REFRESH_WINDOW_SECONDS
    )


def _credentials_refreshed_by_another_process(
    previous: CodexAuthCredentials,
) -> CodexAuthCredentials | None:
    try:
        current = load_codex_auth()
    except ProviderConfigurationError:
        return None
    if current.access_token == previous.access_token:
        return None
    if current.account_id != previous.account_id:
        raise ProviderRequestError(
            "Codex 로그인 계정이 요청 도중 변경되었습니다. 요청을 다시 실행해 주세요.",
            retryable=True,
            stage="authentication",
        )
    return current


def _persist_refreshed_auth(
    previous: CodexAuthCredentials, refreshed: Mapping[str, Any]
) -> CodexAuthCredentials:
    access_token = refreshed.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ProviderRequestError(
            "Codex OAuth 토큰 갱신 응답에 access token이 없습니다.",
            retryable=True,
            stage="authentication",
        )

    payload = _read_auth_payload()
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        raise _login_required_error()
    current_access_token = tokens.get("access_token")
    if current_access_token != previous.access_token:
        current = _credentials_refreshed_by_another_process(previous)
        assert current is not None
        return current

    candidate = dict(tokens)
    candidate["access_token"] = access_token
    for field in ("id_token", "refresh_token"):
        value = refreshed.get(field)
        if isinstance(value, str) and value:
            candidate[field] = value
    payload["tokens"] = candidate
    payload["last_refresh"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    updated = _credentials_from_payload(payload)
    if updated.account_id != previous.account_id:
        raise ProviderRequestError(
            "Codex OAuth 갱신 결과의 계정이 기존 로그인과 다릅니다. `codex login`을 다시 실행해 주세요.",
            retryable=False,
            stage="authentication",
        )
    _write_auth_payload(payload)
    return updated


def _credentials_from_payload(payload: Mapping[str, Any]) -> CodexAuthCredentials:
    tokens = payload.get("tokens")
    access_token = tokens.get("access_token") if isinstance(tokens, Mapping) else None
    if not isinstance(access_token, str):
        raise _login_required_error()
    assert isinstance(tokens, Mapping)
    claims = _jwt_claims(access_token)
    auth = claims.get(_CODEX_JWT_AUTH_CLAIM)
    account_id = auth.get("chatgpt_account_id") if isinstance(auth, Mapping) else None
    if not isinstance(account_id, str) or not account_id:
        raise _login_required_error()
    refresh_token = tokens.get("refresh_token")
    expires_at = claims.get("exp")
    return CodexAuthCredentials(
        access_token=access_token,
        account_id=account_id,
        refresh_token=(
            refresh_token if isinstance(refresh_token, str) and refresh_token else None
        ),
        expires_at=(
            float(expires_at)
            if isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool)
            else None
        ),
    )


def _write_auth_payload(payload: Mapping[str, Any]) -> None:
    path = _codex_auth_path()
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        try:
            temp_path.chmod(path.stat().st_mode)
        except OSError:
            pass
        os.replace(temp_path, path)
    except OSError as exc:
        raise ProviderRequestError(
            "갱신한 Codex OAuth 인증 정보를 저장하지 못했습니다.",
            retryable=False,
            stage="authentication",
        ) from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _login_required_error(*, status_code: int | None = None) -> ProviderRequestError:
    return ProviderRequestError(
        "Codex ChatGPT OAuth 인증을 갱신할 수 없습니다. `codex login`을 다시 실행해 주세요.",
        retryable=False,
        stage="authentication",
        status_code=status_code,
    )


__all__ = [
    "CodexAuthCredentials",
    "codex_oauth_available",
    "load_codex_auth",
    "ready_codex_auth",
    "refresh_codex_auth",
]
