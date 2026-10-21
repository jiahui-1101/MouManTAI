"""Replaceable development dependencies. Never interpret a client header as auth."""

import os
from functools import lru_cache

from pydantic import ValidationError

from .dev_database import create_p1_engine
from .ingestion_schemas import DevelopmentContext
from .postgres_repository import PostgresMessageRepository
from .repository import MessageRepository, PersistenceUnavailable


def development_context() -> DevelopmentContext:
    try:
        return DevelopmentContext(tenant_id=os.environ.get("P1_DEV_TENANT_ID", "synthetic_tenant_a"))
    except ValidationError:
        raise PersistenceUnavailable("Server development tenant is not configured correctly") from None


@lru_cache(maxsize=1)
def local_repository() -> MessageRepository:
    return PostgresMessageRepository(create_p1_engine())
