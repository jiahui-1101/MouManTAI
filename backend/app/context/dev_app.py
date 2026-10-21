"""Replaceable local entry point. Never deploy as the shared application."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .fixture_models import InboxPreview
from .fixture_repository import load_preview
from .ingestion import TenantMismatch, UnsupportedSyntheticChannel
from .repository import DuplicateConflict, PersistenceUnavailable
from .router import router

app = FastAPI(title="MonManTAI P1 development only", version="0.0.1")
app.include_router(router)


@app.exception_handler(PersistenceUnavailable)
def persistence_unavailable(request: Request, exc: PersistenceUnavailable):
    return JSONResponse(status_code=503, content={"detail": "Message storage unavailable; check the local P1 PostgreSQL setup"})


@app.exception_handler(DuplicateConflict)
def duplicate_conflict(request: Request, exc: DuplicateConflict):
    return JSONResponse(status_code=409, content={"detail": "Provider message ID already has different original content; the original was preserved"})


@app.exception_handler(TenantMismatch)
def tenant_mismatch(request: Request, exc: TenantMismatch):
    return JSONResponse(status_code=403, content={"detail": "Envelope tenant does not match the server development tenant"})


@app.exception_handler(UnsupportedSyntheticChannel)
def unsupported_channel(request: Request, exc: UnsupportedSyntheticChannel):
    return JSONResponse(status_code=422, content={"detail": "Only the synthetic WhatsApp-shaped adapter is implemented"})


@app.get("/dev/p1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "synthetic-development"}


@app.get("/dev/p1/inbox", response_model=InboxPreview, tags=["synthetic development only"])
def fixture_inbox() -> InboxPreview:
    """Read-only demo dataset. This endpoint is not a tenant authorization boundary."""
    return load_preview()
