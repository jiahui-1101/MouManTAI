"""Read supported P5 fields without fabricating a full EvaluationSnapshot."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.reservations import get_resource_snapshot
from app.core.schemas import Commitment

from .models import FrozenModel
from .quantities import subtract


UNAVAILABLE_FIELDS = ('sku_catalog', 'unit_conversions', 'bom', 'inventory_lots', 'reservation_ownership',
                      'confirmed_deliveries', 'supplier_eta_evidence', 'competing_commitments',
                      'production_resources', 'production_processes', 'capacity_calendars',
                      'production_plans', 'job_ledger', 'logistics_cutoff', 'source_provenance',
                      'source_freshness_bounds', 'atomic_read_token')


class ResourceQuantity(FrozenModel):
    resource_id: str = Field(min_length=1)
    total_quantity: Decimal = Field(ge=0)
    reserved_quantity: Decimal = Field(ge=0)
    available_quantity: Decimal = Field(ge=0)
    unit: str = Field(min_length=1)
    resource_version: int = Field(ge=1)
    updated_at: datetime
    valid_through: None = None
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode='after')
    def consistency(self):
        if self.reserved_quantity > self.total_quantity or self.available_quantity != subtract(
                self.total_quantity, self.reserved_quantity):
            raise ValueError('inconsistent resource quantities')
        return self


class ResourceReadiness(FrozenModel):
    tenant_id: str
    commitment_id: str
    commitment_version: int
    status: Literal['INCOMPLETE', 'UNAVAILABLE']
    resources: tuple[ResourceQuantity, ...]
    missing_resource_ids: tuple[str, ...]
    unavailable_fields: tuple[str, ...] = UNAVAILABLE_FIELDS
    source_api: Literal['app.core.reservations.get_resource_snapshot'] = 'app.core.reservations.get_resource_snapshot'


def read_resource_summary(db: Session, context: RequestContext, commitment: Commitment, *,
                          resource_ids: tuple[str, ...]) -> ResourceReadiness:
    """Context must be server-resolved by caller; matching strings are not auth.

    P5's API supplies no tenant on individual rows, evidence refs, source validity,
    global version or reservation owners. Retain the query scope and report the
    missing fields, never convert totals into lots or freely available reserved stock.
    """
    if context.tenant_id != commitment.tenant_id:
        raise ValueError('resource query tenant mismatch')
    if not resource_ids or any(not r.strip() for r in resource_ids) or len(set(resource_ids)) != len(resource_ids):
        raise ValueError('explicit unique nonblank resource IDs required')
    # Query only under no_autoflush: a read adapter must not flush unrelated work.
    with db.no_autoflush:
        source_rows = get_resource_snapshot(db, context.tenant_id, list(resource_ids))
    rows = tuple(ResourceQuantity(resource_id=r.resource_id, total_quantity=r.total_quantity,
                                  reserved_quantity=r.reserved_quantity, available_quantity=r.available_quantity,
                                  unit=r.unit, resource_version=r.snapshot_version, updated_at=r.updated_at)
                 for r in source_rows)
    found = {r.resource_id for r in rows}
    if not found.issubset(resource_ids) or len(found) != len(rows):
        raise ValueError('resource query returned unexpected or duplicate resources')
    return ResourceReadiness(tenant_id=context.tenant_id, commitment_id=commitment.commitment_id,
                             commitment_version=commitment.commitment_version,
                             status='INCOMPLETE' if rows else 'UNAVAILABLE', resources=rows,
                             missing_resource_ids=tuple(sorted(set(resource_ids) - found)))
