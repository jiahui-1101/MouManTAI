"""Replaceable local entry point. Never deploy as the shared application."""

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
