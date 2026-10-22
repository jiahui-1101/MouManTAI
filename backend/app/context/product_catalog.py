"""Trusted server-side catalog configuration, separate from unverified noun hints."""
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .deterministic_extraction import ProductAlias, PROVISIONAL_PRODUCTS
from .repository import PersistenceUnavailable


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    tenant_id: str = Field(min_length=1, max_length=100)
    sku: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=30)
    aliases: list[str] = Field(min_length=1, max_length=100)
    source_ref: str = Field(min_length=1, max_length=300)


def load_product_catalog() -> tuple[ProductAlias, ...]:
    path = os.environ.get('P1_PRODUCT_CATALOG_PATH')
    if not path:
        if os.environ.get('ENVIRONMENT', '').lower() == 'production':
            raise PersistenceUnavailable('Configure a trusted P1 product catalog before production use')
        return PROVISIONAL_PRODUCTS
    try:
        data = Path(path).read_bytes()
        if len(data) > 1_048_576:
            raise ValueError('Catalog too large')
        rows = json.loads(data)
        if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
            raise ValueError('Invalid catalog')
        entries = [CatalogEntry.model_validate(row) for row in rows]
        if any(not alias.strip() or len(alias) > 150 for entry in entries for alias in entry.aliases):
            raise ValueError('Invalid alias')
        return tuple(ProductAlias(e.tenant_id, e.sku, tuple(e.aliases), e.unit) for e in entries)
    except Exception:
        # Do not leak private paths, credentials, or untrusted file contents.
        raise PersistenceUnavailable('Configured P1 product catalog is unavailable or invalid') from None
