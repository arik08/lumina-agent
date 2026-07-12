from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from ..auth import resolve_server_session, verify_csrf_token
from ..config import Settings, get_settings
from ..db import get_db
from ..models import AuthSession, User
from .errors import ApiProblem


@dataclass(slots=True)
class AuthContext:
    user: User
    auth_session: AuthSession
    session_token: str


def get_auth_context(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise ApiProblem(401, "authentication_required", "로그인이 필요합니다.")
    resolved = resolve_server_session(db, token)
    if resolved is None:
        raise ApiProblem(401, "session_expired", "로그인 세션이 만료되었습니다.")
    return AuthContext(resolved.user, resolved.auth_session, token)


def get_current_user(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user


def require_csrf(
    request: Request,
    context: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AuthContext:
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    if (
        not csrf_header
        or not csrf_cookie
        or not secrets.compare_digest(csrf_header, csrf_cookie)
        or not verify_csrf_token(context.auth_session, csrf_header)
    ):
        raise ApiProblem(
            403, "csrf_failed", "보안 확인에 실패했습니다. 다시 로그인해 주세요."
        )
    return context
