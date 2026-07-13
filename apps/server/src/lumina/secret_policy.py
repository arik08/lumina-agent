from __future__ import annotations

from typing import Any

from .api.errors import ApiProblem


SECRET_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
)


def reject_secret_key_names(value: Any, *, path: str = "settings") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if any(part in key.casefold() for part in SECRET_KEY_PARTS):
                raise ApiProblem(
                    422,
                    "secret_setting_forbidden",
                    f"{path}.{key}에는 비밀값을 저장할 수 없습니다.",
                )
            reject_secret_key_names(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_secret_key_names(item, path=f"{path}[{index}]")
