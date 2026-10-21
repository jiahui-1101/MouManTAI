"""Minimal model boundary only. No inference, rules engine or model downloads."""

from typing import Literal, Protocol

from .schemas import ExtractedField, NormalizedMessage, P1Model


class ExtractionResult(P1Model):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    fields: list[ExtractedField]
    reason: str | None = None


class Extractor(Protocol):
    def extract(self, message: NormalizedMessage) -> ExtractionResult: ...


class UnavailableExtractor:
    def extract(self, message: NormalizedMessage) -> ExtractionResult:
        return ExtractionResult(status="UNAVAILABLE", fields=[], reason="No inference adapter configured; manual review required")
