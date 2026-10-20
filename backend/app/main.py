from __future__ import annotations

import os
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.errors import DomainError
from app.core.router import router as core_router


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


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="moumantai-api", version=app.version)
