from __future__ import annotations

import hashlib
import secrets
import unicodedata
from datetime import UTC, date, datetime, time, timedelta
from hmac import compare_digest
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


SEOUL = ZoneInfo("Asia/Seoul")
_PASSWORD_HASHER = PasswordHasher()


def normalize_login_parts(login_name: str, login_domain: str) -> tuple[str, str, str]:
    name = unicodedata.normalize("NFKC", login_name).strip().casefold()
    domain_input = unicodedata.normalize("NFKC", login_domain).strip().rstrip(".")
    if not name or not domain_input or "@" in name or "@" in domain_input:
        raise ValueError(
            "login name and domain must be non-empty and must not contain '@'"
        )
    try:
        domain = domain_input.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise ValueError("invalid login domain") from exc
    if len(name) > 120 or len(domain) > 255:
        raise ValueError("login identifier is too long")
    return name, domain, f"{name}@{domain}"


def normalize_login_id(login_id: str) -> tuple[str, str, str]:
    value = unicodedata.normalize("NFKC", login_id).strip()
    if value.count("@") != 1:
        raise ValueError("login_id must contain exactly one '@'")
    return normalize_login_parts(*value.split("@", 1))


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _PASSWORD_HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_secret_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, expected_hash: str) -> bool:
    return compare_digest(hash_token(token), expected_hash)


def next_seoul_midnight(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current_in_seoul = current.astimezone(SEOUL)
    tomorrow: date = current_in_seoul.date() + timedelta(days=1)
    midnight_in_seoul = datetime.combine(tomorrow, time.min, tzinfo=SEOUL)
    return midnight_in_seoul.astimezone(UTC)
