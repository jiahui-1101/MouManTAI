"""P1 extraction boundaries. Optional inference is lazy and disabled by default."""

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


def prepare_model_proposal_service(endpoint=None, *, enabled=False, stages=("gliner", "qwen")):
    """Opt-in preparation seam; not installed in ingestion or processing routes.

    Enable only for explicit evaluation until a real endpoint and the acceptance
    criteria are verified. No model imports/downloads occur in this factory.
    """
    from .ai.service import ModelProposalService
    return ModelProposalService(endpoint, enabled=enabled, stages=stages)
