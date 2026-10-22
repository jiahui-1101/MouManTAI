"""Self-contained Google Colab CPU/GPU GLiNER worker.

Can be run directly as a script or copied into a Google Colab notebook cell.
Zero dependency on the rest of the repository code.
"""
import hmac
import json
import os
import re
import threading
import time
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
import importlib.metadata
from pydantic import BaseModel, ConfigDict, Field
import uvicorn

MODEL_CONFIG = {
    "gliner": ("urchade/gliner_multi-v2.1", "443d26d654e0324125a96bebd8e796c14ff2efe6"),
}
LABELS = {
    "product": "product",
    "quantity": "quantity",
    "unit": "unit",
    "delivery date or time": "delivery",
}
THRESHOLD = 0.35


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceText(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=4000)


class InferenceInput(StrictModel):
    engine: Literal["gliner", "qwen"]
    messages: list[SourceText] = Field(min_length=1, max_length=4)


class Observation(StrictModel):
    field: Literal["product", "quantity", "unit", "delivery", "order_reference"]
    message_id: str = Field(min_length=1, max_length=40)
    quote: str = Field(min_length=1, max_length=500)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    group_id: str | None = Field(default=None, max_length=40)


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
    gpu_name: str | None = Field(default=None, max_length=200)
    dtype: str | None = Field(default=None, max_length=60)
    runtime_versions: dict[str, str] = Field(default_factory=dict)


class OffsetSplitter:
    pattern = re.compile(r"[\u3400-\u9fff]|[A-Za-zÀ-ÖØ-öø-ÿ]+(?:[-_][A-Za-z]+)*|[0-9]+(?:\.[0-9]+)?|[^\s]")

    def __call__(self, text):
        for match in self.pattern.finditer(text):
            yield match.group(), match.start(), match.end()


# Global model holder
_gliner_model = None
_gliner_tokenizer = None
_load_time = 0.0
_device = "cpu"


def get_gliner():
    global _gliner_model, _gliner_tokenizer, _load_time, _device
    if _gliner_model is not None:
        return _gliner_model, _gliner_tokenizer, 0.0

    import torch
    from gliner import GLiNER

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    t0 = time.perf_counter()
    model_id, revision = MODEL_CONFIG["gliner"]
    _gliner_model = GLiNER.from_pretrained(model_id)
    if hasattr(_gliner_model, 'data_processor'):
        _gliner_model.data_processor.words_splitter = OffsetSplitter()
    _gliner_model.to(_device)
    _gliner_model.eval()
    _gliner_tokenizer = _gliner_model.data_processor.transformer_tokenizer
    _load_time = time.perf_counter() - t0
    return _gliner_model, _gliner_tokenizer, _load_time


app = FastAPI(title="MouManTAI P1 GLiNER Inference Worker")
gate = threading.Lock()


@app.get("/health")
def health():
    import torch
    cuda = torch.cuda.is_available()
    return {
        "status": "reachable",
        "cuda_available": cuda,
        "device_reported": torch.cuda.get_device_name(0) if cuda else "CPU",
        "device": _device,
        "model_loaded": _gliner_model is not None,
    }


@app.post("/infer", response_model=InferenceOutput)
def infer(request: InferenceInput, authorization: str | None = Header(None)):
    secret = os.environ.get("P1_AI_API_KEY", "p1-colab-secret")
    if not hmac.compare_digest(authorization or "", "Bearer " + secret):
        raise HTTPException(401, "Unauthorized")

    if request.engine != "gliner":
        raise HTTPException(503, f"Engine '{request.engine}' is not deployed on this worker (GLiNER only)")

    if not gate.acquire(blocking=False):
        raise HTTPException(429, "Worker busy")

    try:
        import torch

        model, tokenizer, load_s = get_gliner()
        t0 = time.perf_counter()
        entities = []
        fields = []
        input_tokens = 0
        status, finish_reason = "ok", "stop"

        with torch.inference_mode():
            for source in request.messages:
                count = len(tokenizer(source.text, add_special_tokens=False)["input_ids"])
                input_tokens += count
                if count > 300 or len(list(OffsetSplitter()(source.text))) > 300:
                    status, finish_reason = "input_too_long", "input_too_long"
                    break

                preds = model.predict_entities(source.text, list(LABELS.keys()), threshold=THRESHOLD)
                for ent in preds:
                    entities.append({"message_id": source.id, **ent})
                    fields.append(
                        Observation(
                            field=LABELS[ent["label"]],
                            message_id=source.id,
                            quote=ent["text"],
                            start=ent["start"],
                            end=ent["end"],
                        )
                    )

        raw = json.dumps(entities, ensure_ascii=False)
        dur = time.perf_counter() - t0
        cuda_avail = torch.cuda.is_available() and _device == "cuda"
        dtype_str = str(next(model.parameters()).dtype)

        return InferenceOutput(
            engine="gliner",
            model_id=MODEL_CONFIG["gliner"][0],
            revision=MODEL_CONFIG["gliner"][1],
            status=status,
            fields=fields,
            raw_output=raw,
            finish_reason=finish_reason,
            load_seconds=load_s,
            inference_seconds=dur,
            input_tokens=input_tokens,
            output_tokens=0,
            peak_gpu_bytes=torch.cuda.max_memory_allocated() if cuda_avail else None,
            gpu_name=torch.cuda.get_device_name() if cuda_avail else "CPU",
            dtype=dtype_str,
            runtime_versions={
                "torch": importlib.metadata.version("torch"),
                "gliner": importlib.metadata.version("gliner"),
                "transformers": importlib.metadata.version("transformers"),
                "huggingface-hub": importlib.metadata.version("huggingface-hub"),
                "p1_worker": "p1-colab-standalone-v1",
                "parameter_device": _device,
                "cuda_runtime": str(torch.version.cuda) if cuda_avail else "none",
            },
        )
    except Exception:
        raise HTTPException(503, "Model inference unavailable") from None
    finally:
        gate.release()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
