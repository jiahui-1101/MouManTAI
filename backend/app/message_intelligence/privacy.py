"""Sensitive text minimization for external semantic-provider prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.IGNORECASE
)
_PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d ().-]{7,}\d(?!\w)")
_BANK_OR_LONG_ID_RE = re.compile(r"(?<!\w)\d{12,}(?!\w)")
_DATE_RE = re.compile(r"^20\d{2}[-/]\d{1,2}[-/]\d{1,2}$")


@dataclass(frozen=True)
class RedactedText:
    text: str
    hidden_ranges: tuple[tuple[int, int], ...]

    def overlaps_hidden(self, start: int, end: int) -> bool:
        return any(
            start < hidden_end and end > hidden_start
            for hidden_start, hidden_end in self.hidden_ranges
        )


def redact_sensitive_text(value: str) -> RedactedText:
    """Mask common contact/account data without changing Unicode code-point offsets."""
    chars = list(value)
    ranges: list[tuple[int, int]] = []

    candidates = (
        list(_EMAIL_RE.finditer(value))
        + list(_PHONE_RE.finditer(value))
        + list(_BANK_OR_LONG_ID_RE.finditer(value))
    )
    accepted: list[tuple[int, int]] = []
    for match in sorted(candidates, key=lambda item: (item.start(), -(item.end() - item.start()))):
        start, end = match.span()
        candidate = match.group(0).strip()
        if _DATE_RE.fullmatch(candidate):
            continue
        digit_count = sum(char.isdigit() for char in candidate)
        if match.re is _PHONE_RE and digit_count < 9 and not candidate.startswith("+"):
            continue
        if any(start < other_end and end > other_start for other_start, other_end in accepted):
            continue
        accepted.append((start, end))

    for start, end in accepted:
        ranges.append((start, end))
        for index in range(start, end):
            if not chars[index].isspace():
                chars[index] = "█"
    return RedactedText("".join(chars), tuple(ranges))
