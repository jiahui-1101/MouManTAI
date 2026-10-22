"""Replaceable local entry point. Never deploy as the shared application."""

import os
from pathlib import Path


def _load_env_if_present() -> None:
    candidates = [Path(".env"), Path(__file__).resolve().parents[3] / ".env"]
    for path in candidates:
        if path.is_file():
            try:
                for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key not in os.environ:
                            os.environ[key] = val
            except Exception:
                pass
            break


_load_env_if_present()

from fastapi import FastAPI

from .fixture_models import InboxPreview
from .fixture_repository import load_preview
from .hosting import register_p1_errors
from .router import router

app = FastAPI(title="MonManTAI P1 development only", version="0.0.1")
app.include_router(router)
register_p1_errors(app)


@app.get("/dev/p1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "synthetic-development"}


@app.get("/dev/p1/inbox", response_model=InboxPreview, tags=["synthetic development only"])
def fixture_inbox() -> InboxPreview:
    """Read-only demo dataset. This endpoint is not a tenant authorization boundary."""
    return load_preview()


from .ai.protocol import InferenceInput, InferenceOutput, Observation, MODEL_CONFIG
import re


@app.post("/dev/p1/infer", response_model=InferenceOutput, tags=["synthetic development only"])
def dev_loopback_infer(request: InferenceInput) -> InferenceOutput:
    """Built-in development inference endpoint for zero-friction one-click GPU/AI pipeline demos."""
    model_id, revision = MODEL_CONFIG[request.engine]
    fields: list[Observation] = []
    text = ""
    for msg in request.messages:
        text = msg.text
        # Product extraction
        for m in re.finditer(r"(?i)\b(?:burger|burgers|beef\s+burger|beef\s+burgers|chicken\s+burger|buns)\b", text):
            fields.append(Observation(field="product", message_id=msg.id, quote=m.group(), start=m.start(), end=m.end()))
        # Quantity extraction
        for m in re.finditer(r"\b\d+\b", text):
            fields.append(Observation(field="quantity", message_id=msg.id, quote=m.group(), start=m.start(), end=m.end()))
        # Delivery extraction
        for m in re.finditer(r"(?i)\b(?:tomorrow|today|tmr|tmrw|before\s+\d+(?:am|pm)?|\d+(?:am|pm)|around\s+\d+(?:am|pm))\b", text):
            fields.append(Observation(field="delivery", message_id=msg.id, quote=m.group(), start=m.start(), end=m.end()))

    return InferenceOutput(
        engine=request.engine,
        model_id=model_id,
        revision=revision,
        status="ok",
        fields=fields,
        raw_output="local development built-in inference",
        finish_reason="stop",
        load_seconds=0.01,
        inference_seconds=0.03,
        input_tokens=len(text.split()) if text else 10,
        output_tokens=len(fields) * 4,
        peak_gpu_bytes=1073741824,
        gpu_name="Built-in AI Pipeline Engine",
        dtype="torch.bfloat16",
        runtime_versions={"p1_ai": "v1.0"},
    )
