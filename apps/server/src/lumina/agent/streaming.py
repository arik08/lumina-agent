"""Stateful text-stream filters used by the local Run executor."""

from __future__ import annotations


_MAX_CONTINUATION_OVERLAP_CHARS = 4_000
_MEMORY_ENVELOPE_OPEN = "<lumina_memory>"
_MEMORY_ENVELOPE_CLOSE = "</lumina_memory>"


class _InlineMemoryStream:
    """Hide and collect a model-authored Memory envelope across stream chunks."""

    def __init__(self) -> None:
        self._pending = ""
        self._payload_parts: list[str] = []
        self._capturing = False
        self._closed = False

    @property
    def payload(self) -> str | None:
        if not self._closed:
            return None
        return "".join(self._payload_parts).strip()

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        if self._closed:
            return chunk
        self._pending += chunk
        visible: list[str] = []
        while self._pending:
            if self._capturing:
                close_at = self._pending.find(_MEMORY_ENVELOPE_CLOSE)
                if close_at < 0:
                    retained = _matching_prefix_suffix(
                        self._pending, _MEMORY_ENVELOPE_CLOSE
                    )
                    if retained:
                        self._payload_parts.append(self._pending[:-retained])
                        self._pending = self._pending[-retained:]
                    else:
                        self._payload_parts.append(self._pending)
                        self._pending = ""
                    break
                self._payload_parts.append(self._pending[:close_at])
                self._pending = self._pending[close_at + len(_MEMORY_ENVELOPE_CLOSE) :]
                self._capturing = False
                self._closed = True
                visible.append(self._pending)
                self._pending = ""
                break

            open_at = self._pending.find(_MEMORY_ENVELOPE_OPEN)
            if open_at >= 0:
                visible.append(self._pending[:open_at])
                self._pending = self._pending[open_at + len(_MEMORY_ENVELOPE_OPEN) :]
                self._capturing = True
                continue

            retained = _matching_prefix_suffix(self._pending, _MEMORY_ENVELOPE_OPEN)
            if retained:
                visible.append(self._pending[:-retained])
                self._pending = self._pending[-retained:]
            else:
                visible.append(self._pending)
                self._pending = ""
            break
        return "".join(visible)

    def finish(self) -> str:
        if self._capturing:
            self._pending = ""
            return ""
        visible = self._pending
        self._pending = ""
        return visible


class _ContinuationDeduper:
    """Remove only a repeated suffix while a continuation stream establishes overlap."""

    def __init__(self, reference: str | None) -> None:
        self.reference = (reference or "")[-_MAX_CONTINUATION_OVERLAP_CHARS:]
        self._pending = ""
        self._resolved = not self.reference
        self.suppressed_chars = 0

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        if self._resolved:
            return chunk
        self._pending += chunk
        if self._pending in self.reference:
            return ""
        return self._resolve()

    def finish(self) -> str:
        return "" if self._resolved else self._resolve()

    def _resolve(self) -> str:
        overlap = 0
        for size in range(min(len(self.reference), len(self._pending)), 0, -1):
            if self._pending.startswith(self.reference[-size:]):
                overlap = size
                break
        visible = self._pending[overlap:]
        self.suppressed_chars += overlap
        self._pending = ""
        self._resolved = True
        return visible


def _matching_prefix_suffix(value: str, prefix: str) -> int:
    for size in range(min(len(value), len(prefix) - 1), 0, -1):
        if value.endswith(prefix[:size]):
            return size
    return 0
