from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...auth import (
    AccountUnavailableError,
    AuthenticationError,
    authenticate_user,
    create_user,
    issue_server_session,
    revoke_server_session,
    verify_csrf_token,
)
from ...config import Settings, get_settings
from ...db import get_db
from ...models import User
from ...notifications import create_registration_approval_notification
from ..dependencies import AuthContext, get_auth_context, require_csrf
from ..errors import ApiProblem
from ..schemas import LoginRequest, RegistrationRequest


router = APIRouter(prefix="/auth", tags=["auth"])


def _user_payload(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "organizationId": user.organization_id,
        "loginName": user.login_name,
        "loginDomain": user.login_domain,
        "email": user.login_id,
        "loginId": user.login_id,
        "displayName": user.display_name,
        "affiliation": user.affiliation,
        "role": user.role,
        "status": user.status,
    }


def _session_payload(user: User, expires_at, csrf_token: str) -> dict[str, object]:
    return {
        "user": _user_payload(user),
        "expiresAt": expires_at,
        "csrfToken": csrf_token,
    }


@router.post("/register", status_code=201)
def register(
    payload: RegistrationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    email = payload.email.strip().casefold()
    if email.count("@") != 1:
        raise ApiProblem(422, "invalid_email", "올바른 이메일 주소를 입력해 주세요.")
    login_name, login_domain = email.split("@", 1)
    bootstrap_admin = db.scalar(
        select(User).where(
            User.login_id == "admin@posco.com",
            User.role == "admin",
            User.status == "active",
        )
    )
    if bootstrap_admin is None:
        raise ApiProblem(503, "registration_unavailable", "가입 신청을 처리할 관리자가 없습니다.")
    try:
        applicant = create_user(
            db,
            login_name=login_name,
            login_domain=login_domain,
            password=payload.password,
            organization_id=bootstrap_admin.organization_id,
            display_name=payload.display_name.strip(),
            affiliation=payload.affiliation.strip(),
            role=payload.role,
            status="invited",
        )
    except ValueError as exc:
        code = "login_id_exists" if "already exists" in str(exc) else "invalid_user"
        raise ApiProblem(
            409 if code == "login_id_exists" else 422,
            code,
            "이미 가입되었거나 신청 중인 이메일입니다." if code == "login_id_exists" else "가입 신청 정보를 확인해 주세요.",
        ) from exc
    create_registration_approval_notification(
        db, admin=bootstrap_admin, applicant=applicant
    )
    record_audit(
        db,
        action="registration_requested",
        target_type="user",
        target_id=applicant.id,
        result="success",
        request_id=getattr(request.state, "request_id", None),
        metadata={"requested_role": applicant.role},
    )
    db.commit()
    return {
        "loginId": applicant.login_id,
        "status": applicant.status,
        "message": "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    try:
        user = authenticate_user(
            db,
            login_name=payload.login_name,
            login_domain=payload.login_domain,
            password=payload.password,
            settings=settings,
        )
    except (AuthenticationError, AccountUnavailableError) as exc:
        db.commit()
        raise ApiProblem(
            401,
            "invalid_credentials",
            "아이디 또는 비밀번호를 확인해 주세요.",
        ) from exc
    issued = issue_server_session(db, user)
    record_audit(
        db,
        action="auth_session_issued",
        target_type="auth_session",
        target_id=issued.auth_session.id,
        result="success",
        actor=user,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    max_age = max(
        0,
        int(
            (
                issued.auth_session.expires_at - issued.auth_session.created_at
            ).total_seconds()
        ),
    )
    response.set_cookie(
        settings.auth_cookie_name,
        issued.session_token,
        max_age=max_age,
        expires=issued.auth_session.expires_at,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        issued.csrf_token,
        max_age=max_age,
        expires=issued.auth_session.expires_at,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["X-CSRF-Token"] = issued.csrf_token
    return _session_payload(user, issued.auth_session.expires_at, issued.csrf_token)


@router.get("/session")
def auth_session(
    request: Request,
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    csrf_token = request.cookies.get(settings.csrf_cookie_name, "")
    if not csrf_token or not verify_csrf_token(context.auth_session, csrf_token):
        raise ApiProblem(401, "session_expired", "로그인 세션을 다시 시작해 주세요.")
    # The readable CSRF cookie is returned to recover clients after a page refresh.
    # It is still verified against the server-side hash on every mutation.
    # FastAPI injects Request separately to avoid exposing the HttpOnly session token.
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-CSRF-Token"] = csrf_token
    return _session_payload(context.user, context.auth_session.expires_at, csrf_token)


@router.post("/logout", status_code=204)
def logout(
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    revoke_server_session(db, context.session_token)
    db.commit()
    result = Response(status_code=204)
    result.delete_cookie(settings.auth_cookie_name, path="/")
    result.delete_cookie(settings.csrf_cookie_name, path="/")
    return result
