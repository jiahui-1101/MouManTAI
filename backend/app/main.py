from __future__ import annotations

import os
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi import Request
from fastapi.responses import JSONResponse

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import DomainError
from app.core.feasibility_adapters import (
    AuthoritativeAssessmentHistoryReader,
    AuthoritativeImpactReader,
)
from app.core.router import router as core_router
from app.feasibility.api_dependencies import (
    get_assessment_history,
    get_impact_reader,
)
from app.feasibility.router import feasibility_read_router


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


app = FastAPI(title="MouManTAI API", version="0.1.0")

origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
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
app.include_router(feasibility_read_router)

app.dependency_overrides[get_assessment_history] = lambda: AuthoritativeAssessmentHistoryReader()
app.dependency_overrides[get_impact_reader] = lambda: AuthoritativeImpactReader()


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
            "details": {"errors": exc.errors()},
        },
    )


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="moumantai-api", version=app.version)
