"""Time-phased, query-only material ATP across all confirmed competing demand.

COVERED/SHORTAGE describe materials only. They do not establish production or
overall commitment feasibility, change Core state, or reserve operational stock.
"""

from datetime import datetime, timezone
from decimal import Decimal, DecimalException

from .bom import evidence_for, explode_bom, source_issues
from .materials import MaterialATP, MaterialAvailability, SupplyAllocation
from .models import (
    DeliveryConfirmationStatus, IssueSeverity, OperationalSnapshot, ReservationStatus,
    SkuSupplyType, SnapshotIssue, SourceKind, _utc,
)
from .quantities import add, subtract


def calculate_atp(
    snapshot: OperationalSnapshot, *, tenant_id: str, as_of: datetime | None = None,
) -> MaterialATP:
    if tenant_id != snapshot.tenant_id:
        raise ValueError('tenant scope mismatch')
    # Pydantic model_copy/model_construct bypass validators; never trust those at
    # a calculation boundary, even when the ordinary snapshot type is frozen.
    snapshot = OperationalSnapshot.model_validate(snapshot.model_dump(exclude_computed_fields=True))
    instant = snapshot.captured_at if as_of is None else as_of
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('calculation time must be offset-aware')
    if _utc(instant) < _utc(snapshot.captured_at):
        raise ValueError('calculation time cannot precede snapshot capture')
    expansion = explode_bom(snapshot, tenant_id=tenant_id)
    kinds = (SourceKind.SKU_CATALOG, SourceKind.BOM, SourceKind.INVENTORY,
             SourceKind.RESERVATIONS, SourceKind.INCOMING_DELIVERIES,
             SourceKind.CONFIRMED_COMMITMENTS, SourceKind.LOGISTICS_CUTOFF)
    issues = list(expansion.issues)
    for issue in source_issues(snapshot, kinds, instant):
        if issue not in issues:
            issues.append(issue)

    def incomplete(code, resource, message, refs=()):
        issues.append(SnapshotIssue(code=code, resource_id=resource, message=message,
                                    severity=IssueSeverity.INCOMPLETE,
                                    evidence_refs=evidence_for(snapshot, refs)))

    for requirement in expansion.requirements:
        if _utc(requirement.needed_by) < _utc(instant):
            incomplete('PAST_MATERIAL_USE', requirement.line_id,
                       'Past demand needs verified consumption/remaining-demand input.')
    for delivery in snapshot.incoming_deliveries:
        if delivery.confirmation_status == DeliveryConfirmationStatus.CONFIRMED and _utc(delivery.expected_at) <= _utc(instant):
            incomplete('OVERDUE_RECEIPT', delivery.delivery_id,
                       'Outstanding receipt at/before calculation time needs receipt/stock reconciliation.',
                       delivery.source_refs)
    manufactured = {s.sku_id for s in snapshot.sku_catalog if s.supply_type == SkuSupplyType.MANUFACTURED}
    for supply in (*snapshot.inventory_lots, *snapshot.incoming_deliveries):
        if supply.sku_id in manufactured:
            incomplete('STOCKED_ASSEMBLY_UNSUPPORTED', supply.sku_id,
                       'Stocked assemblies require netting intermediate production before leaf explosion.', supply.source_refs)

    relevant_refs = tuple(sorted(s.source_id for s in snapshot.sources if s.kind in kinds))
    all_evidence = evidence_for(snapshot, relevant_refs)
    assumptions = (*expansion.assumptions,
                   'Material-only check; capacity, production jobs and full feasibility are not evaluated.',
                   'Allocation order: material-use instant, commitment ID/version, line ID, SKU.',
                   'Active reservations stay held for owners; unused reserved surplus is not released.',
                   'Unscoped demand pools warehouses; scoped demand requires exact warehouse match.',
                   'Lot expiry is exclusive; receipt ETA <= material use and <= logistics cutoff.',
                   'Confirmed receipts are projected supply backed by P2-local evidence, not goods received.')

    def result(materials=()):
        return MaterialATP(
            tenant_id=tenant_id, snapshot_id=snapshot.snapshot_id,
            snapshot_version=snapshot.snapshot_version, as_of=instant,
            status='UNKNOWN' if issues else ('SHORTAGE' if any(r.shortage > 0 for r in materials) else 'COVERED'),
            materials=() if issues else tuple(materials), assumptions=assumptions,
            issues=tuple(issues), evidence_refs=all_evidence,
        )

    if issues:
        return result()

    lots = {lot.lot_id: lot for lot in snapshot.inventory_lots}
    active = sorted((r for r in snapshot.reservations if r.status == ReservationStatus.ACTIVE),
                    key=lambda r: (r.inventory_lot_id, r.reservation_id))
    held = {}
    try:
        free = {lot.lot_id: snapshot.quantity_in_base(lot.sku_id, lot.quantity, lot.unit) for lot in lots.values()}
        for reservation in active:
            lot = lots[reservation.inventory_lot_id]
            quantity = snapshot.quantity_in_base(lot.sku_id, reservation.quantity, reservation.unit)
            held[reservation.reservation_id] = quantity
            free[lot.lot_id] = subtract(free[lot.lot_id], quantity)
        receipts = sorted((d for d in snapshot.incoming_deliveries
                           if d.confirmation_status == DeliveryConfirmationStatus.CONFIRMED),
                          key=lambda d: (_utc(d.expected_at), d.delivery_id))
        remaining_receipts = {d.delivery_id: snapshot.quantity_in_base(d.sku_id, d.quantity, d.unit) for d in receipts}
        ordered_lots = sorted(lots.values(), key=lambda lot: (
            _utc(lot.expires_at) if lot.expires_at else datetime.max.replace(tzinfo=timezone.utc), lot.lot_id))
        materials = []
        for requirement in expansion.requirements:
            remaining = requirement.quantity
            allocations = []
            totals = {'LOT': Decimal(0), 'RESERVATION': Decimal(0), 'RECEIPT': Decimal(0)}

            def matches(supply):
                return supply.sku_id == requirement.sku_id and (
                    requirement.warehouse_id is None or supply.warehouse_id == requirement.warehouse_id)

            def take(supply_id, kind, available, refs, reservation_id=None):
                nonlocal remaining
                quantity = min(remaining, available)
                if quantity > 0:
                    allocations.append(SupplyAllocation(supply_id=supply_id, kind=kind,
                                       quantity=quantity, reservation_id=reservation_id,
                                       evidence_refs=evidence_for(snapshot, refs)))
                    remaining = subtract(remaining, quantity)
                    totals[kind] = add(totals[kind], quantity)
                return subtract(available, quantity)

            for reservation in active:
                lot = lots[reservation.inventory_lot_id]
                if (reservation.commitment_id == requirement.commitment_id and matches(lot)
                        and not lot.is_expired_at(requirement.needed_by)):
                    held[reservation.reservation_id] = take(lot.lot_id, 'RESERVATION', held[reservation.reservation_id],
                                                           (*lot.source_refs, *reservation.source_refs), reservation.reservation_id)
            for lot in ordered_lots:
                if matches(lot) and not lot.is_expired_at(requirement.needed_by):
                    free[lot.lot_id] = take(lot.lot_id, 'LOT', free[lot.lot_id], lot.source_refs)
            for delivery in receipts:
                if (matches(delivery) and _utc(delivery.expected_at) <= _utc(requirement.needed_by)
                        and _utc(delivery.expected_at) <= _utc(snapshot.logistics_cutoff_at)):
                    remaining_receipts[delivery.delivery_id] = take(delivery.delivery_id, 'RECEIPT',
                                                                  remaining_receipts[delivery.delivery_id], delivery.source_refs)
            materials.append(MaterialAvailability(
                commitment_id=requirement.commitment_id, commitment_version=requirement.commitment_version,
                line_id=requirement.line_id, sku_id=requirement.sku_id, unit=requirement.unit,
                needed_by=requirement.needed_by, warehouse_id=requirement.warehouse_id,
                code='MATERIAL_SHORTAGE' if remaining > 0 else 'MATERIAL_COVERED',
                required=requirement.quantity, usable=totals['LOT'], reserved=totals['RESERVATION'],
                confirmed_incoming=totals['RECEIPT'], shortage=remaining, allocations=tuple(allocations),
                evidence_refs=tuple(sorted(set((*requirement.evidence_refs, *all_evidence)))),
            ))
        return result(materials)
    except DecimalException:
        incomplete('CALCULATION_LIMIT', 'inventory', 'Quantities exceed supported exact arithmetic limits.')
        return result()
