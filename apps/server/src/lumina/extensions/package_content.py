from __future__ import annotations

import base64
import binascii


_BINARY_PREFIX = "lumina-package-base64-v1:"


def encode_binary_package_content(content: bytes) -> str:
    return _BINARY_PREFIX + base64.b64encode(content).decode("ascii")


def decode_package_content(content: str) -> tuple[bytes, str]:
    if not content.startswith(_BINARY_PREFIX):
        return content.encode("utf-8"), "utf-8"
    encoded = content.removeprefix(_BINARY_PREFIX)
    try:
        return base64.b64decode(encoded, validate=True), "base64"
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Skill binary resource encoding is invalid.") from exc


def package_content_for_model(content: str) -> tuple[str, str]:
    if content.startswith(_BINARY_PREFIX):
        decode_package_content(content)
        return content.removeprefix(_BINARY_PREFIX), "base64"
    return content, "utf-8"


__all__ = [
    "decode_package_content",
    "encode_binary_package_content",
    "package_content_for_model",
]
