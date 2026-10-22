"""Replaceable development dependencies. Never interpret a client header as auth."""

import os
from functools import lru_cache
from typing import Annotated

from fastapi import Header, HTTPException
from pydantic import ValidationError

from .dev_database import create_p1_engine
from .ingestion_schemas import DevelopmentContext
from .postgres_repository import PostgresMessageRepository
from .repository import MessageRepository, PersistenceUnavailable
from app.core.dependencies import ACTOR_ROLES


def development_context(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
) -> DevelopmentContext:
    """Resolve tenant context from trusted X-Tenant-ID header when present,
    falling back to server environment configuration in local test/dev workflows."""
    tenant_id = x_tenant_id or os.environ.get("P1_DEV_TENANT_ID", "synthetic_tenant_a")
    try:
        return DevelopmentContext(tenant_id=tenant_id)
    except ValidationError:
        raise PersistenceUnavailable("Server development tenant is not configured correctly") from None


def resolve_actor(
    x_actor_id: str | None = None,
    x_actor_role: str | None = None,
) -> tuple[str, str]:
    """Resolve actor identity using the shared ACTOR_ROLES registry.

    Returns (actor_id, actor_role). The caller-supplied X-Actor-Role header
    is never trusted to grant privileged roles (OWNER/MANAGER); roles for registered
    actors are always resolved server-side from ACTOR_ROLES.
    """
    actor_id = x_actor_id or "user_staff_01"
    if actor_id in ACTOR_ROLES:
        actor_role = ACTOR_ROLES[actor_id]
    else:
        # Untrusted external actor cannot self-assign OWNER or MANAGER
        if x_actor_role in {"OWNER", "MANAGER"}:
            actor_role = "STAFF"
        else:
            actor_role = x_actor_role or "STAFF"
    return actor_id, actor_role


@lru_cache(maxsize=1)
def local_repository() -> MessageRepository:
    return PostgresMessageRepository(create_p1_engine())
