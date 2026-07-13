from __future__ import annotations


COBALT_HEX = "315FBD"
INK_HEX = "202631"
MUTED_HEX = "6B7280"
LIGHT_BLUE_HEX = "EAF0FB"


def hex_rgb(value: str) -> tuple[int, int, int]:
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )
