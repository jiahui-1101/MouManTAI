"""P1-private proposal protocol; not a shared BusinessContext contract."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL_CONFIG = {
    "gliner": ("urchade/gliner_multi-v2.1", "443d26d654e0324125a96bebd8e796c14ff2efe6"),
    "qwen": ("Qwen/Qwen3-4B-Instruct-2507", "cdbee75f17c01a7cc42f958dc650907174af0554"),
    "gemini": ("gemini-3.8-flash", "google-generative-language-v1beta"),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceText(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=4000)


class InferenceInput(StrictModel):
    engine: Literal["gliner", "qwen"]
    messages: list[SourceText] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def bounded_context(self):
        if len({m.id for m in self.messages}) != len(self.messages):
            raise ValueError("Duplicate source ID")
        if sum(len(m.text) for m in self.messages) > 4000:
            raise ValueError("Context budget exceeded; do not silently truncate")
        return self


class Observation(StrictModel):
    field: Literal["product", "quantity", "unit", "delivery", "order_reference"]
    message_id: str = Field(min_length=1, max_length=40)
    quote: str = Field(min_length=1, max_length=500)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    group_id: str | None = Field(default=None, max_length=40)


class Answer(StrictModel):
    fields: list[Observation] = Field(max_length=40)


class InferenceOutput(StrictModel):
    engine: Literal["gliner", "qwen"]
    provider: Literal["gliner", "qwen", "gemini"] | None = None
    model_id: str
    revision: str
    status: Literal["ok", "invalid_output", "input_too_long", "unavailable"]
    fields: list[Observation] = Field(default_factory=list, max_length=40)
    raw_output: str = Field(default="", max_length=32000)
    finish_reason: str = Field(max_length=60)
    load_seconds: float = Field(ge=0)
    inference_seconds: float = Field(ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    peak_gpu_bytes: int | None = Field(default=None, ge=0)
    gpu_name: str | None = Field(default=None, max_length=200)
    dtype: str | None = Field(default=None, max_length=60)
    runtime_versions: dict[str, str] = Field(default_factory=dict)
    fallback_trigger: str | None = Field(default=None, max_length=60)
    provider_attempts: int = Field(default=1, ge=1, le=6)
    provider_latency_ms: int | None = Field(default=None, ge=0, le=600_000)
    redacted_span_count: int = Field(default=0, ge=0, le=1000)
    validation_outcome: Literal["NOT_VALIDATED", "VALIDATED"] = "NOT_VALIDATED"


class InferenceFailure(Exception):
    """Only fixed error codes cross the boundary; no credential/HTTP body echo."""

    SAFE_CODES = frozenset(
        {
            "timeout",
            "rate_limited",
            "service_unavailable",
            "transport_error",
            "retryable_provider_error",
            "provider_internal_error",
            "provider_rejected",
            "busy",
            "invalid_json",
            "schema_validation",
            "incomplete_or_invalid_output",
            "invalid_output",
            "response_budget_exceeded",
            "model_mismatch",
            "source_evidence_invalid",
            "redacted_evidence_blocked",
            "missing_source_or_invalid_span",
            "evidence_mismatch",
            "unavailable",
            "worker_connection_refused",
            "endpoint_http_error",
            "transport_or_schema_error",
            "invalid_context_or_candidate",
            "invalid_structured_output",
            "endpoint_job_not_completed",
            "job_id_mismatch",
            "unsupported_engine",
            "credentials_missing",
            "provider_disabled",
        }
    )

    def __init__(
        self,
        code: str,
        *,
        audit: dict | None = None,
        attempt_count: int = 1,
        latency_ms: int | None = None,
    ):
        self.code = code if code in self.SAFE_CODES else "provider_internal_error"
        self.audit = audit
        self.attempt_count = max(1, min(6, int(attempt_count)))
        self.latency_ms = latency_ms
        super().__init__(self.code)


class RawFallbackObservation(StrictModel):
    field: Literal["product", "quantity", "unit", "delivery", "order_reference"]
    message_id: str
    quote: str = Field(min_length=1, max_length=500)
    group_id: str | None = Field(default=None, max_length=40)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, gt=0)


class RawFallbackAnswer(StrictModel):
    fields: list[RawFallbackObservation] = Field(max_length=40)


def _recover_token_bounded_output(answer: InferenceOutput, request: InferenceInput) -> InferenceOutput | None:
    if not answer.raw_output or answer.finish_reason != "stop":
        return None
    try:
        parsed = RawFallbackAnswer.model_validate_json(answer.raw_output)
    except Exception:
        return None
    sources = {m.id: m.text for m in request.messages}
    recovered: list[Observation] = []
    for cand in parsed.fields:
        source = sources.get(cand.message_id)
        if source is None:
            return None
        start, end = cand.start, cand.end
        if start is None and end is None:
            if source.count(cand.quote) == 1:
                start = source.index(cand.quote)
                end = start + len(cand.quote)
            else:
                matches = list(re.finditer(
                    r"(?<![A-Za-z0-9])" + re.escape(cand.quote) + r"(?![A-Za-z0-9])",
                    source,
                ))
                if len(matches) == 1:
                    start, end = matches[0].span()
        if start is None or end is None or not 0 <= start < end <= len(source) or source[start:end] != cand.quote:
            return None
        recovered.append(
            Observation(
                field=cand.field,
                message_id=cand.message_id,
                quote=cand.quote,
                start=start,
                end=end,
                group_id=cand.group_id,
            )
        )
    return answer.model_copy(update={"status": "ok", "fields": recovered})


def validate_evidence(answer: InferenceOutput, request: InferenceInput) -> InferenceOutput:
    provider = answer.provider or answer.engine
    allowed_providers = {"gliner"} if request.engine == "gliner" else {"qwen", "gemini"}
    if answer.engine != request.engine or provider not in allowed_providers:
        raise InferenceFailure("model_mismatch")
    expected = MODEL_CONFIG.get(provider)
    if expected is None:
        raise InferenceFailure("model_mismatch")
    if provider == "gemini":
        if (
            answer.revision != MODEL_CONFIG["gemini"][1]
            or not re.fullmatch(r"gemini-[A-Za-z0-9._-]{1,100}", answer.model_id)
        ):
            raise InferenceFailure("model_mismatch")
    elif (answer.model_id, answer.revision) != expected:
        raise InferenceFailure("model_mismatch")
    if answer.status == "invalid_output" and answer.finish_reason == "stop":
        recovered = _recover_token_bounded_output(answer, request)
        if recovered is not None:
            answer = recovered
    if answer.status != "ok" or answer.finish_reason != "stop":
        raise InferenceFailure("incomplete_or_invalid_output")
    sources = {m.id: m.text for m in request.messages}
    for field in answer.fields:
        source = sources.get(field.message_id)
        if source is None or not 0 <= field.start < field.end <= len(source):
            raise InferenceFailure("missing_source_or_invalid_span")
        if source[field.start:field.end] != field.quote:
            raise InferenceFailure("evidence_mismatch")
    # Actual offsets disambiguate repeated quotes. No source search, repair,
    # translation, whitespace folding or semantic correctness claim is made.
    return answer.model_copy(update={"validation_outcome": "VALIDATED"})
