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

from fastapi.middleware.cors import CORSMiddleware

from .fixture_models import InboxPreview
from .fixture_repository import load_preview
from .hosting import register_p1_errors
from .router import router

app = FastAPI(title="MonManTAI P1 development only", version="0.0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
register_p1_errors(app)


@app.get("/dev/p1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "synthetic-development"}


@app.get("/dev/p1/inbox", response_model=InboxPreview, tags=["synthetic development only"])
def fixture_inbox() -> InboxPreview:
    """Read-only demo dataset. This endpoint is not a tenant authorization boundary."""
    return load_preview()


@app.post("/dev/p1/infer", tags=["synthetic development only"])
def dev_loopback_infer():
    """Old launcher target: fail explicitly rather than impersonate a model."""
    from fastapi import HTTPException
    raise HTTPException(503, "No model is served locally; deterministic rules remain available")
