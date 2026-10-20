from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Generator
from uuid import uuid4

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import SessionLocal


ACTOR_ROLES = {
    "user_owner_01": "OWNER",
    "user_manager_01": "MANAGER",
    "user_staff_01": "STAFF",
}


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str
    actor_id: str
    actor_role: str
    correlation_id: str


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_request_context(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> RequestContext:
    if not x_tenant_id or not x_actor_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID and X-Actor-ID are required")
    return RequestContext(
        tenant_id=x_tenant_id,
        actor_id=x_actor_id,
        actor_role=ACTOR_ROLES.get(x_actor_id, "STAFF"),
        correlation_id=x_correlation_id or f"corr_{uuid4().hex}",
    )
