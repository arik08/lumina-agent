"""
Common types shared across schema models.

These types are used by both layout_plan.py and generation_result.py
to avoid circular imports and maintain DRY principles.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StyledRun(BaseModel):
    """Text run with optional inline styling.

    Used for rich text formatting within headlines and body content.
    Style dict may contain: color (hex), bold, italic, type (e.g., "question").
    """

    model_config = ConfigDict(extra="allow")  # Allow additional style properties

    text: str
    style: dict | None = None


class BodyItem(BaseModel):
    """Body content item with optional styled runs.

    Represents a single paragraph/bullet in body content.
    Can contain styled runs for inline formatting.
    """

    model_config = ConfigDict(extra="allow")

    text: str
    runs: list[StyledRun] | None = None
    paragraph: dict | None = None  # Paragraph-level styling
