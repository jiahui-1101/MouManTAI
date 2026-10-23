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


def prepare_model_proposal_service(endpoint=None, *, enabled: bool | None = None, stages: tuple[str, ...] | None = None):
    """Opt-in preparation seam with lazy environment resolution.

    If endpoint is not supplied, it resolves from P1_AI_ENDPOINT_URL/P1_AI_API_KEY
    if available in the environment. If enabled is None, it defaults to False unless
    an endpoint is configured and P1_AI_ENABLED is truthy.
    No heavy model imports or downloads occur during this factory initialization.
    """
    import os
    from .ai.endpoint import EndpointAdapter, EndpointConfig
    from .ai.service import ModelProposalService

    if endpoint is None:
        cfg = EndpointConfig.from_env_or_none()
        if cfg is not None:
            endpoint = EndpointAdapter(cfg)

    is_enabled = enabled
    if is_enabled is None:
        env_flag = os.environ.get("P1_AI_ENABLED", "").lower()
        is_enabled = env_flag in ("1", "true", "yes") and endpoint is not None

    stage_tuple = stages
    if stage_tuple is None:
        env_stages = os.environ.get("P1_AI_STAGES")
        if env_stages:
            stage_tuple = tuple(s.strip() for s in env_stages.split(",") if s.strip())
        else:
            stage_tuple = ("gliner",)  # L2 requires an explicit P1_AI_STAGES opt-in.

    return ModelProposalService(endpoint, enabled=is_enabled, stages=stage_tuple)
