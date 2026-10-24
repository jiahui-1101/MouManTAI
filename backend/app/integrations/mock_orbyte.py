"""Persistent, transaction-safe Mock Orbyte resources and reservation receipts.

This adapter has no network path. All source records must be explicit synthetic
fixtures. A local PostgreSQL row lock serializes reservations for one tenant.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.feasibility.production import EvaluationSnapshot
from app.integrations.business_ports import ReservationCommand, ReservationReceipt
from app.orders.models import MockOrbyteReservationRecord, MockOrbyteStateRecord


class MockOrbyteAdapter:
    def __init__(self, db: Session) -> None:
        self.db = db

    def read_state(self, tenant_id: str, *, lock: bool = False) -> tuple[MockOrbyteStateRecord, EvaluationSnapshot]:
        statement = select(MockOrbyteStateRecord).where(MockOrbyteStateRecord.tenant_id == tenant_id)
        row = self.db.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise DomainError("MOCK_RESOURCE_UNAVAILABLE", "Mock Orbyte data is not configured", status_code=503)
        try:
            snapshot = EvaluationSnapshot.model_validate(row.snapshot_payload)
        except ValueError as exc:
            raise DomainError("MOCK_RESOURCE_CORRUPT", "Mock Orbyte snapshot is invalid", status_code=503) from exc
        if (snapshot.operational.tenant_id != tenant_id
                or snapshot.operational.snapshot_version != row.snapshot_version
                or snapshot.current_snapshot_version != row.snapshot_version
                or not snapshot.operational.sources
                or any(not (source.source_ref or "").startswith("synthetic://")
                       for source in snapshot.operational.sources)
                or snapshot.production is None
                or any(not source.source_ref.startswith("synthetic://")
                       for source in snapshot.production.sources)):
            raise DomainError("MOCK_RESOURCE_AUTHORITY_INVALID", "Only tenant-bound synthetic Mock sources are allowed",
                              status_code=503)
        return row, snapshot

    def read_reservation_status(self, tenant_id: str, operation_id: str) -> ReservationReceipt:
        row = self.db.get(MockOrbyteReservationRecord, operation_id)
        if row is None or row.tenant_id != tenant_id:
            raise DomainError("MOCK_RESERVATION_NOT_FOUND", "Mock reservation not found", status_code=404)
        return ReservationReceipt.model_validate(row.receipt)

    def reserve_resources(self, command: ReservationCommand, *,
                          projected: EvaluationSnapshot, assessment,
                          actor_id: str, approval_reason: str) -> ReservationReceipt:
        state, current = self.read_state(command.tenant_id, lock=True)
        if (state.snapshot_version != command.snapshot_version
                or current.operational.snapshot_id != command.snapshot_id
                or projected.operational.snapshot_version != command.snapshot_version
                or assessment.assessment_id != command.assessment_id
                or assessment.snapshot_version != command.snapshot_version):
            raise DomainError("STALE_RESOURCE_VERSION", "Mock resource snapshot changed", status_code=409)
        existing = self.db.scalar(select(MockOrbyteReservationRecord).where(
            MockOrbyteReservationRecord.tenant_id == command.tenant_id,
            MockOrbyteReservationRecord.idempotency_key == command.idempotency_key,
        ))
        if existing is not None:
            if (existing.order_request_id != command.order_request_id
                    or existing.request_version != command.request_version
                    or existing.terms_hash != command.terms.terms_hash):
                raise DomainError("IDEMPOTENCY_CONFLICT", "Key already belongs to another command", status_code=409)
            return ReservationReceipt.model_validate(existing.receipt)
        prior_confirmed = self.db.scalar(select(MockOrbyteReservationRecord).where(
            MockOrbyteReservationRecord.tenant_id == command.tenant_id,
            MockOrbyteReservationRecord.order_request_id == command.order_request_id,
            MockOrbyteReservationRecord.status == "CONFIRMED",
        ))
        if prior_confirmed is not None:
            raise DomainError("ORDER_ALREADY_RESERVED", "Order already has a Mock reservation", status_code=409)

        if state.next_outcome == "REJECT":
            operation_id = f"mop_{uuid4().hex}"
            now = datetime.now(UTC)
            receipt = ReservationReceipt(
                tenant_id=command.tenant_id, order_request_id=command.order_request_id,
                operation_id=operation_id, idempotency_key=command.idempotency_key,
                request_version=command.request_version, terms_hash=command.terms.terms_hash,
                terms_revision=command.terms.terms_revision, snapshot_id=command.snapshot_id,
                snapshot_version=command.snapshot_version, assessment_id=command.assessment_id,
                status="FAILED", mode="MOCK", checked_at=now, reservation_ids=(),
                evidence_refs=(f"mock-orbyte:rejected:{operation_id}",),
            )
            state.next_outcome = "NORMAL"
            self.db.add(MockOrbyteReservationRecord(
                operation_id=operation_id, tenant_id=command.tenant_id,
                order_request_id=command.order_request_id, idempotency_key=command.idempotency_key,
                request_version=command.request_version, terms_hash=command.terms.terms_hash,
                snapshot_version=command.snapshot_version, assessment_id=command.assessment_id,
                actor_id=actor_id, approval_reason=approval_reason,
                status="FAILED", receipt=receipt.model_dump(mode="json"), created_at=now,
            ))
            self.db.flush()
            return receipt
        if state.next_outcome == "UNKNOWN":
            operation_id = f"mop_{uuid4().hex}"
            now = datetime.now(UTC)
            receipt = ReservationReceipt(
                tenant_id=command.tenant_id, order_request_id=command.order_request_id,
                operation_id=operation_id, idempotency_key=command.idempotency_key,
                request_version=command.request_version, terms_hash=command.terms.terms_hash,
                terms_revision=command.terms.terms_revision, snapshot_id=command.snapshot_id,
                snapshot_version=command.snapshot_version, assessment_id=command.assessment_id,
                status="UNKNOWN", mode="MOCK", checked_at=now,
                reservation_ids=(), evidence_refs=(f"mock-orbyte:unknown:{operation_id}",),
            )
            state.next_outcome = "NORMAL"
            self.db.add(MockOrbyteReservationRecord(
                operation_id=operation_id, tenant_id=command.tenant_id,
                order_request_id=command.order_request_id, idempotency_key=command.idempotency_key,
                request_version=command.request_version, terms_hash=command.terms.terms_hash,
                snapshot_version=command.snapshot_version, assessment_id=command.assessment_id,
                actor_id=actor_id, approval_reason=approval_reason,
                status="UNKNOWN", receipt=receipt.model_dump(mode="json"), created_at=now,
            ))
            self.db.flush()
            return receipt

        target_id = f"com_{command.order_request_id}"
        lots = {lot.lot_id: lot for lot in projected.operational.inventory_lots}
        reservations: list[dict] = []
        operation_id = f"mop_{uuid4().hex}"
        reservation_source = next((source for source in projected.operational.sources
                                   if source.kind == "reservations"), None)
        if reservation_source is None:
            raise DomainError("MOCK_RESOURCE_INCOMPLETE", "Reservation provenance is missing", status_code=409)
        for material in assessment.materials.materials:
            if material.commitment_id != target_id:
                continue
            for allocation in material.allocations:
                lot = lots.get(allocation.supply_id)
                if allocation.kind != "LOT" or lot is None or lot.unit != material.unit:
                    raise DomainError("MOCK_RESERVATION_UNSUPPORTED", "Only exact-unit stock lots can be reserved",
                                      status_code=409)
                reservations.append({
                    "reservation_id": f"mres_{uuid4().hex}", "tenant_id": command.tenant_id,
                    "inventory_lot_id": lot.lot_id, "commitment_id": target_id,
                    "quantity": allocation.quantity, "unit": lot.unit,
                    "status": "ACTIVE", "source_refs": (reservation_source.source_id,),
                })
        if not reservations:
            raise DomainError("MOCK_RESERVATION_UNSUPPORTED", "No stock-lot allocation was proven", status_code=409)
        now = datetime.now(UTC)
        data = projected.model_dump(mode="python", exclude_computed_fields=True)
        data["operational"]["reservations"] = [*data["operational"]["reservations"], *reservations]
        data["operational"]["snapshot_version"] = state.snapshot_version + 1
        data["operational"]["snapshot_id"] = f"mock-orbyte-{command.tenant_id}-{state.snapshot_version + 1}"
        data["operational"]["captured_at"] = now
        data["as_of"] = now
        data["current_snapshot_version"] = state.snapshot_version + 1
        try:
            updated = EvaluationSnapshot.model_validate(data)
        except ValueError as exc:
            raise DomainError("MOCK_RESOURCE_RECONCILIATION_FAILED", "Reserved snapshot is invalid",
                              status_code=409) from exc
        receipt = ReservationReceipt(
            tenant_id=command.tenant_id, order_request_id=command.order_request_id,
            operation_id=operation_id, idempotency_key=command.idempotency_key,
            request_version=command.request_version, terms_hash=command.terms.terms_hash,
            terms_revision=command.terms.terms_revision, snapshot_id=command.snapshot_id,
            snapshot_version=command.snapshot_version, assessment_id=command.assessment_id,
            status="CONFIRMED", mode="MOCK", checked_at=now,
            reservation_ids=tuple(row["reservation_id"] for row in reservations),
            evidence_refs=(f"mock-orbyte:receipt:{operation_id}",),
        )
        state.snapshot_version += 1
        state.snapshot_payload = updated.model_dump(mode="json", exclude_computed_fields=True)
        state.updated_at = now
        self.db.add(MockOrbyteReservationRecord(
            operation_id=operation_id, tenant_id=command.tenant_id,
            order_request_id=command.order_request_id, idempotency_key=command.idempotency_key,
            request_version=command.request_version, terms_hash=command.terms.terms_hash,
            snapshot_version=command.snapshot_version, assessment_id=command.assessment_id,
            actor_id=actor_id, approval_reason=approval_reason,
            status="CONFIRMED", receipt=receipt.model_dump(mode="json"), created_at=now,
        ))
        self.db.flush()
        return receipt

    def reconcile_unknown(self, tenant_id: str, operation_id: str) -> ReservationReceipt:
        """The local Mock records no side effect for UNKNOWN; verify before retry."""
        row = self.db.scalar(select(MockOrbyteReservationRecord).where(
            MockOrbyteReservationRecord.tenant_id == tenant_id,
            MockOrbyteReservationRecord.operation_id == operation_id,
        ).with_for_update())
        if row is None:
            raise DomainError("MOCK_RESERVATION_NOT_FOUND", "Mock reservation not found", status_code=404)
        if row.status != "UNKNOWN":
            return ReservationReceipt.model_validate(row.receipt)
        receipt = ReservationReceipt.model_validate(row.receipt)
        if receipt.reservation_ids:
            raise DomainError("MOCK_RECONCILIATION_UNSAFE", "Unknown side effect needs manual investigation",
                              status_code=409)
        failed = receipt.model_copy(update={"status": "FAILED", "checked_at": datetime.now(UTC),
                                            "evidence_refs": (*receipt.evidence_refs,
                                                              f"mock-orbyte:reconciled-empty:{operation_id}")})
        row.status = "FAILED"
        row.receipt = failed.model_dump(mode="json")
        self.db.flush()
        return failed
