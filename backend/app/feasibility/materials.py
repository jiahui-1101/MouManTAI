"""P2-local material calculation values; not shared feasibility assessments."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from backend.app.feasibility.models import FrozenModel, SnapshotIssue


class MaterialRequirement(FrozenModel):
    commitment_id: str
    commitment_version: int
    line_id: str
    sku_id: str
    quantity: Decimal
    unit: str
    needed_by: datetime
    warehouse_id: str | None
    paths: tuple[tuple[str, ...], ...]
    component_paths: tuple[tuple[str, ...], ...]
    evidence_refs: tuple[str, ...]


class BomExpansion(FrozenModel):
    tenant_id: str
    snapshot_id: str
    snapshot_version: int
    status: Literal['COMPLETE', 'UNKNOWN']
    requirements: tuple[MaterialRequirement, ...] = ()
    assumptions: tuple[str, ...] = ()
    issues: tuple[SnapshotIssue, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class SupplyAllocation(FrozenModel):
    supply_id: str
    kind: Literal['RESERVATION', 'LOT', 'RECEIPT']
    quantity: Decimal
    reservation_id: str | None = None
    evidence_refs: tuple[str, ...]


class MaterialAvailability(FrozenModel):
    commitment_id: str
    commitment_version: int
    line_id: str
    sku_id: str
    unit: str
    needed_by: datetime
    warehouse_id: str | None
    code: Literal['MATERIAL_COVERED', 'MATERIAL_SHORTAGE']
    required: Decimal
    usable: Decimal  # allocated unreserved lots, excluding owned reservation
    reserved: Decimal  # allocated owned reservation only
    confirmed_incoming: Decimal  # allocated confirmed receipts only
    shortage: Decimal
    allocations: tuple[SupplyAllocation, ...]
    evidence_refs: tuple[str, ...]


class MaterialATP(FrozenModel):
    tenant_id: str
    snapshot_id: str
    snapshot_version: int
    as_of: datetime
    status: Literal['COVERED', 'SHORTAGE', 'UNKNOWN']
    materials: tuple[MaterialAvailability, ...] = ()
    assumptions: tuple[str, ...] = ()
    issues: tuple[SnapshotIssue, ...] = ()
    evidence_refs: tuple[str, ...] = ()
