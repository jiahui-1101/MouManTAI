"""Mock Resource Inventory and Concurrent Reservation Lock Primitive.

Per REQUIREMENTS_SYSTEM.md §2.2 (Invariant 8) and PERSON_5 §5 (SAF-4):
"A mock resource reservation must enforce no over-allocation under concurrent requests;
P3 action adapter obtains lock/transaction, P2 query evaluator stays read-only."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import threading
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .errors import DomainError, InsufficientResourceError
from .models import AuditEventRecord, ResourceReservationRecord, ResourceStockRecord

_RESERVATION_LOCK = threading.RLock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _format_decimal(d: Decimal) -> str:
    if d == d.to_integral():
        return str(int(d))
    s = str(d)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


@dataclass(frozen=True)
class ResourceSnapshot:
    resource_id: str
    total_quantity: Decimal
    reserved_quantity: Decimal
    available_quantity: Decimal
    unit: str
    snapshot_version: int
    updated_at: datetime

    @property
    def available(self) -> Decimal:
        return self.available_quantity

    def __getitem__(self, item: str) -> Any:
        if item in ("available", "available_quantity"):
            return self.available_quantity
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "total_quantity": str(self.total_quantity),
            "reserved_quantity": str(self.reserved_quantity),
            "available_quantity": str(self.available_quantity),
            "available": str(self.available_quantity),
            "unit": self.unit,
            "snapshot_version": self.snapshot_version,
            "updated_at": self.updated_at.isoformat(),
        }


class ResourceSnapshotList(list[ResourceSnapshot]):
    """List of ResourceSnapshots with convenient single-item properties and key-based lookup."""

    @property
    def resource_id(self) -> str:
        return self[0].resource_id if self else ""

    @property
    def total_quantity(self) -> Decimal:
        return self[0].total_quantity if self else Decimal("0")

    @property
    def reserved_quantity(self) -> Decimal:
        return self[0].reserved_quantity if self else Decimal("0")

    @property
    def available_quantity(self) -> Decimal:
        return self[0].available_quantity if self else Decimal("0")

    @property
    def available(self) -> Decimal:
        return self[0].available if self else Decimal("0")

    @property
    def unit(self) -> str:
        return self[0].unit if self else ""

    @property
    def snapshot_version(self) -> int:
        return self[0].snapshot_version if self else 1

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            for s in self:
                if s.resource_id == item:
                    return s
            raise KeyError(f"Resource '{item}' not found in snapshot list")
        return super().__getitem__(item)


# -----------------------------------------------------------------------------
# 1. Read-Only Query for P2 (get_resource_snapshot, get_available_stock)
# -----------------------------------------------------------------------------

def get_resource_snapshot(
    session: Session,
    tenant_id: str,
    resource_ids: list[str] | str | None = None,
) -> ResourceSnapshotList:
    """Pure read-only query helper for P2 Feasibility evaluator.

    Computes available = total_quantity - reserved_quantity using Decimal arithmetic
    and returns current snapshot_version without mutating rows or acquiring write locks.
    """
    stmt = select(ResourceStockRecord).where(ResourceStockRecord.tenant_id == tenant_id)
    if isinstance(resource_ids, str):
        stmt = stmt.where(ResourceStockRecord.resource_id == resource_ids)
    elif resource_ids:
        stmt = stmt.where(ResourceStockRecord.resource_id.in_(resource_ids))

    stmt = stmt.order_by(ResourceStockRecord.resource_id)
    records = session.scalars(stmt).all()

    snapshots = ResourceSnapshotList()
    for r in records:
        total = Decimal(str(r.total_quantity))
        reserved = Decimal(str(r.reserved_quantity))
        available = total - reserved
        snapshots.append(
            ResourceSnapshot(
                resource_id=r.resource_id,
                total_quantity=total,
                reserved_quantity=reserved,
                available_quantity=available,
                unit=r.unit,
                snapshot_version=r.snapshot_version,
                updated_at=_aware(r.updated_at),
            )
        )
    return snapshots


def get_available_stock(session: Session, tenant_id: str, resource_id: str) -> Decimal:
    """Convenience helper returning available stock quantity for a single resource."""
    snapshots = get_resource_snapshot(session, tenant_id, resource_id)
    if not snapshots:
        return Decimal("0")
    return snapshots[0].available


# -----------------------------------------------------------------------------
# 2. Seed Mock Resource Inventory
# -----------------------------------------------------------------------------

def seed_resource_stock(
    session: Session,
    tenant_id: str,
    resource_id: str,
    total_quantity: Decimal | str | int,
    unit: str,
    reserved_quantity: Decimal | str | int = Decimal("0"),
    snapshot_version: int = 1,
    commit: bool = True,
) -> ResourceStockRecord:
    """Create or update mock resource inventory stock."""
    now = _now()
    total_dec = Decimal(str(total_quantity))
    reserved_dec = Decimal(str(reserved_quantity))

    stock = session.scalar(
        select(ResourceStockRecord).where(
            ResourceStockRecord.tenant_id == tenant_id,
            ResourceStockRecord.resource_id == resource_id,
        )
    )
    if stock is None:
        stock = ResourceStockRecord(
            tenant_id=tenant_id,
            resource_id=resource_id,
            total_quantity=total_dec,
            reserved_quantity=reserved_dec,
            unit=unit,
            snapshot_version=snapshot_version,
            updated_at=now,
        )
        session.add(stock)
    else:
        stock.total_quantity = total_dec
        stock.reserved_quantity = reserved_dec
        stock.unit = unit
        stock.snapshot_version = snapshot_version
        stock.updated_at = now

    if commit:
        session.commit()
        session.refresh(stock)
    else:
        session.flush()
    return stock


# -----------------------------------------------------------------------------
# 3. Transactional Locking Reservation for P3 (reserve_resource)
# -----------------------------------------------------------------------------

def reserve_resource(
    session: Session,
    *,
    tenant_id: str,
    commitment_id: str,
    plan_id: str,
    action_id: str,
    idempotency_key: str,
    resource_id: str,
    quantity: Decimal | str | int | float,
    actor_id: str = "system",
    commit: bool = True,
) -> ResourceReservationRecord:
    """Transactional locking reservation primitive for P3 Recovery action adapter.

    Enforces SAF-4 & Invariant 8:
    1. Idempotency on (tenant_id, idempotency_key): returns existing reservation without double-deducting.
    2. Atomic conditional stock deduction:
       SET reserved_quantity = reserved_quantity + :qty, snapshot_version = snapshot_version + 1
       WHERE tenant_id = :t AND resource_id = :r AND (total_quantity - reserved_quantity) >= :qty.
    3. If available < quantity: raises InsufficientResourceError (HTTP 409 Conflict) and rolls back cleanly.
    4. Increments snapshot_version so concurrent plans pinned to older snapshot detect drift.
    5. Records an immutable audit log entry.
    """
    qty = Decimal(str(quantity))
    if qty <= Decimal("0"):
        raise DomainError(
            "INVALID_QUANTITY",
            f"Reservation quantity must be strictly positive, got {quantity}",
            status_code=400,
        )

    # Fast-path idempotency check: check if reservation already exists
    existing = session.scalar(
        select(ResourceReservationRecord).where(
            ResourceReservationRecord.tenant_id == tenant_id,
            ResourceReservationRecord.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing

    now = _now()

    with _RESERVATION_LOCK:
        # Re-check idempotency under lock in case of concurrent first-call
        existing = session.scalar(
            select(ResourceReservationRecord).where(
                ResourceReservationRecord.tenant_id == tenant_id,
                ResourceReservationRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing

        # Execute atomic conditional update enforcing no over-allocation
        stmt = (
            update(ResourceStockRecord)
            .where(
                ResourceStockRecord.tenant_id == tenant_id,
                ResourceStockRecord.resource_id == resource_id,
                (ResourceStockRecord.total_quantity - ResourceStockRecord.reserved_quantity) >= qty,
            )
            .values(
                reserved_quantity=ResourceStockRecord.reserved_quantity + qty,
                snapshot_version=ResourceStockRecord.snapshot_version + 1,
                updated_at=now,
            )
        )
        result = session.execute(stmt)

        if result.rowcount == 0:
            # Atomic update failed: either resource does not exist or available < quantity
            stock = session.scalar(
                select(ResourceStockRecord).where(
                    ResourceStockRecord.tenant_id == tenant_id,
                    ResourceStockRecord.resource_id == resource_id,
                )
            )
            if stock is None:
                raise DomainError(
                    "RESOURCE_NOT_FOUND",
                    f"Resource '{resource_id}' does not exist for tenant '{tenant_id}'",
                    status_code=404,
                )

            avail = Decimal(str(stock.total_quantity)) - Decimal(str(stock.reserved_quantity))
            session.rollback()
            raise InsufficientResourceError(
                f"Insufficient stock for resource '{resource_id}': available {_format_decimal(avail)} < requested {_format_decimal(qty)}",
                details={
                    "resource_id": resource_id,
                    "total_quantity": _format_decimal(Decimal(str(stock.total_quantity))),
                    "reserved_quantity": _format_decimal(Decimal(str(stock.reserved_quantity))),
                    "available_quantity": _format_decimal(avail),
                    "requested_quantity": _format_decimal(qty),
                    "unit": stock.unit,
                },
            )

        # Create active reservation record
        reservation = ResourceReservationRecord(
            reservation_id=_id("res"),
            tenant_id=tenant_id,
            commitment_id=commitment_id,
            plan_id=plan_id,
            action_id=action_id,
            idempotency_key=idempotency_key,
            resource_id=resource_id,
            quantity=qty,
            status="ACTIVE",
            created_at=now,
        )
        session.add(reservation)

        # Record immutable audit event
        audit = AuditEventRecord(
            audit_id=_id("aud"),
            tenant_id=tenant_id,
            commitment_id=commitment_id,
            event_type="resource.reserved",
            actor_id=actor_id,
            actor_role="MANAGER",
            dimension="recovery",
            previous_state=None,
            new_state={
                "reservation_id": reservation.reservation_id,
                "resource_id": resource_id,
                "quantity": str(qty),
                "plan_id": plan_id,
                "action_id": action_id,
                "idempotency_key": idempotency_key,
            },
            evidence_refs=[f"ev_res_{reservation.reservation_id}"],
            reason=f"Resource '{resource_id}' reserved for plan '{plan_id}' action '{action_id}' (qty: {qty})",
            correlation_id=f"corr_{uuid4().hex[:12]}",
            causation_id=plan_id,
            occurred_at=now,
        )
        session.add(audit)

        if commit:
            session.commit()
            session.refresh(reservation)
        else:
            session.flush()

        return reservation


# -----------------------------------------------------------------------------
# 4. Release and Consume Operations
# -----------------------------------------------------------------------------

def release_reservation(
    session: Session,
    *,
    tenant_id: str,
    reservation_id: str,
    actor_id: str = "system",
    reason: str = "Reservation released",
    commit: bool = True,
) -> ResourceReservationRecord:
    """Release an active resource reservation, restoring available inventory."""
    now = _now()
    with _RESERVATION_LOCK:
        reservation = session.scalar(
            select(ResourceReservationRecord).where(
                ResourceReservationRecord.tenant_id == tenant_id,
                ResourceReservationRecord.reservation_id == reservation_id,
            )
        )
        if reservation is None:
            raise DomainError("RESERVATION_NOT_FOUND", f"Reservation '{reservation_id}' not found", status_code=404)

        if reservation.status != "ACTIVE":
            raise DomainError(
                "INVALID_RESERVATION_STATE",
                f"Cannot release reservation with status '{reservation.status}'; must be ACTIVE",
                status_code=409,
            )

        # Restore reserved quantity on stock
        qty = Decimal(str(reservation.quantity))
        session.execute(
            update(ResourceStockRecord)
            .where(
                ResourceStockRecord.tenant_id == tenant_id,
                ResourceStockRecord.resource_id == reservation.resource_id,
            )
            .values(
                reserved_quantity=ResourceStockRecord.reserved_quantity - qty,
                snapshot_version=ResourceStockRecord.snapshot_version + 1,
                updated_at=now,
            )
        )
        reservation.status = "RELEASED"

        audit = AuditEventRecord(
            audit_id=_id("aud"),
            tenant_id=tenant_id,
            commitment_id=reservation.commitment_id,
            event_type="resource.released",
            actor_id=actor_id,
            actor_role="MANAGER",
            dimension="recovery",
            previous_state={"status": "ACTIVE"},
            new_state={"status": "RELEASED", "reservation_id": reservation_id},
            evidence_refs=[f"ev_rel_{reservation_id}"],
            reason=reason,
            correlation_id=f"corr_{uuid4().hex[:12]}",
            causation_id=reservation.plan_id,
            occurred_at=now,
        )
        session.add(audit)

        if commit:
            session.commit()
            session.refresh(reservation)
        else:
            session.flush()

        return reservation


def consume_reservation(
    session: Session,
    *,
    tenant_id: str,
    reservation_id: str,
    actor_id: str = "system",
    reason: str = "Reservation consumed upon action execution",
    commit: bool = True,
) -> ResourceReservationRecord:
    """Consume an active reservation, decrementing total_quantity upon actual execution."""
    now = _now()
    with _RESERVATION_LOCK:
        reservation = session.scalar(
            select(ResourceReservationRecord).where(
                ResourceReservationRecord.tenant_id == tenant_id,
                ResourceReservationRecord.reservation_id == reservation_id,
            )
        )
        if reservation is None:
            raise DomainError("RESERVATION_NOT_FOUND", f"Reservation '{reservation_id}' not found", status_code=404)

        if reservation.status != "ACTIVE":
            raise DomainError(
                "INVALID_RESERVATION_STATE",
                f"Cannot consume reservation with status '{reservation.status}'; must be ACTIVE",
                status_code=409,
            )

        qty = Decimal(str(reservation.quantity))
        session.execute(
            update(ResourceStockRecord)
            .where(
                ResourceStockRecord.tenant_id == tenant_id,
                ResourceStockRecord.resource_id == reservation.resource_id,
            )
            .values(
                total_quantity=ResourceStockRecord.total_quantity - qty,
                reserved_quantity=ResourceStockRecord.reserved_quantity - qty,
                snapshot_version=ResourceStockRecord.snapshot_version + 1,
                updated_at=now,
            )
        )
        reservation.status = "CONSUMED"

        audit = AuditEventRecord(
            audit_id=_id("aud"),
            tenant_id=tenant_id,
            commitment_id=reservation.commitment_id,
            event_type="resource.consumed",
            actor_id=actor_id,
            actor_role="MANAGER",
            dimension="recovery",
            previous_state={"status": "ACTIVE"},
            new_state={"status": "CONSUMED", "reservation_id": reservation_id},
            evidence_refs=[f"ev_con_{reservation_id}"],
            reason=reason,
            correlation_id=f"corr_{uuid4().hex[:12]}",
            causation_id=reservation.plan_id,
            occurred_at=now,
        )
        session.add(audit)

        if commit:
            session.commit()
            session.refresh(reservation)
        else:
            session.flush()

        return reservation
