from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.app.feasibility.fixtures import (
    build_supplier_delay_scenario,
    build_two_affected_scenario,
)
from backend.app.feasibility.models import (
    CapacityWindow,
    FreshnessStatus,
    OperationalSnapshot,
    Reservation,
    ReservationStatus,
    SnapshotValidationStatus,
)


def test_supplier_delay_fixture_preserves_before_after_versions_and_expected_labels():
    scenario = build_supplier_delay_scenario()

    assert scenario.before.snapshot_version == 1
    assert scenario.after.snapshot_version == 2
    assert scenario.before.tenant_id == scenario.after.tenant_id
    assert scenario.changed_delivery_id == "delivery-patty-001"
    assert scenario.expected_affected_commitment_ids == ("com-001",)
    assert scenario.expected_unaffected_commitment_ids == ("com-002",)
    assert scenario.expected_shortages[0].quantity == Decimal("40")
    assert scenario.expected_shortages[0].unit == "pcs"
    assert scenario.before.incoming_deliveries[0].expected_at.hour == 8
    assert scenario.after.incoming_deliveries[0].expected_at.hour == 11
    assert scenario.before.freshness_status is FreshnessStatus.CURRENT
    assert scenario.before.validation_status is SnapshotValidationStatus.VALID
    assert {component.component_sku_id for component in scenario.before.bom_components} == {
        "PATTY",
        "BUN",
        "WRAP",
    }
    calendar = scenario.before.capacity_calendars[0]
    assert calendar.resource_id == "kitchen-line-1"
    assert calendar.timezone_name == "Asia/Kuala_Lumpur"
    assert calendar.windows[0].available_minutes == Decimal("480")
    assert scenario.before.logistics_cutoff_at.isoformat() == "2026-10-24T08:00:00+08:00"
    assert scenario.before.confirmed_commitments[0].lines[0].material_use_at.isoformat() == (
        "2026-10-23T09:00:00+08:00"
    )
    assert scenario.after.confirmed_commitments[1].lines[0].material_use_at.isoformat() == (
        "2026-10-24T09:00:00+08:00"
    )


def test_two_affected_fixture_uses_documented_stable_allocation_order():
    scenario = build_two_affected_scenario()

    assert scenario.allocation_priority_commitment_ids == ("com-001", "com-002")
    assert scenario.expected_affected_commitment_ids == ("com-001", "com-002")
    assert [(row.commitment_id, row.quantity) for row in scenario.expected_shortages] == [
        ("com-001", Decimal("70")),
        ("com-002", Decimal("40")),
    ]
    assert sum((row.quantity for row in scenario.expected_shortages), Decimal("0")) == Decimal("110")


def test_buffered_fixture_has_capacity_calendar_coverage_for_both_material_use_times():
    scenario = build_supplier_delay_scenario()

    for snapshot in (scenario.before, scenario.after):
        windows = tuple(
            window
            for calendar in snapshot.capacity_calendars
            for window in calendar.windows
        )
        for commitment in snapshot.confirmed_commitments:
            for line in commitment.lines:
                material_use_at = line.material_use_at.astimezone(timezone.utc)
                assert any(
                    window.start_at.astimezone(timezone.utc)
                    <= material_use_at
                    <= window.end_at.astimezone(timezone.utc)
                    for window in windows
                ), f"no capacity-calendar window covers {commitment.commitment_id} material use"


def test_capacity_window_rejects_available_minutes_above_elapsed_duration():
    with pytest.raises(ValidationError, match="available_minutes.*duration"):
        CapacityWindow(
            start_at=datetime.fromisoformat("2026-10-23T07:00:00+08:00"),
            end_at=datetime.fromisoformat("2026-10-23T08:00:00+08:00"),
            available_minutes=Decimal("61"),
        )


def test_snapshot_rejects_material_use_after_commitment_delivery_deadline():
    snapshot = build_supplier_delay_scenario().before
    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["confirmed_commitments"][0]["delivery_deadline"] = datetime.fromisoformat(
        "2026-10-23T08:59:00+08:00"
    )

    with pytest.raises(ValidationError, match="material_use_at.*delivery_deadline"):
        OperationalSnapshot.model_validate(payload)


def test_active_reservation_is_owned_by_one_tenant_commitment_and_lot():
    snapshot = build_supplier_delay_scenario().before
    reservation = snapshot.reservations[0]
    lot = next(row for row in snapshot.inventory_lots if row.lot_id == reservation.inventory_lot_id)

    assert reservation.tenant_id == snapshot.tenant_id
    assert reservation.commitment_id == "com-002"
    assert reservation.status is ReservationStatus.ACTIVE
    assert reservation.quantity == Decimal("20")
    assert reservation.source_refs
    assert lot.quantity == Decimal("80")


def test_snapshot_is_immutable_and_supplier_change_creates_a_new_version():
    scenario = build_supplier_delay_scenario()

    with pytest.raises((ValidationError, AttributeError)):
        scenario.before.snapshot_version = 99

    assert scenario.before.incoming_deliveries[0].expected_at.hour == 8
    assert scenario.after.incoming_deliveries[0].expected_at.hour == 11
    assert scenario.after.snapshot_id != scenario.before.snapshot_id


