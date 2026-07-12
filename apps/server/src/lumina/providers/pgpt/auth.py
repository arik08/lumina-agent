from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

from ..errors import ProviderConfigurationError

_MAX_API_KEY_LENGTH = 4096
_MAX_IDENTIFIER_LENGTH = 256


@dataclass(frozen=True, slots=True)
class PgptCredentials:
    api_key: str
    employee_no: str
    company_code: str

    def __post_init__(self) -> None:
        values = {
            "PGPT_API_KEY": self.api_key.strip(),
            "PGPT_EMPLOYEE_NO": self.employee_no.strip(),
            "PGPT_COMPANY_CODE": self.company_code.strip(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ProviderConfigurationError(
                f"P-GPT credentials are incomplete; missing {', '.join(missing)}."
            )
        if len(values["PGPT_API_KEY"]) > _MAX_API_KEY_LENGTH:
            raise ProviderConfigurationError(
                "PGPT_API_KEY exceeds the supported length."
            )
        for name in ("PGPT_EMPLOYEE_NO", "PGPT_COMPANY_CODE"):
            if len(values[name]) > _MAX_IDENTIFIER_LENGTH:
                raise ProviderConfigurationError(
                    f"{name} exceeds the supported length."
                )
        object.__setattr__(self, "api_key", values["PGPT_API_KEY"])
        object.__setattr__(self, "employee_no", values["PGPT_EMPLOYEE_NO"])
        object.__setattr__(self, "company_code", values["PGPT_COMPANY_CODE"])

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "PgptCredentials":
        values = os.environ if env is None else env
        return cls(
            api_key=values.get("PGPT_API_KEY", ""),
            employee_no=values.get("PGPT_EMPLOYEE_NO", ""),
            company_code=values.get("PGPT_COMPANY_CODE", ""),
        )


def build_pgpt_auth_token(
    api_key: str,
    employee_no: str,
    company_code: str,
) -> str:
    credentials = PgptCredentials(api_key, employee_no, company_code)
    payload = {
        "apiKey": credentials.api_key,
        "companyCode": credentials.company_code,
        "systemCode": credentials.employee_no,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def build_pgpt_authorization_header(credentials: PgptCredentials) -> str:
    token = build_pgpt_auth_token(
        credentials.api_key,
        credentials.employee_no,
        credentials.company_code,
    )
    return f"Bearer {token}"
