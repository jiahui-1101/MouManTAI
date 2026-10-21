"""P1-private proposal protocol; not a shared BusinessContext contract."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL_CONFIG = {
    "gliner": ("urchade/gliner_multi-v2.1", "443d26d654e0324125a96bebd8e796c14ff2efe6"),
    "qwen": ("Qwen/Qwen3-4B-Instruct-2507", "cdbee75f17c01a7cc42f958dc650907174af0554"),
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


class InferenceFailure(Exception):
    """Only fixed error codes cross the boundary; no credential/HTTP body echo."""


def validate_evidence(answer: InferenceOutput, request: InferenceInput) -> InferenceOutput:
    expected = MODEL_CONFIG[request.engine]
    if answer.engine != request.engine or (answer.model_id, answer.revision) != expected:
        raise InferenceFailure("model_mismatch")
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
    return answer
