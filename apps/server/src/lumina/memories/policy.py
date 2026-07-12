from __future__ import annotations

import re

from ..api.errors import ApiProblem


_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN[^\n]*(?:PRIVATE KEY|CERTIFICATE)-----", re.IGNORECASE),
    re.compile(r"\b\d{6}-\d{7}\b"),
    re.compile(
        r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"secret|authorization|bearer)(?:\s*(?:[:=]|\bis\b)\s*|\s+)\S{4,}"
    ),
    re.compile(
        r"(?i)(?:비밀번호|패스워드|토큰|인증번호|일회용\s*번호|otp|사번|"
        r"employee\s*id|staff\s*id)(?:은|는|이|가)?\s*[:=]?\s*"
        r"[A-Za-z0-9_./+\-=]{3,}"
    ),
)
_PROHIBITED_SENSITIVE_TOPICS = re.compile(
    r"(?i)(?:건강|질병|진단|병력|의료|처방|복용약|임신|장애|health|medical|"
    r"diagnos|prescription|pregnan|정치|정당|투표|선거|politic|party\s+"
    r"affiliation|voting|노조|노동조합|labor\s+union|union\s+member)"
)


def normalize_fact(value: str) -> str:
    normalized = " ".join(value.split()).casefold()
    if not normalized:
        raise ApiProblem(422, "memory_fact_required", "Memory 내용을 입력해 주세요.")
    return normalized


def contains_sensitive_memory(value: str) -> bool:
    return _PROHIBITED_SENSITIVE_TOPICS.search(value) is not None or any(
        pattern.search(value) for pattern in _SECRET_PATTERNS
    )


def validate_memory_text(*values: str) -> None:
    if any(contains_sensitive_memory(value) for value in values):
        raise ApiProblem(
            422,
            "sensitive_memory_forbidden",
            "비밀번호, 토큰 또는 민감한 개인정보는 Memory에 저장할 수 없습니다.",
        )
