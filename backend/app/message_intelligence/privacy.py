"""C3 projection of the canonical P1 external-provider masking policy."""

from __future__ import annotations

from dataclasses import dataclass

from app.context.ai.provider_reliability import redact_source_text


@dataclass(frozen=True)
class RedactedText:
    text: str
    hidden_ranges: tuple[tuple[int, int], ...]

    def overlaps_hidden(self, start: int, end: int) -> bool:
        return any(start < right and end > left for left, right in self.hidden_ranges)


def redact_sensitive_text(value: str) -> RedactedText:
    masked, spans = redact_source_text(value)
    return RedactedText(masked, spans)
