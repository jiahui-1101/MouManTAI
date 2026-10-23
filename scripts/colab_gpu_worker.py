"""Optional CUDA host. Reuses the pinned evaluator worker; no provisioning on import.
Run with PYTHONPATH=backend and a private P1_AI_API_KEY in an isolated GPU environment.
Updating this file does not update an already running notebook.
"""
import hmac
import os
import threading
from fastapi import FastAPI, Header, HTTPException
from app.context.ai.protocol import InferenceInput, InferenceOutput
from app.context.ai.worker import ModelRuntime

runtime = ModelRuntime()
gate = threading.Lock()
app = FastAPI(title="MouManTAI P1 optional CUDA worker")

@app.get("/health")
def health():
    import torch
    cuda = torch.cuda.is_available()
    return {"status": "reachable", "cuda_available": cuda,
            "device_reported": torch.cuda.get_device_name(0) if cuda else "CPU",
            "device": runtime.device,
            "model_loaded": bool(runtime.loaded)}

@app.post("/infer", response_model=InferenceOutput)
def infer(request: InferenceInput, authorization: str | None = Header(None)):
    secret = os.environ.get("P1_AI_API_KEY", "")
    if not secret:
        raise HTTPException(503, "Worker authentication is unconfigured")
    if not hmac.compare_digest(authorization or "", "Bearer " + secret):
        raise HTTPException(401, "Unauthorized")
    if not gate.acquire(blocking=False):
        raise HTTPException(429, "Worker busy; no automatic retry")
    try:
        return runtime.predict(request)
    except Exception:
        raise HTTPException(503, "Model inference unavailable") from None
    finally:
        gate.release()

if __name__ == "__main__":
    import uvicorn
    if not os.environ.get("P1_AI_API_KEY"):
        raise SystemExit("Set a private P1_AI_API_KEY before serving")
    uvicorn.run(app, host="127.0.0.1", port=8000)
