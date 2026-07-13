from __future__ import annotations

import ipaddress
import re


SECRET_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")
APPROVABLE_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "fc00::/7",
        "::1/128",
    )
)
