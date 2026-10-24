"""Qwen-primary structured extraction with a bounded Gemini fallback.

The adapter sends only one current message, after same-length PII masking.
Every model result is validated against the existing P1 span protocol before
it is converted back to the immutable original message offsets.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote

from pydantic import ValidationError

from .prompts import C3_CLASSIFICATION_PROMPT, SYSTEM_PROMPT
from .protocol import (
    MODEL_CONFIG,
    InferenceFailure,
    InferenceInput,
    InferenceOutput,
    RawFallbackAnswer,
    _recover_token_bounded_output,
    validate_evidence,
)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
MAX_GEMINI_RESPONSE_BYTES = 65_536
RETRYABLE_PROVIDER_ERRORS = frozenset(
    {"rate_limited", "service_unavailable", "transport_error", "retryable_provider_error"}
)
FALLBACK_TRIGGER_ERRORS = frozenset(
    {
        "timeout",
        "rate_limited",
        "service_unavailable",
        "transport_error",
        "retryable_provider_error",
        "unavailable",
        "worker_connection_refused",
        "endpoint_job_not_completed",
        "busy",
        "invalid_json",
        "schema_validation",
        "incomplete_or_invalid_output",
        "response_budget_exceeded",
        "model_mismatch",
    }
)


def eligible_technical_fallback(code: str) -> bool:
    """Only provider/response failures may advance to Gemini.

    Grounding disagreements, missing authority and ambiguous but valid output
    are review conditions, not reasons to ask another model for a preferred fact.
    """
    return code in FALLBACK_TRIGGER_ERRORS


_SENSITIVE_PATTERNS = (
    re.compile(
        r"(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+(?![\w-])",
        re.IGNORECASE,
    ),
    re.compile(r"(?<!\w)\+\d{1,3}(?:[ .()-]*\d){7,14}(?!\w)"),
    re.compile(r"(?<!\w)0\d{1,2}(?:[ .-]*\d){7,9}(?!\w)"),
    re.compile(r"(?<!\w)[689]\d{3}(?:[ .-]*\d{4})(?!\w)"),
    re.compile(r"(?<!\w)(?:\d[ .()-]?){10}(?!\w)"),
    re.compile(
        r"(?i)\b(?:ORD|PO|INV|CUST|SUP|ACCT|ACCOUNT|REF|TXN|PAY)(?:[-_/# ]+[A-Z0-9][A-Z0-9/_-]{2,}|[0-9][A-Z0-9/_-]{2,})\b"
    ),
    re.compile(r"(?<!\w)(?:\d[ -]?){13,19}(?!\w)"),
    re.compile(
        r"(?<!\w)(?:(?:no\.?\s*)?\d{1,5}\s+)?(?:jalan|jln|lorong|lg|persiaran|street|st|road|rd|avenue|ave)\s+[^,\n;.!?]{1,60}",
        re.IGNORECASE,
    ),
    re.compile(r"(?<!\w)(?!19\d{2}\b|20\d{2}\b)\d{5}(?!\w)"),
    re.compile(r"\b(?i:hi|hello|dear)\s+(?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+){0,2}\b"),
    re.compile(
        r"\b(?i:attn|attention|contact(?: person)?|customer name|supplier name|buyer name)"
        r"\s*[:#-]?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b"
    ),
    re.compile(r"(?i)\b(?:p\.?\s*o\.?\s*box)\s+[A-Z0-9 -]{2,20}\b"),
    re.compile(
        r"(?i)\b(?:[A-Z][\w&.-]+\s+){1,3}(?:Sdn\.?\s+Bhd\.?|Pte\.?\s+Ltd\.?|Limited|Ltd\.?|Inc\.?|LLC)\b"
    ),
)


@dataclass(frozen=True)
class RedactedRequest:
    request: InferenceInput
    spans_by_message: dict[str, tuple[tuple[int, int], ...]]


def redact_inference_request(request: InferenceInput) -> RedactedRequest:
    """Mask common personal/commercial identifiers without shifting offsets."""
    sanitized_messages = []
    spans_by_message: dict[str, tuple[tuple[int, int], ...]] = {}
    for message in request.messages:
        masked, merged = redact_source_text(message.text)
        sanitized_messages.append(message.model_copy(update={"text": masked}))
        spans_by_message[message.id] = merged
    return RedactedRequest(
        request=request.model_copy(update={"messages": sanitized_messages}),
        spans_by_message=spans_by_message,
    )


def redact_source_text(text: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    """The shared same-length external-provider masking policy."""
    ranges = sorted(
        {
            match.span()
            for pattern in _SENSITIVE_PATTERNS
            for match in pattern.finditer(text)
            if match.start() < match.end()
        }
    )
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    characters = list(text)
    for start, end in merged:
        characters[start:end] = ["*"] * (end - start)
    return "".join(characters), tuple(merged)


def _restore_original_spans(
    answer: InferenceOutput,
    original: InferenceInput,
    redacted_spans: dict[str, tuple[tuple[int, int], ...]],
) -> InferenceOutput:
    originals = {item.id: item.text for item in original.messages}
    fields = []
    for observation in answer.fields:
        source = originals.get(observation.message_id)
        if source is None or not 0 <= observation.start < observation.end <= len(source):
            raise InferenceFailure("source_evidence_invalid")
        if any(
            observation.start < redacted_end and redacted_start < observation.end
            for redacted_start, redacted_end in redacted_spans.get(observation.message_id, ())
        ):
            raise InferenceFailure("redacted_evidence_blocked")
        fields.append(
            observation.model_copy(update={"quote": source[observation.start : observation.end]})
        )
    classification = answer.classification
    if classification is not None:
        claims = []
        for claim in classification.claims:
            citation = claim.evidence
            source = originals.get(citation.segment_id)
            if source is None or citation.end > len(source):
                raise InferenceFailure("source_evidence_invalid")
            if any(citation.start < right and left < citation.end
                   for left, right in redacted_spans.get(citation.segment_id, ())):
                raise InferenceFailure("redacted_evidence_blocked")
            claims.append(claim.model_copy(update={"evidence": citation.model_copy(
                update={"quote": source[citation.start:citation.end]})}))
        classification = classification.model_copy(update={"claims": claims})
    restored = answer.model_copy(update={"fields": fields, "classification": classification, "raw_output": ""})
    return validate_evidence(restored, original)


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str = field(repr=False)
    model_id: str = MODEL_CONFIG["gemini"][0]
    timeout_seconds: float = 20.0
    max_retries: int = 1
    max_response_bytes: int = MAX_GEMINI_RESPONSE_BYTES

    def __post_init__(self):
        if not self.api_key or len(self.api_key) > 4096:
            raise ValueError("Gemini API key is required")
        if not re.fullmatch(r"gemini-[A-Za-z0-9._-]{1,100}", self.model_id):
            raise ValueError("Invalid Gemini model name")
        if not 0.1 <= self.timeout_seconds <= 60:
            raise ValueError("Gemini timeout must be between 0.1 and 60 seconds")
        if not 0 <= self.max_retries <= 2:
            raise ValueError("Gemini retries must be between 0 and 2")
        if not 1024 <= self.max_response_bytes <= MAX_GEMINI_RESPONSE_BYTES:
            raise ValueError("Invalid Gemini response budget")

    @classmethod
    def from_env_or_none(cls) -> GeminiConfig | None:
        api_key = os.environ.get("P1_GEMINI_API_KEY")
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            model_id=os.environ.get("P1_GEMINI_MODEL", MODEL_CONFIG["gemini"][0]),
            timeout_seconds=float(os.environ.get("P1_GEMINI_TIMEOUT_SECONDS", "20")),
            max_retries=int(os.environ.get("P1_GEMINI_MAX_RETRIES", "1")),
        )


def _gemini_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "maxItems": 40,
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": ["product", "quantity", "unit", "delivery", "order_reference"],
                        },
                        "message_id": {"type": "string"},
                        "quote": {"type": "string"},
                        "group_id": {"type": ["string", "null"]},
                        "start": {"type": ["integer", "null"]},
                        "end": {"type": ["integer", "null"]},
                    },
                    "required": ["field", "message_id", "quote"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["fields"],
        "additionalProperties": False,
    }


def _c3_gemini_schema() -> dict:
    citation = {"type": "object", "properties": {
        "segment_id": {"type": "string"}, "quote": {"type": "string"},
        "start": {"type": "integer"}, "end": {"type": "integer"}},
        "required": ["segment_id", "quote", "start", "end"], "additionalProperties": False}
    return {"type": "object", "properties": {
        "intent": {"type": "string", "enum": ["CUSTOMER_INQUIRY", "CUSTOMER_ORDER_REQUEST", "SUPPLIER_DELAY", "OTHER", "UNKNOWN"]},
        "inquiry_topic": {"type": ["string", "null"], "enum": ["PRICE", "AVAILABILITY", "DELIVERY", "PRODUCT_INFO", "OTHER", None]},
        "claims": {"type": "array", "maxItems": 12, "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["INQUIRY", "SUPPLIER_DELAY", "DELIVERY_REFERENCE", "REPORTED_ETA", "ORDER_REQUEST"]},
            "value": {"type": "string"}, "evidence": citation},
            "required": ["kind", "value", "evidence"], "additionalProperties": False}}},
        "required": ["intent", "inquiry_topic", "claims"], "additionalProperties": False}


class GeminiEndpointAdapter:
    """Direct, bounded Google Gemini structured-output adapter."""

    def __init__(self, config: GeminiConfig, *, transport=None):
        self.config = config
        self.transport = transport

    async def infer(self, request: InferenceInput) -> InferenceOutput:
        if request.engine != "qwen":
            raise InferenceFailure("unsupported_engine")
        started = time.perf_counter()
        attempts = 0
        while True:
            attempts += 1
            try:
                output = await self._infer_once(request)
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                return output.model_copy(
                    update={"provider_attempts": attempts, "provider_latency_ms": elapsed_ms}
                )
            except InferenceFailure as failure:
                if (
                    failure.code in RETRYABLE_PROVIDER_ERRORS
                    and attempts <= self.config.max_retries
                ):
                    await asyncio.sleep(min(0.1 * attempts, 0.25))
                    continue
                raise InferenceFailure(
                    failure.code,
                    attempt_count=attempts,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                ) from None

    async def _infer_once(self, request: InferenceInput) -> InferenceOutput:
        import httpx

        model = quote(self.config.model_id, safe="-_.")
        url = f"{GEMINI_API_BASE}models/{model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": C3_CLASSIFICATION_PROMPT if request.task == "c3_classification" else SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                request.model_dump(mode="json")["messages"], ensure_ascii=False
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "candidateCount": 1,
                "temperature": 0,
                "maxOutputTokens": 1024,
                "responseFormat": {
                    "text": {
                        "mimeType": "APPLICATION_JSON",
                        "schema": _c3_gemini_schema() if request.task == "c3_classification" else _gemini_schema(),
                    }
                },
            },
        }
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                async with (
                    httpx.AsyncClient(
                        transport=self.transport,
                        timeout=self.config.timeout_seconds,
                        follow_redirects=False,
                        trust_env=False,
                    ) as client,
                    client.stream(
                        "POST",
                        url,
                        json=payload,
                        headers={
                            "x-goog-api-key": self.config.api_key,
                            "Content-Type": "application/json",
                        },
                    ) as response,
                ):
                    if response.status_code == 429:
                        raise InferenceFailure("rate_limited")
                    if 500 <= response.status_code < 600:
                        raise InferenceFailure("service_unavailable")
                    if response.status_code != 200:
                        raise InferenceFailure("provider_rejected")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > self.config.max_response_bytes:
                            raise InferenceFailure("response_budget_exceeded")
        except InferenceFailure:
            raise
        except TimeoutError:
            raise InferenceFailure("timeout") from None
        except httpx.TimeoutException:
            raise InferenceFailure("timeout") from None
        except httpx.TransportError:
            raise InferenceFailure("transport_error") from None
        except Exception:  # noqa: BLE001 -- hide unexpected transport details at the provider boundary.
            raise InferenceFailure("provider_internal_error") from None

        try:
            body = json.loads(chunks)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InferenceFailure("invalid_json") from None
        try:
            candidate = body["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise InferenceFailure("incomplete_or_invalid_output")
            parts = candidate["content"]["parts"]
            raw_text = "".join(part["text"] for part in parts if isinstance(part.get("text"), str))
            if not raw_text:
                raise InferenceFailure("invalid_output")
            decoded = json.loads(raw_text)
        except InferenceFailure:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise InferenceFailure("invalid_json") from None
        try:
            if request.task == "c3_classification":
                from app.message_intelligence.contracts import SemanticAssessment
                SemanticAssessment.model_validate(decoded)
            else:
                RawFallbackAnswer.model_validate(decoded)
        except ValidationError:
            raise InferenceFailure("schema_validation") from None

        ungrounded = InferenceOutput(
            engine="qwen",
            provider="gemini",
            model_id=self.config.model_id,
            revision=MODEL_CONFIG["gemini"][1],
            status="invalid_output",
            raw_output=raw_text,
            finish_reason="stop",
            load_seconds=0.0,
            inference_seconds=0.0,
        )
        if request.task == "c3_classification":
            return validate_evidence(ungrounded, request).model_copy(update={"raw_output": ""})
        grounded = _recover_token_bounded_output(ungrounded, request)
        if grounded is None:
            raise InferenceFailure("source_evidence_invalid")
        return validate_evidence(grounded, request).model_copy(update={"raw_output": ""})


class QwenGeminiReliabilityAdapter:
    """Redacts shared provider input and falls back only on technical failure."""

    def __init__(self, primary, fallback: GeminiEndpointAdapter | None = None):
        self.primary = primary
        self.fallback = fallback
        self.config = getattr(primary, "config", None)
        self.cache_key = (
            getattr(self.config, "url", ""),
            getattr(self.config, "mode", ""),
            getattr(getattr(fallback, "config", None), "model_id", ""),
            getattr(getattr(fallback, "config", None), "timeout_seconds", None),
            getattr(getattr(fallback, "config", None), "max_retries", None),
            "same-length-redaction-v1",
        )

    async def infer(self, request: InferenceInput) -> InferenceOutput:
        redacted = redact_inference_request(request)
        if request.engine != "qwen":
            try:
                output = await self.primary.infer(redacted.request)
                output = InferenceOutput.model_validate(
                    output.model_dump() if isinstance(output, InferenceOutput) else output
                )
                output = validate_evidence(output, redacted.request)
                restored = _restore_original_spans(output, request, redacted.spans_by_message)
                return restored.model_copy(
                    update={
                        "provider_attempts": 1,
                        "provider_latency_ms": output.provider_latency_ms or 0,
                        "redacted_span_count": sum(
                            len(items) for items in redacted.spans_by_message.values()
                        ),
                        "validation_outcome": "VALIDATED",
                    }
                )
            except InferenceFailure:
                raise
            except (ValidationError, ValueError, TypeError):
                raise InferenceFailure("schema_validation") from None

        started = time.perf_counter()
        primary_started = time.perf_counter()
        try:
            raw = await self.primary.infer(redacted.request)
            primary = InferenceOutput.model_validate(
                raw.model_dump() if isinstance(raw, InferenceOutput) else raw
            )
            primary = validate_evidence(primary, redacted.request)
            if primary.provider not in {None, "qwen"}:
                raise InferenceFailure("model_mismatch")
            primary = _restore_original_spans(primary, request, redacted.spans_by_message)
            latency_ms = round((time.perf_counter() - started) * 1000)
            return primary.model_copy(
                update={
                    "provider": "qwen",
                    "fallback_trigger": None,
                    "provider_attempts": 1,
                    "provider_latency_ms": latency_ms,
                    "redacted_span_count": sum(
                        len(items) for items in redacted.spans_by_message.values()
                    ),
                    "validation_outcome": "VALIDATED",
                }
            )
        except InferenceFailure as failure:
            primary_failure = failure.code
        except (ValidationError, ValueError, TypeError):
            primary_failure = "schema_validation"
        except Exception:  # noqa: BLE001 -- sanitize unexpected custom-adapter failures.
            primary_failure = "provider_internal_error"
        primary_latency_ms = round((time.perf_counter() - primary_started) * 1000)

        should_fallback = eligible_technical_fallback(primary_failure)
        fallback = self.fallback if should_fallback else None
        if fallback is None:
            audit = {
                "primary_provider": "qwen",
                "provider_used": None,
                "fallback_provider": "gemini",
                "fallback_trigger": primary_failure if should_fallback else None,
                "primary_error": primary_failure,
                "fallback_error": "credentials_missing"
                if should_fallback and self.fallback is None
                else None,
                "validation_outcome": "PRIMARY_FAILED",
                "latency_ms": primary_latency_ms,
                "primary_attempts": 1,
                "fallback_attempts": 0,
                "redacted_span_count": sum(
                    len(items) for items in redacted.spans_by_message.values()
                ),
                "review_required": True,
            }
            raise InferenceFailure(
                primary_failure, audit=audit, latency_ms=primary_latency_ms
            ) from None

        try:
            raw_fallback = await fallback.infer(redacted.request)
            fallback_output = InferenceOutput.model_validate(
                raw_fallback.model_dump()
                if isinstance(raw_fallback, InferenceOutput)
                else raw_fallback
            )
            fallback_output = validate_evidence(fallback_output, redacted.request)
            if fallback_output.provider != "gemini":
                raise InferenceFailure("model_mismatch")
            fallback_output = _restore_original_spans(
                fallback_output, request, redacted.spans_by_message
            )
            total_latency = round((time.perf_counter() - started) * 1000)
            attempts = 1 + fallback_output.provider_attempts
            return fallback_output.model_copy(
                update={
                    "provider": "gemini",
                    "fallback_trigger": primary_failure,
                    "provider_attempts": attempts,
                    "provider_latency_ms": total_latency,
                    "redacted_span_count": sum(
                        len(items) for items in redacted.spans_by_message.values()
                    ),
                    "validation_outcome": "VALIDATED",
                }
            )
        except InferenceFailure as failure:
            fallback_failure = failure.code
            fallback_attempts = failure.attempt_count
            fallback_latency_ms = failure.latency_ms or 0
        except (ValidationError, ValueError, TypeError):
            fallback_failure = "schema_validation"
            fallback_attempts = 1
            fallback_latency_ms = 0
        except Exception:  # noqa: BLE001 -- sanitize unexpected fallback failures.
            fallback_failure = "provider_internal_error"
            fallback_attempts = 1
            fallback_latency_ms = 0

        total_latency = round((time.perf_counter() - started) * 1000)
        audit = {
            "primary_provider": "qwen",
            "provider_used": None,
            "fallback_provider": "gemini",
            "fallback_trigger": primary_failure,
            "primary_error": primary_failure,
            "fallback_error": fallback_failure,
            "validation_outcome": "BOTH_FAILED",
            "latency_ms": total_latency,
            "primary_latency_ms": primary_latency_ms,
            "fallback_latency_ms": fallback_latency_ms,
            "primary_attempts": 1,
            "fallback_attempts": fallback_attempts,
            "redacted_span_count": sum(len(items) for items in redacted.spans_by_message.values()),
            "review_required": True,
        }
        raise InferenceFailure(
            fallback_failure,
            audit=audit,
            attempt_count=1 + fallback_attempts,
            latency_ms=total_latency,
        ) from None
