"""P1-owned mounting boundary for a P5 host, with explicit dependency injection.

This does not install migrations, infer authentication or read tenant headers.
The host supplies a repository and a server-resolved DevelopmentContext provider.
"""

from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .dependencies import development_context, local_repository
from .ingestion import TenantMismatch, UnsupportedSyntheticChannel
from .repository import (
    DuplicateConflict,
    ExtractionNotFound,
    MessageNotFound,
    PersistenceUnavailable,
    ProcessingConflict,
)
from .router import router


def register_p1_errors(app: FastAPI) -> None:
    errors = {
        PersistenceUnavailable: (503, "Message storage unavailable; check the local P1 PostgreSQL setup"),
        DuplicateConflict: (409, "Provider message ID already has different original content; the original was preserved"),
        TenantMismatch: (403, "Envelope tenant does not match the server development tenant"),
        UnsupportedSyntheticChannel: (422, "Only the synthetic WhatsApp-shaped adapter is implemented"),
        MessageNotFound: (404, "Message not found"),
        ExtractionNotFound: (404, "Extraction attempt not found"),
        ProcessingConflict: (409, "Message processing conflict"),
    }
    for exception_type, (status, detail) in errors.items():
        def handler(request: Request, exc: Exception, *, status=status, detail=detail, etype=exception_type):
            msg = detail if etype is PersistenceUnavailable else (str(exc) if str(exc) else detail)
            return JSONResponse(status_code=status, content={"detail": msg})
        app.add_exception_handler(exception_type, handler)


def mount_p1_ingestion(app: FastAPI, *, repository_provider: Callable, tenant_provider: Callable) -> None:
    """Mount only ingestion routes/errors; fixture preview and dev shell stay separate.

    Providers may themselves use FastAPI dependencies (e.g. P5 get_db). The host
    must authorize its tenant mechanism; passing a header is not authentication.
    Response/error normalization and the provisional schema still need P5 review.
    """
    app.dependency_overrides[local_repository] = repository_provider
    app.dependency_overrides[development_context] = tenant_provider
    register_p1_errors(app)
    app.include_router(router)
