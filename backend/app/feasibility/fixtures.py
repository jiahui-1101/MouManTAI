"""Reproducible, labelled synthetic operational snapshots for P2 development."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .models import (
    BomComponent,
    CapacityCalendar,
    CapacityWindow,
    CommitmentLine,
    ConfirmedCommitment,
    DeliveryConfirmationStatus,
    IncomingDelivery,
    InventoryLot,
    OperationalSnapshot,
    Reservation,
    ReservationStatus,
    Sku,
    SkuSupplyType,
    SourceEvidence,
    SourceKind,
    SupplierDeliveryEvidence,
    SupplierDeliveryEvidenceType,
)


FIXTURE_TENANT_ID = "tenant-synthetic-p2"
FIXTURE_TIMEZONE = "Asia/Kuala_Lumpur"


@dataclass(frozen=True, slots=True)
class ExpectedShortage:
    commitment_id: str
    sku_id: str
    quantity: Decimal
    unit: str


@dataclass(frozen=True, slots=True)
class SupplierDelayScenario:
    scenario_id: str
    before: OperationalSnapshot
    after: OperationalSnapshot
    changed_delivery_id: str
    allocation_priority_commitment_ids: tuple[str, ...]
    expected_affected_commitment_ids: tuple[str, ...]
    expected_unaffected_commitment_ids: tuple[str, ...]
    expected_shortages: tuple[ExpectedShortage, ...]


def build_supplier_delay_scenario() -> SupplierDelayScenario:
    """One affected commitment and one later, fully buffered commitment."""

    captured_at = datetime.fromisoformat("2026-10-22T12:00:00+08:00")
    before = _build_snapshot(
        snapshot_id="snapshot-buffered-v1",
        version=1,
        captured_at=captured_at,
        patty_on_hand=Decimal("80"),
        deliveries=(
            _delivery("delivery-patty-001", Decimal("40"), "2026-10-23T08:00:00+08:00", True),
            _delivery("delivery-unconfirmed-001", Decimal("500"), "2026-10-23T07:00:00+08:00", False),
        ),
        commitment_specs=(
            ("com-001", "2026-10-23T09:00:00+08:00", "2026-10-24T15:00:00+08:00", Decimal("100")),
            ("com-002", "2026-10-24T09:00:00+08:00", "2026-10-24T15:00:00+08:00", Decimal("20")),
        ),
        reservations=(
            Reservation(
                reservation_id="reservation-com-002-patty",
                tenant_id=FIXTURE_TENANT_ID,
                inventory_lot_id="lot-patty-001",
                commitment_id="com-002",
                quantity=Decimal("20"),
                unit="pcs",
                status=ReservationStatus.ACTIVE,
                source_refs=("source-reservations-001",),
            ),
        ),
        logistics_cutoff_at=datetime.fromisoformat("2026-10-24T08:00:00+08:00"),
        additional_capacity_windows=(
            CapacityWindow(
                start_at=datetime.fromisoformat("2026-10-24T07:00:00+08:00"),
                end_at=datetime.fromisoformat("2026-10-24T17:00:00+08:00"),
                available_minutes=Decimal("480"),
            ),
        ),
    )
    after = _delay_delivery(before, captured_at + timedelta(minutes=30), "2026-10-23T11:00:00+08:00")
    return SupplierDelayScenario(
        scenario_id="supplier-delay-buffered-unaffected",
        before=before,
        after=after,
        changed_delivery_id="delivery-patty-001",
        allocation_priority_commitment_ids=("com-001", "com-002"),
        expected_affected_commitment_ids=("com-001",),
        expected_unaffected_commitment_ids=("com-002",),
        expected_shortages=(ExpectedShortage("com-001", "PATTY", Decimal("40"), "pcs"),),
    )


def build_two_affected_scenario() -> SupplierDelayScenario:
    """Two same-deadline commitments, stable ID tie-break, one delayed receipt."""

    captured_at = datetime.fromisoformat("2026-10-22T12:00:00+08:00")
    before = _build_snapshot(
        snapshot_id="snapshot-two-affected-v1",
        version=1,
        captured_at=captured_at,
        patty_on_hand=Decimal("30"),
        deliveries=(_delivery("delivery-patty-110", Decimal("110"), "2026-10-23T08:00:00+08:00", True),),
        commitment_specs=(
            ("com-001", "2026-10-23T09:00:00+08:00", "2026-10-24T15:00:00+08:00", Decimal("100")),
            ("com-002", "2026-10-23T09:00:00+08:00", "2026-10-24T15:00:00+08:00", Decimal("40")),
        ),
        reservations=(),
        logistics_cutoff_at=datetime.fromisoformat("2026-10-23T08:00:00+08:00"),
    )
    after = _delay_delivery(before, captured_at + timedelta(minutes=30), "2026-10-23T11:00:00+08:00")
    return SupplierDelayScenario(
        scenario_id="supplier-delay-two-affected",
        before=before,
        after=after,
        changed_delivery_id="delivery-patty-110",
        allocation_priority_commitment_ids=("com-001", "com-002"),
        expected_affected_commitment_ids=("com-001", "com-002"),
        expected_unaffected_commitment_ids=(),
        expected_shortages=(
            ExpectedShortage("com-001", "PATTY", Decimal("70"), "pcs"),
            ExpectedShortage("com-002", "PATTY", Decimal("40"), "pcs"),
        ),
    )


def _build_snapshot(
    *,
    snapshot_id: str,
    version: int,
    captured_at: datetime,
    patty_on_hand: Decimal,
    deliveries: tuple[IncomingDelivery, ...],
    commitment_specs: tuple[tuple[str, str, str, Decimal], ...],
    reservations: tuple[Reservation, ...],
    logistics_cutoff_at: datetime,
    additional_capacity_windows: tuple[CapacityWindow, ...] = (),
) -> OperationalSnapshot:
    fresh_through = datetime.fromisoformat("2026-10-26T00:00:00+08:00")
    confirmation_evidence = tuple(
        _confirmation_evidence(delivery)
        for delivery in deliveries
        if delivery.confirmation_status is DeliveryConfirmationStatus.CONFIRMED
    )
    sources = tuple(
        SourceEvidence(
            source_id=source_id,
            tenant_id=FIXTURE_TENANT_ID,
            kind=kind,
            source_ref=f"synthetic://p2/{kind.value}/{version}",
            observed_at=captured_at,
            valid_through=fresh_through,
            evidence_refs=(
                raw_refs
                + tuple(evidence.evidence_ref for evidence in confirmation_evidence)
                if source_id == "source-deliveries-001"
                else raw_refs
            ),
            supplier_delivery_evidence=(
                confirmation_evidence if source_id == "source-deliveries-001" else ()
            ),
        )
        for source_id, kind, raw_refs in (
            ("source-sku-001", SourceKind.SKU_CATALOG, ("sku-catalog-v1",)),
            ("source-bom-001", SourceKind.BOM, ("bom-burger-v1",)),
            ("source-inventory-001", SourceKind.INVENTORY, ("stocktake-patty-v1", "stocktake-bun-v1", "stocktake-wrap-v1")),
            ("source-reservations-001", SourceKind.RESERVATIONS, ("reservation-ledger-v1",)),
            ("source-deliveries-001", SourceKind.INCOMING_DELIVERIES, ("supplier-quote-v1",)),
            ("source-capacity-001", SourceKind.CAPACITY_CALENDARS, ("kitchen-calendar-v1",)),
            ("source-commitments-001", SourceKind.CONFIRMED_COMMITMENTS, ("commitment-registry-v1",)),
            ("source-logistics-001", SourceKind.LOGISTICS_CUTOFF, ("receiving-cutoff-v1",)),
        )
    )
    sku_catalog = (
        Sku(sku_id="BURGER", tenant_id=FIXTURE_TENANT_ID, base_unit="pcs", supply_type=SkuSupplyType.MANUFACTURED, source_refs=("source-sku-001",)),
        Sku(sku_id="PATTY", tenant_id=FIXTURE_TENANT_ID, base_unit="pcs", supply_type=SkuSupplyType.PURCHASED, source_refs=("source-sku-001",)),
        Sku(sku_id="BUN", tenant_id=FIXTURE_TENANT_ID, base_unit="pcs", supply_type=SkuSupplyType.PURCHASED, source_refs=("source-sku-001",)),
        Sku(sku_id="WRAP", tenant_id=FIXTURE_TENANT_ID, base_unit="pcs", supply_type=SkuSupplyType.PURCHASED, source_refs=("source-sku-001",)),
    )
    bom_components = tuple(
        BomComponent(
            component_id=f"bom-burger-{sku_id.lower()}",
            tenant_id=FIXTURE_TENANT_ID,
            parent_sku_id="BURGER",
            component_sku_id=sku_id,
            quantity=Decimal("1"),
            unit="pcs",
            source_refs=("source-bom-001",),
        )
        for sku_id in ("PATTY", "BUN", "WRAP")
    )
    inventory_lots = (
        InventoryLot(lot_id="lot-patty-001", tenant_id=FIXTURE_TENANT_ID, sku_id="PATTY", quantity=patty_on_hand, unit="pcs", warehouse_id="warehouse-kitchen", expires_at=datetime.fromisoformat("2026-10-30T00:00:00+08:00"), source_refs=("source-inventory-001",)),
        InventoryLot(lot_id="lot-bun-001", tenant_id=FIXTURE_TENANT_ID, sku_id="BUN", quantity=Decimal("140"), unit="pcs", warehouse_id="warehouse-kitchen", expires_at=datetime.fromisoformat("2026-10-30T00:00:00+08:00"), source_refs=("source-inventory-001",)),
        InventoryLot(lot_id="lot-wrap-001", tenant_id=FIXTURE_TENANT_ID, sku_id="WRAP", quantity=Decimal("140"), unit="pcs", warehouse_id="warehouse-kitchen", expires_at=datetime.fromisoformat("2026-10-30T00:00:00+08:00"), source_refs=("source-inventory-001",)),
    )
    capacity = CapacityCalendar(
        calendar_id="calendar-kitchen-001",
        tenant_id=FIXTURE_TENANT_ID,
        resource_id="kitchen-line-1",
        timezone_name=FIXTURE_TIMEZONE,
        windows=(
            CapacityWindow(
                start_at=datetime.fromisoformat("2026-10-23T07:00:00+08:00"),
                end_at=datetime.fromisoformat("2026-10-23T17:00:00+08:00"),
                available_minutes=Decimal("480"),
            ),
            *additional_capacity_windows,
        ),
        source_refs=("source-capacity-001",),
    )
    commitments = tuple(
        ConfirmedCommitment(
            commitment_id=commitment_id,
            tenant_id=FIXTURE_TENANT_ID,
            commitment_version=1,
            delivery_deadline=datetime.fromisoformat(deadline),
            lines=(
                CommitmentLine(
                    line_id=f"{commitment_id}-line-1",
                    sku_id="BURGER",
                    quantity=quantity,
                    unit="pcs",
                    material_use_at=datetime.fromisoformat(material_use_at),
                ),
            ),
            source_refs=("source-commitments-001",),
        )
        for commitment_id, material_use_at, deadline, quantity in commitment_specs
    )
    return OperationalSnapshot(
        snapshot_id=snapshot_id,
        snapshot_version=version,
        tenant_id=FIXTURE_TENANT_ID,
        captured_at=captured_at,
        sources=sources,
        sku_catalog=sku_catalog,
        bom_components=bom_components,
        inventory_lots=inventory_lots,
        reservations=reservations,
        incoming_deliveries=deliveries,
        capacity_calendars=(capacity,),
        confirmed_commitments=commitments,
        logistics_cutoff_at=logistics_cutoff_at,
    )


def _delivery(delivery_id: str, quantity: Decimal, expected_at: str, confirmed: bool) -> IncomingDelivery:
    return IncomingDelivery(
        delivery_id=delivery_id,
        tenant_id=FIXTURE_TENANT_ID,
        supplier_id="supplier-synthetic-001",
        sku_id="PATTY",
        quantity=quantity,
        unit="pcs",
        confirmation_status=(
            DeliveryConfirmationStatus.CONFIRMED
            if confirmed
            else DeliveryConfirmationStatus.UNCONFIRMED
        ),
        confirmed_at=(
            datetime.fromisoformat("2026-10-22T10:00:00+08:00") if confirmed else None
        ),
        confirmation_evidence_id=_confirmation_evidence_id(delivery_id) if confirmed else None,
        expected_at=datetime.fromisoformat(expected_at),
        source_refs=("source-deliveries-001",),
    )


def _confirmation_evidence_id(delivery_id: str) -> str:
    return f"confirmation-{delivery_id}-v1"


def _confirmation_evidence(delivery: IncomingDelivery) -> SupplierDeliveryEvidence:
    if delivery.confirmed_at is None or delivery.confirmation_evidence_id is None:
        raise ValueError("confirmed fixture delivery requires confirmation provenance")
    return SupplierDeliveryEvidence(
        evidence_id=delivery.confirmation_evidence_id,
        tenant_id=delivery.tenant_id,
        delivery_id=delivery.delivery_id,
        supplier_id=delivery.supplier_id,
        evidence_type=SupplierDeliveryEvidenceType.CONFIRMATION,
        evidence_ref=f"supplier-confirmation-{delivery.delivery_id}-v1",
        observed_at=delivery.confirmed_at,
    )


def _delay_delivery(
    snapshot: OperationalSnapshot,
    captured_at: datetime,
    expected_at: str,
) -> OperationalSnapshot:
    changed_deliveries = tuple(
        delivery
        for delivery in snapshot.incoming_deliveries
        if delivery.delivery_id in {"delivery-patty-001", "delivery-patty-110"}
    )
    eta_change_evidence = tuple(
        SupplierDeliveryEvidence(
            evidence_id=f"eta-change-{delivery.delivery_id}-v2",
            tenant_id=delivery.tenant_id,
            delivery_id=delivery.delivery_id,
            supplier_id=delivery.supplier_id,
            evidence_type=SupplierDeliveryEvidenceType.ETA_CHANGE,
            evidence_ref=f"supplier-eta-change-{delivery.delivery_id}-v2",
            observed_at=captured_at,
        )
        for delivery in changed_deliveries
    )
    eta_evidence_by_delivery_id = {
        evidence.delivery_id: evidence for evidence in eta_change_evidence
    }
    delayed_rows = []
    for delivery in snapshot.incoming_deliveries:
        row = delivery.model_dump(exclude_computed_fields=True)
        if delivery.delivery_id in eta_evidence_by_delivery_id:
            evidence = eta_evidence_by_delivery_id[delivery.delivery_id]
            row.update(
                {
                    "expected_at": datetime.fromisoformat(expected_at),
                    "source_refs": (*delivery.source_refs, "source-deliveries-002"),
                    "eta_change_evidence_ids": (
                        *delivery.eta_change_evidence_ids,
                        evidence.evidence_id,
                    ),
                }
            )
        delayed_rows.append(row)
    sources = (
        *snapshot.sources,
        SourceEvidence(
            source_id="source-deliveries-002",
            tenant_id=snapshot.tenant_id,
            kind=SourceKind.INCOMING_DELIVERIES,
            source_ref="synthetic://p2/incoming-deliveries/eta-change-v2",
            observed_at=captured_at,
            valid_through=datetime.fromisoformat("2026-10-26T00:00:00+08:00"),
            evidence_refs=tuple(evidence.evidence_ref for evidence in eta_change_evidence),
            supplier_delivery_evidence=eta_change_evidence,
        ),
    )
    # Revalidate all updated data; model_copy alone intentionally skips validation.
    return OperationalSnapshot.model_validate(
        {
            **snapshot.model_dump(exclude_computed_fields=True),
            "snapshot_id": f"{snapshot.snapshot_id.rsplit('-', 1)[0]}-v2",
            "snapshot_version": snapshot.snapshot_version + 1,
            "captured_at": captured_at,
            "sources": sources,
            "incoming_deliveries": tuple(delayed_rows),
        }
    )