def test_snapshot_rejects_duplicate_source_sku_and_lot_ids():
    snapshot = build_supplier_delay_scenario().before
    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["sku_catalog"] = (*payload["sku_catalog"], payload["sku_catalog"][0])

    with pytest.raises(ValidationError, match="duplicate"):
        OperationalSnapshot.model_validate(payload)

    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["inventory_lots"] = (*payload["inventory_lots"], payload["inventory_lots"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        OperationalSnapshot.model_validate(payload)

    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["sources"] = (*payload["sources"], payload["sources"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        OperationalSnapshot.model_validate(payload)


def test_snapshot_rejects_cross_tenant_rows_and_unresolved_source_evidence():
    snapshot = build_supplier_delay_scenario().before
    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["confirmed_commitments"][0]["tenant_id"] = "tenant_other"

    with pytest.raises(ValidationError, match="tenant"):
        OperationalSnapshot.model_validate(payload)

    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["inventory_lots"][0]["source_refs"] = ("missing-source",)
    with pytest.raises(ValidationError, match="source"):
        OperationalSnapshot.model_validate(payload)


def test_snapshot_rejects_unit_mismatch_and_active_reservations_exceeding_lot():
    snapshot = build_supplier_delay_scenario().before
    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["inventory_lots"][0]["unit"] = "kg"
    with pytest.raises(ValidationError, match="unit"):
        OperationalSnapshot.model_validate(payload)

    payload = snapshot.model_dump(exclude_computed_fields=True)
    extra = Reservation(
        reservation_id="reservation-overlap",
        tenant_id=snapshot.tenant_id,
        inventory_lot_id="lot-patty-001",
        commitment_id="com-001",
        quantity=Decimal("61"),
        unit="pcs",
        status=ReservationStatus.ACTIVE,
        source_refs=("source-reservations-001",),
    )
    payload["reservations"] = (*payload["reservations"], extra.model_dump())
    with pytest.raises(ValidationError, match="reservation"):
        OperationalSnapshot.model_validate(payload)


def test_snapshot_rejects_floating_point_inventory_quantities():
    snapshot = build_supplier_delay_scenario().before
    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["inventory_lots"][0]["quantity"] = 80.1

    with pytest.raises(ValidationError, match="decimal value or integer"):
        OperationalSnapshot.model_validate(payload)


def test_snapshot_retains_expired_lots_but_marks_them_unusable():
    snapshot = build_supplier_delay_scenario().before
    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["inventory_lots"][1]["expires_at"] = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)

    expired = OperationalSnapshot.model_validate(payload)

    assert expired.expired_lot_ids == ("lot-bun-001",)
    assert expired.validation_status is SnapshotValidationStatus.VALID


def test_missing_bom_and_stale_or_missing_sources_are_preserved_as_incomplete():
    snapshot = build_supplier_delay_scenario().before
    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["bom_components"] = ()
    payload["sources"] = tuple(
        {
            **source,
            "source_ref": None,
            "observed_at": None,
            "valid_through": None,
            "evidence_refs": (),
        }
        if source["source_id"] == "source-bom-001"
        else source
        for source in payload["sources"]
    )

    incomplete = OperationalSnapshot.model_validate(payload)

    assert incomplete.source_freshness("BOM") is FreshnessStatus.MISSING
    assert incomplete.validation_status is SnapshotValidationStatus.INCOMPLETE
    assert {issue.code for issue in incomplete.validation_issues} >= {"MISSING_SOURCE", "MISSING_BOM"}

    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["sources"] = tuple(
        {
            **source,
            "observed_at": datetime(2026, 10, 20, 12, tzinfo=timezone.utc),
            "valid_through": datetime(2026, 10, 21, 0, tzinfo=timezone.utc),
        }
        if source["source_id"] == "source-inventory-001"
        else source
        for source in payload["sources"]
    )
    stale = OperationalSnapshot.model_validate(payload)

    assert stale.source_freshness("INVENTORY") is FreshnessStatus.STALE
    assert stale.freshness_status is FreshnessStatus.STALE
    assert stale.validation_status is SnapshotValidationStatus.INCOMPLETE


def test_snapshot_rejects_naive_datetimes_and_compares_offset_aware_instants():
    snapshot = build_supplier_delay_scenario().before
    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["captured_at"] = "2026-10-22T12:00:00"
    with pytest.raises(ValidationError, match="offset-aware"):
        OperationalSnapshot.model_validate(payload)

    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["incoming_deliveries"][0]["expected_at"] = "2026-10-23T08:00:00"
    with pytest.raises(ValidationError, match="offset-aware"):
        OperationalSnapshot.model_validate(payload)

    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["captured_at"] = datetime(2026, 10, 22, 4, tzinfo=timezone.utc)
    utc_snapshot = OperationalSnapshot.model_validate(payload)

    assert utc_snapshot.captured_at.astimezone(timezone.utc) == snapshot.captured_at.astimezone(timezone.utc)
    assert utc_snapshot.freshness_status is FreshnessStatus.CURRENT

    serialized = snapshot.model_dump(mode="json")
    assert serialized["captured_at"] == "2026-10-22T12:00:00+08:00"
    assert serialized["inventory_lots"][0]["quantity"] == "80"


def test_unconfirmed_incoming_delivery_is_preserved_with_confirmation_state():
    snapshot = build_supplier_delay_scenario().before
    unconfirmed = next(
        row for row in snapshot.incoming_deliveries if row.confirmation_status.value == "UNCONFIRMED"
    )

    assert unconfirmed.quantity == Decimal("500")
    assert unconfirmed.source_refs
    assert all(row.confirmation_status.value == "CONFIRMED" for row in snapshot.incoming_deliveries if row is not unconfirmed)


def test_snapshot_rejects_confirmation_evidence_from_after_capture():
    snapshot = build_supplier_delay_scenario().before
    payload = snapshot.model_dump(exclude_computed_fields=True)
    payload["incoming_deliveries"][0]["confirmed_at"] = datetime.fromisoformat(
        "2026-10-23T12:00:00+08:00"
    )

    with pytest.raises(ValidationError, match="after snapshot capture"):
        OperationalSnapshot.model_validate(payload)
