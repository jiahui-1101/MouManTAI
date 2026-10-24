"""C3 typed task adapter over P1's sole Qwen/Gemini reliability boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.context.ai.endpoint import EndpointAdapter, EndpointConfig
from app.context.ai.protocol import InferenceFailure, InferenceInput, SourceText
from app.context.ai.provider_reliability import (
    GeminiConfig,
    GeminiEndpointAdapter,
    QwenGeminiReliabilityAdapter,
)

from .contracts import ProviderAttempt, SemanticAssessment


@dataclass(frozen=True)
class ClassificationResult:
    assessment: SemanticAssessment
    provider: str
    model_id: str
    attempts: tuple[ProviderAttempt, ...]


class P1ClassificationGateway:
    def __init__(self, reliability: QwenGeminiReliabilityAdapter):
        self.reliability = reliability

    @classmethod
    def from_env_or_none(cls):
        primary = EndpointConfig.from_env_or_none()
        if primary is None:
            return None
        fallback = GeminiConfig.from_env_or_none()
        return cls(QwenGeminiReliabilityAdapter(
            EndpointAdapter(primary), GeminiEndpointAdapter(fallback) if fallback else None
        ))

    async def classify_async(self, segments: list[tuple[str, str]]) -> ClassificationResult:
        request = InferenceInput(
            engine="qwen", task="c3_classification",
            messages=[SourceText(id=source_id, text=value) for source_id, value in segments],
        )
        output = await self.reliability.infer(request)
        if output.validation_outcome != "VALIDATED" or output.classification is None:
            raise InferenceFailure("schema_validation")
        provider = "QWEN" if output.provider == "qwen" else "GEMINI"
        attempts = []
        if output.fallback_trigger:
            attempts.append(ProviderAttempt(
                provider="QWEN", attempt_number=1, status="INVALID_OUTPUT"
                if output.fallback_trigger in {"invalid_json", "schema_validation", "incomplete_or_invalid_output"}
                else "TIMEOUT" if output.fallback_trigger == "timeout" else "PROVIDER_ERROR",
                error_code=output.fallback_trigger, duration_ms=0,
            ))
        attempts.append(ProviderAttempt(
            provider=provider, attempt_number=1, status="VALID",
            input_tokens=output.input_tokens, output_tokens=output.output_tokens,
            duration_ms=output.provider_latency_ms or 0,
        ))
        return ClassificationResult(output.classification, provider, output.model_id, tuple(attempts))

    def classify(self, segments: list[tuple[str, str]]) -> ClassificationResult:
        """Synchronous C3 entry point; async callers use classify_async directly."""
        return asyncio.run(self.classify_async(segments))
