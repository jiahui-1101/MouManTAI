from __future__ import annotations

import os
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.communication.router import router as communication_router
from app.context.router import router as context_router
from app.core.errors import DomainError
from app.core.feasibility_adapters import (
    AuthoritativeAssessmentHistoryReader,
    AuthoritativeImpactReader,
)
from app.core.router import router as core_router
from app.decision_memory.mock_router import router as mock_memory_router
from app.feasibility.api_dependencies import (
    get_assessment_history,
    get_impact_reader,
    require_isolated_e2e_key,
)
from app.feasibility.router import (
    feasibility_assessment_router,
    feasibility_read_router,
    feasibility_supplier_event_router,
)
from app.forecasting.mock_router import router as mock_forecast_router
from app.forecasting.router import router as forecasting_router
from app.optimization.mock_router import router as mock_optimization_router
from app.orders.api import router as orders_api_router
from app.orders.demo_router import router as orders_demo_router
from app.orders.router import router as orders_preview_router
from app.recovery.router import router as recovery_router
from app.suppliers.router import router as suppliers_router


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


app = FastAPI(title="MouManTAI API", version="0.1.0")

_P1_IDENTITY_PATHS = ("/dev/p1", "/v1/messages", "/v1/contexts", "/v1/attachments")


@app.middleware("http")
async def gate_p1_development_identity(request: Request, call_next):
    """Keep P1's separate development identity fallback behind the shared gate."""
    if (
        request.method != "OPTIONS"
        and request.url.path.startswith(_P1_IDENTITY_PATHS)
        and os.getenv("MOUMANTAI_SYNTHETIC_MODE", "0") != "1"
    ):
        return JSONResponse(
            status_code=403,
            content={
                "code": "SYNTHETIC_IDENTITY_DISABLED",
                "message": "Header-based demo identity is disabled; set MOUMANTAI_SYNTHETIC_MODE=1 only for a synthetic demo",
                "correlation_id": request.headers.get("X-Correlation-ID") or f"corr_{uuid4().hex}",
            },
        )
    return await call_next(request)

origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(core_router)
app.include_router(recovery_router)
app.include_router(communication_router)
app.include_router(feasibility_read_router)
app.include_router(context_router)
app.include_router(orders_preview_router)
app.include_router(orders_demo_router)
app.include_router(suppliers_router)
app.include_router(forecasting_router)
app.include_router(orders_api_router)
app.include_router(mock_forecast_router)
app.include_router(mock_optimization_router)
app.include_router(mock_memory_router)
if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1":
    isolated_dependencies = [Depends(require_isolated_e2e_key)]
    app.include_router(feasibility_assessment_router, dependencies=isolated_dependencies)
    app.include_router(feasibility_supplier_event_router, dependencies=isolated_dependencies)

app.dependency_overrides[get_assessment_history] = lambda: AuthoritativeAssessmentHistoryReader()
app.dependency_overrides[get_impact_reader] = lambda: AuthoritativeImpactReader()


@app.on_event("startup")
def on_startup() -> None:
    try:
        from app.context.channels.manager import get_channel_manager
        get_channel_manager().start_configured_workers()
    except Exception as exc:
        import logging
        logging.getLogger("moumantai.startup").warning("Channel workers startup skipped: %s", exc)


@app.on_event("shutdown")
def on_shutdown() -> None:
    try:
        from app.context.channels.manager import get_channel_manager
        get_channel_manager().stop_all_workers()
    except Exception as exc:
        import logging
        logging.getLogger("moumantai.shutdown").warning("Channel workers shutdown error: %s", exc)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    correlation_id = exc.correlation_id or request.headers.get("X-Correlation-ID") or f"corr_{uuid4().hex}"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "correlation_id": correlation_id,
            "details": exc.details,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    correlation_id = request.headers.get("X-Correlation-ID") or f"corr_{uuid4().hex}"
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        500: "INTERNAL_SERVER_ERROR",
    }
    code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
    if isinstance(exc.detail, dict):
        message = exc.detail.get("message", "HTTP error")
        details = exc.detail
    else:
        message = str(exc.detail)
        details = {"detail": exc.detail}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "message": message,
            "correlation_id": correlation_id,
            "details": details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    correlation_id = request.headers.get("X-Correlation-ID") or f"corr_{uuid4().hex}"
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "correlation_id": correlation_id,
            # Pydantic ctx can contain non-JSON ValueError objects. Input may
            # contain secrets/PII; return locations and explanations only.
            "details": {"errors": [
                {"type": error["type"], "loc": error["loc"], "msg": error["msg"]}
                for error in exc.errors()
            ]},
        },
    )


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="moumantai-api", version=app.version)
