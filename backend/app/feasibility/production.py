"""Provisional P2-local production inputs, never persistence or Core state.

Fixed bookings are evaluated as supplied. A failed booking is not proof that
no alternative schedule exists. P3 may propose a new booking using the same
engine. P5 must supply authenticated, complete operational evidence.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .models import FrozenModel, OperationalSnapshot, _ensure_unique, _utc


NonNegativeMinutes = Annotated[Decimal, Field(ge=0)]
PositiveMinutes = Annotated[Decimal, Field(gt=0)]
Refs = Annotated[tuple[str, ...], Field(min_length=1)]


class ProductionValue(FrozenModel):
    @field_validator('*', mode='before')
    @classmethod
    def exact_minutes(cls, value, info):
        if info.field_name in {'minutes_per_unit', 'setup_minutes', 'delivery_lead_minutes'} and isinstance(value, float):
            raise ValueError('processing times must use exact decimals, not floats')
        return value

    @field_validator('source_refs', 'evidence_refs', 'resource_ids', check_fields=False)
    @classmethod
    def nonblank_refs(cls, values):
        if any(not value.strip() for value in values) or len(values) != len(set(values)):
            raise ValueError('references must be nonempty and unique')
        return values


class ProductionSource(ProductionValue):
    source_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    kind: Literal['resources', 'processes', 'jobs', 'plans']
    source_ref: str = Field(min_length=1)
    observed_at: datetime
    valid_through: datetime
    evidence_refs: Refs

    @model_validator(mode='after')
    def time_bounds(self):
        if _utc(self.valid_through) < _utc(self.observed_at):
            raise ValueError('source expiry precedes observation')
        return self


class ProductionResource(ProductionValue):
    resource_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    source_refs: Refs
    # Each ID means one exclusive resource, never an inferred number of lanes.


class ProductionProcess(ProductionValue):
    process_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    resource_ids: Refs
    minutes_per_unit: PositiveMinutes | None
    setup_minutes: NonNegativeMinutes
    delivery_lead_minutes: NonNegativeMinutes | None
    source_refs: Refs


class ProductionPlan(ProductionValue):
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    commitment_version: int = Field(ge=1)
    line_id: str = Field(min_length=1)
    start_at: datetime
    dispatch_cutoff_at: datetime
    source_refs: Refs
    preferred_finish_at: datetime | None = None


class ProductionJob(ProductionValue):
    job_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    resource_ids: Refs
    start_at: datetime
    end_at: datetime
    source_refs: Refs

    @model_validator(mode='after')
    def positive_interval(self):
        if _utc(self.end_at) <= _utc(self.start_at):
            raise ValueError('job must have positive duration')
        return self


class ProductionData(ProductionValue):
    tenant_id: str = Field(min_length=1)
    sources: tuple[ProductionSource, ...]
    resources: tuple[ProductionResource, ...]
    processes: tuple[ProductionProcess, ...]
    plans: tuple[ProductionPlan, ...]
    # None means missing; () is an evidenced, complete, empty ledger.
    jobs: tuple[ProductionJob, ...] | None
    jobs_covered_from: datetime
    jobs_covered_through: datetime

    @model_validator(mode='after')
    def structure(self):
        for rows, key in ((self.sources, 'source_id'), (self.resources, 'resource_id'),
                          (self.processes, 'process_id'), (self.jobs or (), 'job_id')):
            _ensure_unique(rows, key, key)
        if len({p.sku_id for p in self.processes}) != len(self.processes):
            raise ValueError('ambiguous production process for SKU')
        if len({(p.commitment_id, p.line_id) for p in self.plans}) != len(self.plans):
            raise ValueError('duplicate production plan')
        if _utc(self.jobs_covered_through) <= _utc(self.jobs_covered_from):
            raise ValueError('job ledger horizon must be positive')
        sources = {s.source_id: s for s in self.sources}
        for rows, kind in ((self.resources, 'resources'), (self.processes, 'processes'),
                           (self.plans, 'plans'), (self.jobs or (), 'jobs')):
            for row in rows:
                if row.tenant_id != self.tenant_id:
                    raise ValueError('production tenant mismatch')
                for ref in row.source_refs:
                    if ref in sources and sources[ref].kind != kind:
                        raise ValueError('production source kind mismatch')
        if any(s.tenant_id != self.tenant_id for s in self.sources):
            raise ValueError('production source tenant mismatch')
        return self


class EvaluationSnapshot(ProductionValue):
    operational: OperationalSnapshot
    production: ProductionData | None = None
    as_of: datetime
    current_snapshot_version: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def boundaries(self):
        if _utc(self.as_of) < _utc(self.operational.captured_at):
            raise ValueError('assessment time precedes snapshot')
        if self.production:
            if self.production.tenant_id != self.operational.tenant_id:
                raise ValueError('production snapshot tenant mismatch')
            if any(_utc(s.observed_at) > _utc(self.operational.captured_at) for s in self.production.sources):
                raise ValueError('production source observation after capture')
        return self


class ProposedChanges(ProductionValue):
    """Query only; no arbitrary supply insertion, job deletion or lifecycle PATCH."""

    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    expected_commitment_version: int = Field(ge=1)
    expected_snapshot_version: int = Field(ge=1)
    quantity: Annotated[Decimal, Field(gt=0)] | None = None
    deadline: datetime | None = None
    production_start_at: datetime | None = None
    evidence_refs: Refs

    @model_validator(mode='after')
    def has_change(self):
        if self.quantity is None and self.deadline is None and self.production_start_at is None:
            raise ValueError('proposal requires an explicit change')
        return self
