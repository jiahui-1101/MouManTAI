from datetime import datetime, timedelta
from decimal import Context, Decimal, localcontext

import pytest

from app.core.schemas import Commitment, FeasibilityState
from app.feasibility.fixtures import build_supplier_delay_scenario, build_two_affected_scenario
from app.feasibility.impact import (
    ImpactClassification,
    OperationalChange,
    OperationalChangeType,
    ResourceKey,
    ResourceKind,
    assess_impact,
)
from app.feasibility.models import CapacityWindow, SourceEvidence, SourceKind
from app.feasibility.production import (
    EvaluationSnapshot,
    ProductionData,
    ProductionJob,
    ProductionProcess,
    ProductionSource,
)


CAPTURE = datetime.fromisoformat("2026-10-22T12:00:00+08:00")


def core_commitments(snapshot):
    result = []
    for row in snapshot.confirmed_commitments:
        line = row.lines[0]
        result.append(Commitment.model_validate({
            "tenant_id": row.tenant_id,
            "commitment_id": row.commitment_id,
            "order_id": f"order-{row.commitment_id}",
            "customer_id": f"customer-{row.commitment_id}",
            "terms": {"sku": line.sku_id, "quantity": str(line.quantity), "unit": line.unit,
                      "deadline": row.delivery_deadline},
            "agreement_state": "CONFIRMED", "feasibility_state": "NOT_ASSESSED",
            "risk_state": "NORMAL", "recovery_state": "NONE", "fulfilment_state": "NOT_STARTED",
            "commitment_version": row.commitment_version,
            "evidence_refs": [f"confirmation-{row.commitment_id}"], "updated_at": snapshot.captured_at,
        }))
    return tuple(result)


def production_for(snapshot):
    tenant = snapshot.tenant_id
    fresh_through = datetime.fromisoformat("2026-10-26T00:00:00+08:00")
    source_rows = (
        ("p4-resources", "resources", "synthetic-p4-resource-v1"),
        ("p4-processes", "processes", "synthetic-p4-process-v1"),
        ("p4-jobs", "jobs", "synthetic-p4-empty-job-ledger-v1"),
        ("p4-plans", "plans", "synthetic-p4-fixed-plan-v1"),
    )
    sources = tuple(ProductionSource(
        source_id=source_id, tenant_id=tenant, kind=kind,
        source_ref=f"synthetic://p2/phase4/{kind}", observed_at=snapshot.captured_at,
        valid_through=fresh_through, evidence_refs=(evidence_ref,),
    ) for source_id, kind, evidence_ref in source_rows)
    resources = ({"resource_id": "p4-line-1", "tenant_id": tenant, "source_refs": ("p4-resources",)},)
    processes = ({"process_id": "p4-burger", "tenant_id": tenant, "sku_id": "BURGER", "unit": "pcs",
                  "resource_ids": ("p4-line-1",), "minutes_per_unit": "1", "setup_minutes": "0",
                  "delivery_lead_minutes": "30", "source_refs": ("p4-processes",)},)
    plans = []
    operational = snapshot.model_dump(exclude_computed_fields=True)
    days = sorted({line["material_use_at"].date() for row in operational["confirmed_commitments"]
                   for line in row["lines"]})
    calendars = []
    for calendar in operational["capacity_calendars"]:
        windows = tuple(CapacityWindow(
            start_at=datetime.combine(day, datetime.min.time()).replace(hour=7, tzinfo=CAPTURE.tzinfo),
            end_at=datetime.combine(day, datetime.min.time()).replace(hour=17, tzinfo=CAPTURE.tzinfo),
            available_minutes=Decimal("600"),
        ) for day in days)
        calendars.append({**calendar, "resource_id": "p4-line-1", "windows": windows})
    operational["capacity_calendars"] = tuple(calendars)
    snapshot = type(snapshot).model_validate(operational)
    for commitment in snapshot.confirmed_commitments:
        for line in commitment.lines:
            day = line.material_use_at.date()
            plans.append({
                "tenant_id": tenant, "commitment_id": commitment.commitment_id,
                "commitment_version": commitment.commitment_version, "line_id": line.line_id,
                "start_at": line.material_use_at,
                "dispatch_cutoff_at": datetime.combine(day, datetime.min.time()).replace(hour=17, tzinfo=CAPTURE.tzinfo),
                "source_refs": ("p4-plans",),
            })
    production = ProductionData.model_validate({
        "tenant_id": tenant, "sources": sources, "resources": resources, "processes": processes,
        "plans": tuple(plans), "jobs": (), "jobs_covered_from": snapshot.captured_at,
        "jobs_covered_through": fresh_through,
    })
    return EvaluationSnapshot.model_validate({
        "operational": snapshot, "production": production, "as_of": snapshot.captured_at,
        "current_snapshot_version": snapshot.snapshot_version,
    })


def wrapped(snapshot, production=None):
    return EvaluationSnapshot.model_validate({
        "operational": snapshot, "production": production, "as_of": snapshot.captured_at,
        "current_snapshot_version": snapshot.snapshot_version,
    })


def supplier_change(before, after, delivery_id):
    delivery = next(row for row in after.incoming_deliveries if row.delivery_id == delivery_id)
    evidence_refs = tuple(sorted({
        evidence.evidence_ref
        for source in after.sources
        for evidence in source.supplier_delivery_evidence
        if evidence.evidence_id in delivery.eta_change_evidence_ids
    }))
    return OperationalChange(
        event_id="evt-supplier-eta-1", tenant_id=after.tenant_id, correlation_id="corr-p4-supplier-1",
        event_type=OperationalChangeType.SUPPLIER_DELIVERY_CHANGED,
        occurred_at=after.captured_at, before_snapshot_version=before.snapshot_version,
        after_snapshot_version=after.snapshot_version,
        resource_keys=(ResourceKey(kind=ResourceKind.SUPPLIER_DELIVERY, resource_id=delivery_id),),
        evidence_refs=evidence_refs,
    )


def test_buffered_supplier_fixture_discovers_candidates_but_keeps_full_impact_unknown():
    scenario = build_supplier_delay_scenario()
    before, after = wrapped(scenario.before), wrapped(scenario.after)
    result = assess_impact(before, after, supplier_change(scenario.before, scenario.after,
        scenario.changed_delivery_id), before_commitments=core_commitments(scenario.before),
        after_commitments=core_commitments(scenario.after))

    assert result.candidate_commitment_ids == ("com-001", "com-002")
    assert result.confirmed_impacted_commitment_ids == ()
    assert result.verified_unaffected_commitment_ids == ()
    assert result.unknown_commitment_ids == ("com-001", "com-002")
    com1 = next(row for row in result.impacts if row.commitment_id == "com-001")
    delta = next(row for row in com1.material_deltas if row.resource_id == "PATTY")
    assert (delta.before_shortage, delta.after_shortage, delta.delta, delta.unit) == (
        Decimal("0"), Decimal("40"), Decimal("40"), "pcs")
    assert com1.after_assessment.status is FeasibilityState.UNKNOWN
    com2 = next(row for row in result.impacts if row.commitment_id == "com-002")
    assert tuple(next(material.shortage for material in assessment.materials.materials
                      if material.commitment_id == "com-002" and material.sku_id == "PATTY")
                 for assessment in (com2.before_assessment, com2.after_assessment)) == (
                     Decimal("0"), Decimal("0"))


def test_two_affected_supplier_fixture_reports_material_deltas_separately_from_unknown_feasibility():
    scenario = build_two_affected_scenario()
    result = assess_impact(wrapped(scenario.before), wrapped(scenario.after),
        supplier_change(scenario.before, scenario.after, scenario.changed_delivery_id),
        before_commitments=core_commitments(scenario.before), after_commitments=core_commitments(scenario.after))

    assert result.candidate_commitment_ids == ("com-001", "com-002")
    assert result.confirmed_impacted_commitment_ids == ()
    assert result.unknown_commitment_ids == ("com-001", "com-002")
    deltas = {
        row.commitment_id: (
            next(delta.before_shortage for delta in row.material_deltas if delta.resource_id == "PATTY"),
            next(delta.after_shortage for delta in row.material_deltas if delta.resource_id == "PATTY"),
            next(delta.delta for delta in row.material_deltas if delta.resource_id == "PATTY"))
        for row in result.impacts
    }
    assert deltas == {"com-001": (Decimal("0"), Decimal("70"), Decimal("70")),
                      "com-002": (Decimal("0"), Decimal("40"), Decimal("40"))}


def test_inventory_lot_change_uses_lot_key_and_reports_only_its_actual_delta():
    scenario = build_supplier_delay_scenario()
    captured = scenario.before.captured_at + timedelta(minutes=30)
    data = scenario.before.model_dump(exclude_computed_fields=True)
    data.update(snapshot_id="snapshot-inventory-v2", snapshot_version=2, captured_at=captured)
    data["inventory_lots"] = tuple({**lot.model_dump(), "quantity": Decimal("70")} if lot.sku_id == "PATTY"
                                    else lot.model_dump() for lot in scenario.before.inventory_lots)
    data["sources"] = tuple({**source.model_dump(), "observed_at": captured,
        "evidence_refs": (*source.evidence_refs, "stock-adjustment-p4-v2")}
        if source.source_id == "source-inventory-001" else source.model_dump() for source in scenario.before.sources)
    after_snapshot = type(scenario.before).model_validate(data)
    change = OperationalChange(event_id="evt-inventory-1", tenant_id=after_snapshot.tenant_id,
        correlation_id="corr-inventory-1", event_type=OperationalChangeType.INVENTORY_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.INVENTORY_LOT, resource_id="lot-patty-001"),),
        evidence_refs=("stock-adjustment-p4-v2",))
    result = assess_impact(wrapped(scenario.before), wrapped(after_snapshot), change,
        before_commitments=core_commitments(scenario.before), after_commitments=core_commitments(after_snapshot))

    assert result.candidate_commitment_ids == ("com-001", "com-002")
    com1 = next(row for row in result.impacts if row.commitment_id == "com-001")
    delta = next(row for row in com1.material_deltas if row.resource_id == "PATTY")
    assert (delta.before_shortage, delta.after_shortage, delta.delta) == (
        Decimal("0"), Decimal("10"), Decimal("10"))
    assert result.unknown_commitment_ids == ("com-001", "com-002")


def test_sku_catalog_change_invalidates_bom_dependents_without_inventing_impact():
    scenario = build_supplier_delay_scenario()
    before = production_for(scenario.before)
    captured = before.operational.captured_at + timedelta(minutes=30)
    op_data = before.operational.model_dump(exclude_computed_fields=True)
    op_data.update(snapshot_id="snapshot-sku-change-v2", snapshot_version=2, captured_at=captured)
    op_data["sku_catalog"] = tuple({**sku, "supply_type": "MANUFACTURED",
        "source_refs": (*sku["source_refs"], "source-sku-p4-revision")}
        if sku["sku_id"] == "PATTY" else sku for sku in op_data["sku_catalog"])
    op_data["sources"] = tuple({**source, "observed_at": captured} for source in op_data["sources"])
    op_data["sources"] += ({"source_id": "source-sku-p4-revision", "tenant_id": before.operational.tenant_id,
        "kind": SourceKind.SKU_CATALOG, "source_ref": "synthetic://p2/phase4/sku-revision",
        "observed_at": captured, "valid_through": datetime.fromisoformat("2026-10-26T00:00:00+08:00"),
        "evidence_refs": ("sku-catalog-revision-p4-v2",), "supplier_delivery_evidence": ()},)
    after_operational = type(before.operational).model_validate(op_data)
    after = EvaluationSnapshot.model_validate({"operational": after_operational, "production": before.production,
        "as_of": captured, "current_snapshot_version": 2})
    change = OperationalChange(event_id="evt-sku-catalog", tenant_id=after.operational.tenant_id,
        correlation_id="corr-sku-catalog", event_type=OperationalChangeType.INVENTORY_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.SKU, resource_id="PATTY"),),
        evidence_refs=("sku-catalog-revision-p4-v2",))

    result = assess_impact(before, after, change, before_commitments=core_commitments(scenario.before),
        after_commitments=core_commitments(scenario.before))

    assert result.candidate_commitment_ids == ("com-001", "com-002")
    assert result.confirmed_impacted_commitment_ids == ()
    assert result.unknown_commitment_ids == ("com-001", "com-002")
    assert all(any(path.resource_key.kind is ResourceKind.SKU and
        path.resource_key.resource_id == "PATTY" for path in row.dependency_paths) for row in result.impacts)


def test_complete_supplier_recalculation_confirms_new_shortage_and_buffered_commitment():
    scenario = build_supplier_delay_scenario()
    before, after = production_for(scenario.before), production_for(scenario.after)
    commitments_before = core_commitments(scenario.before)
    commitments_after = core_commitments(scenario.after)
    result = assess_impact(before, after, supplier_change(scenario.before, scenario.after,
        scenario.changed_delivery_id), before_commitments=commitments_before, after_commitments=commitments_after)

    assert result.candidate_commitment_ids == ("com-001", "com-002")
    assert result.confirmed_impacted_commitment_ids == ("com-001",)
    assert result.verified_unaffected_commitment_ids == ("com-002",)
    assert result.unknown_commitment_ids == ()
    impacted = next(row for row in result.impacts if row.commitment_id == "com-001")
    unaffected = next(row for row in result.impacts if row.commitment_id == "com-002")
    assert (impacted.before_assessment.status, impacted.after_assessment.status) == (
        FeasibilityState.FEASIBLE, FeasibilityState.INFEASIBLE)
    assert unaffected.after_assessment.status is FeasibilityState.FEASIBLE
    assert any(buffer.value > 0 for buffer in unaffected.buffers)
    assert any(path.nodes[-1].resource_id == "com-001" and
               any(node.kind is ResourceKind.PRODUCTION_PLAN for node in path.nodes)
               for path in impacted.dependency_paths)
    assert any(intent.event.event_type == "commitment.at_risk" for intent in impacted.event_intents)
    assert unaffected.evidence_refs
    assert not any(intent.event.event_type == "commitment.at_risk" for intent in unaffected.event_intents)


def test_order_request_change_rechecks_new_confirmed_version_and_scopes_by_order():
    scenario = build_supplier_delay_scenario()
    captured = scenario.before.captured_at + timedelta(minutes=30)
    data = scenario.before.model_dump(exclude_computed_fields=True)
    data.update(snapshot_id="snapshot-order-v2", snapshot_version=2, captured_at=captured)
    rows = []
    for commitment in scenario.before.confirmed_commitments:
        row = commitment.model_dump()
        if row["commitment_id"] == "com-001":
            row["commitment_version"] = 2
            row["lines"] = ({**row["lines"][0], "quantity": Decimal("120")},)
        rows.append(row)
    data["confirmed_commitments"] = tuple(rows)
    data["sources"] = tuple({**source.model_dump(), "observed_at": captured,
        "evidence_refs": (*source.evidence_refs, "order-request-change-p4-v2")}
        if source.source_id == "source-commitments-001" else source.model_dump() for source in scenario.before.sources)
    after_snapshot = type(scenario.before).model_validate(data)
    before_core = core_commitments(scenario.before)
    after_core = core_commitments(after_snapshot)
    updated = next(row for row in after_core if row.commitment_id == "com-001").model_copy(update={
        "order_id": "order-com-001", "evidence_refs": ["order-request-change-p4-v2"], "updated_at": captured,
    })
    after_core = tuple(updated if row.commitment_id == "com-001" else row for row in after_core)
    change = OperationalChange(event_id="evt-order-change-1", tenant_id=after_snapshot.tenant_id,
        correlation_id="corr-order-change-1", event_type=OperationalChangeType.ORDER_REQUEST_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.ORDER, resource_id="order-com-001"),),
        evidence_refs=("order-request-change-p4-v2",))
    result = assess_impact(wrapped(scenario.before), wrapped(after_snapshot), change,
        before_commitments=before_core, after_commitments=after_core)

    assert result.candidate_commitment_ids == ("com-001",)
    assert result.unknown_commitment_ids == ("com-001",)
    delta = result.impacts[0].material_deltas[0]
    assert (delta.before_shortage, delta.after_shortage, delta.delta) == (
        Decimal("0"), Decimal("20"), Decimal("20"))


def test_resource_keyed_capacity_change_only_marks_overlapping_booking_and_preserves_inputs():
    scenario = build_supplier_delay_scenario()
    before = production_for(scenario.before)
    captured = before.operational.captured_at + timedelta(minutes=30)
    op_data = before.operational.model_dump(exclude_computed_fields=True)
    op_data.update(snapshot_id="snapshot-buffered-capacity-v2", snapshot_version=2, captured_at=captured)
    after_operational = type(before.operational).model_validate(op_data)
    p_data = before.production.model_dump(exclude_computed_fields=True)
    p_data["sources"] = tuple({**source, "observed_at": captured,
        "evidence_refs": ("synthetic-p4-capacity-change-v2",) if source["kind"] == "jobs"
        else source["evidence_refs"]} for source in p_data["sources"])
    p_data["jobs"] = (ProductionJob(
        job_id="external-job-p4-1", tenant_id=after_operational.tenant_id,
        resource_ids=("p4-line-1",), start_at=datetime.fromisoformat("2026-10-23T09:00:00+08:00"),
        end_at=datetime.fromisoformat("2026-10-23T10:00:00+08:00"), source_refs=("p4-jobs",),
    ),)
    after_production = ProductionData.model_validate(p_data)
    after = EvaluationSnapshot.model_validate({"operational": after_operational, "production": after_production,
        "as_of": captured, "current_snapshot_version": 2})
    change = OperationalChange(
        event_id="evt-capacity-job-1", tenant_id=after.operational.tenant_id, correlation_id="corr-p4-capacity-1",
        event_type=OperationalChangeType.CAPACITY_CHANGED, occurred_at=captured,
        before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.PRODUCTION_JOB, resource_id="external-job-p4-1"),),
        evidence_refs=("synthetic-p4-capacity-change-v2",),
    )
    original = (before.model_dump_json(), after.model_dump_json(), change.model_dump_json())
    result = assess_impact(before, after, change, before_commitments=core_commitments(scenario.before),
        after_commitments=core_commitments(scenario.after))

    assert result.candidate_commitment_ids == ("com-001", "com-002")
    assert result.confirmed_impacted_commitment_ids == ("com-001",)
    assert result.verified_unaffected_commitment_ids == ("com-002",)
    assert any(row.code == "JOB_CONFLICT" for row in next(
        row for row in result.impacts if row.commitment_id == "com-001").after_assessment.constraints)
    assert original == (before.model_dump_json(), after.model_dump_json(), change.model_dump_json())


def test_capacity_calendar_change_confirms_only_booking_that_loses_required_window():
    scenario = build_supplier_delay_scenario()
    before = production_for(scenario.before)
    captured = before.operational.captured_at + timedelta(minutes=30)
    op_data = before.operational.model_dump(exclude_computed_fields=True)
    op_data.update(snapshot_id="snapshot-calendar-capacity-v2", snapshot_version=2, captured_at=captured)
    revised_windows = tuple(CapacityWindow(start_at=datetime.combine(day, datetime.min.time()).replace(
            hour=start_hour, tzinfo=CAPTURE.tzinfo),
        end_at=datetime.combine(day, datetime.min.time()).replace(hour=end_hour, tzinfo=CAPTURE.tzinfo),
        available_minutes=minutes)
        for day in (datetime.fromisoformat("2026-10-23T00:00:00+08:00").date(),
                    datetime.fromisoformat("2026-10-24T00:00:00+08:00").date())
        for start_hour, end_hour, minutes in ((9, 10, Decimal("60")),
                                               (12, 17, Decimal("300"))))
    op_data["capacity_calendars"] = tuple({**calendar, "windows": revised_windows}
        if calendar["resource_id"] == "p4-line-1" else calendar for calendar in op_data["capacity_calendars"])
    op_data["sources"] = tuple({**source, "observed_at": captured,
        "evidence_refs": (*source["evidence_refs"], "capacity-revision-p4-v2")}
        if source["source_id"] == "source-capacity-001" else {**source, "observed_at": captured}
        for source in op_data["sources"])
    after_operational = type(before.operational).model_validate(op_data)
    p_data = before.production.model_dump(exclude_computed_fields=True)
    p_data["sources"] = tuple({**source, "observed_at": captured} for source in p_data["sources"])
    after_production = ProductionData.model_validate(p_data)
    after = EvaluationSnapshot.model_validate({"operational": after_operational, "production": after_production,
        "as_of": captured, "current_snapshot_version": 2})
    change = OperationalChange(event_id="evt-capacity-calendar", tenant_id=after.operational.tenant_id,
        correlation_id="corr-capacity-calendar", event_type=OperationalChangeType.CAPACITY_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.PRODUCTION_RESOURCE, resource_id="p4-line-1"),),
        evidence_refs=("capacity-revision-p4-v2",))

    result = assess_impact(before, after, change, before_commitments=core_commitments(scenario.before),
        after_commitments=core_commitments(scenario.before))

    assert result.candidate_commitment_ids == ("com-001", "com-002")
    assert result.confirmed_impacted_commitment_ids == ("com-001",)
    assert result.verified_unaffected_commitment_ids == ("com-002",)
    com1 = next(row for row in result.impacts if row.commitment_id == "com-001")
    assert any(row.code == "CAPACITY_WINDOW_VIOLATION" and row.is_new
        for row in com1.hard_constraint_deltas)


def test_unchanged_preexisting_shortage_is_not_reported_as_new_impact_or_risk():
    scenario = build_supplier_delay_scenario()
    before_snapshot = type(scenario.before).model_validate({
        **scenario.before.model_dump(exclude_computed_fields=True),
        "snapshot_id": "snapshot-preexisting-shortage-v1",
        "inventory_lots": tuple({**lot.model_dump(), "quantity": Decimal("50")} if lot.sku_id == "PATTY"
                                else lot.model_dump() for lot in scenario.before.inventory_lots),
    })
    before = production_for(before_snapshot)
    captured = before.operational.captured_at + timedelta(minutes=30)
    after_op_data = before.operational.model_dump(exclude_computed_fields=True)
    after_op_data.update(snapshot_id="snapshot-preexisting-shortage-v2", snapshot_version=2, captured_at=captured)
    after_operational = type(before.operational).model_validate(after_op_data)
    p_data = before.production.model_dump(exclude_computed_fields=True)
    p_data["sources"] = tuple({**source, "observed_at": captured,
        "evidence_refs": ("synthetic-p4-capacity-change-v2",) if source["kind"] == "jobs"
        else source["evidence_refs"]} for source in p_data["sources"])
    p_data["jobs"] = (ProductionJob(job_id="late-job", tenant_id=after_operational.tenant_id,
        resource_ids=("p4-line-1",), start_at=datetime.fromisoformat("2026-10-23T14:00:00+08:00"),
        end_at=datetime.fromisoformat("2026-10-23T15:00:00+08:00"), source_refs=("p4-jobs",)),)
    after_production = ProductionData.model_validate(p_data)
    after = EvaluationSnapshot.model_validate({"operational": after_operational, "production": after_production,
        "as_of": captured, "current_snapshot_version": 2})
    change = OperationalChange(event_id="evt-late-job", tenant_id=after.operational.tenant_id,
        correlation_id="corr-late-job", event_type=OperationalChangeType.CAPACITY_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.PRODUCTION_RESOURCE, resource_id="p4-line-1"),),
        evidence_refs=("synthetic-p4-capacity-change-v2",))

    result = assess_impact(before, after, change, before_commitments=core_commitments(before.operational),
        after_commitments=core_commitments(after.operational))
    com1 = next(row for row in result.impacts if row.commitment_id == "com-001")
    assert com1.before_assessment.status is FeasibilityState.INFEASIBLE
    assert com1.after_assessment.status is FeasibilityState.INFEASIBLE
    assert com1.material_deltas == ()
    assert com1.classification is ImpactClassification.PRE_EXISTING_UNCHANGED
    assert not any(intent.event.event_type == "commitment.at_risk" for intent in com1.event_intents)


def test_change_versions_tenant_scope_and_replay_idempotency_are_enforced():
    scenario = build_supplier_delay_scenario()
    before, after = wrapped(scenario.before), wrapped(scenario.after)
    change = supplier_change(scenario.before, scenario.after, scenario.changed_delivery_id)
    kwargs = dict(before_commitments=core_commitments(scenario.before),
                  after_commitments=core_commitments(scenario.after))
    first = assess_impact(before, after, change, **kwargs)
    again = assess_impact(before, after, change, **kwargs)
    assert first == again
    assert first.impact_id == again.impact_id
    assert tuple(intent.deduplication_key for intent in first.event_intents) == tuple(
        intent.deduplication_key for intent in again.event_intents)

    second_cause = change.model_copy(update={"event_id": "evt-supplier-eta-replay-2"})
    second_result = assess_impact(before, after, second_cause, **kwargs)
    assert tuple(intent.deduplication_key for intent in first.event_intents) == tuple(
        intent.deduplication_key for intent in second_result.event_intents)
    assert tuple(intent.event.event_id for intent in first.event_intents) != tuple(
        intent.event.event_id for intent in second_result.event_intents)

    stale = change.model_copy(update={"before_snapshot_version": 99})
    with pytest.raises(ValueError, match="snapshot version"):
        assess_impact(before, after, stale, **kwargs)
    cross_tenant = change.model_copy(update={"tenant_id": "tenant-other"})
    with pytest.raises(ValueError, match="tenant"):
        assess_impact(before, after, cross_tenant, **kwargs)


def test_stale_after_production_source_keeps_supplier_impact_unknown():
    scenario = build_supplier_delay_scenario()
    before = production_for(scenario.before)
    after_base = production_for(scenario.after)
    p_data = after_base.production.model_dump(exclude_computed_fields=True)
    stale_at = after_base.operational.captured_at - timedelta(minutes=1)
    p_data["sources"] = tuple({**source, "observed_at": stale_at, "valid_through": stale_at}
                              if source["kind"] == "processes" else source for source in p_data["sources"])
    after = EvaluationSnapshot.model_validate({"operational": after_base.operational,
        "production": ProductionData.model_validate(p_data), "as_of": after_base.as_of,
        "current_snapshot_version": after_base.current_snapshot_version})
    result = assess_impact(before, after, supplier_change(scenario.before, scenario.after,
        scenario.changed_delivery_id), before_commitments=core_commitments(scenario.before),
        after_commitments=core_commitments(scenario.after))

    com1 = next(row for row in result.impacts if row.commitment_id == "com-001")
    assert com1.after_assessment.status is FeasibilityState.UNKNOWN
    assert com1.after_assessment.evidence_complete is False
    assert com1.classification is ImpactClassification.UNKNOWN
    assert com1.material_deltas[0].delta == Decimal("40")
    assert com1.verified_material_deterioration
    assert any(intent.event.event_type == "operational.insufficient_data" for intent in com1.event_intents)


def test_stale_material_source_does_not_label_material_deterioration_verified():
    scenario = build_supplier_delay_scenario()
    before = production_for(scenario.before)
    after_base = production_for(scenario.after)
    stale_at = after_base.operational.captured_at - timedelta(minutes=1)
    op_data = after_base.operational.model_dump(exclude_computed_fields=True)
    op_data["sources"] = tuple({**source, "observed_at": stale_at, "valid_through": stale_at}
        if source["source_id"] == "source-inventory-001" else source for source in op_data["sources"])
    stale_operational = type(after_base.operational).model_validate(op_data)
    after = EvaluationSnapshot.model_validate({"operational": stale_operational,
        "production": after_base.production, "as_of": after_base.as_of,
        "current_snapshot_version": after_base.current_snapshot_version})
    result = assess_impact(before, after, supplier_change(scenario.before, scenario.after,
        scenario.changed_delivery_id), before_commitments=core_commitments(scenario.before),
        after_commitments=core_commitments(scenario.after))

    com1 = next(row for row in result.impacts if row.commitment_id == "com-001")
    assert com1.after_assessment.status is FeasibilityState.UNKNOWN
    assert com1.after_assessment.evidence_complete is False
    assert com1.classification is ImpactClassification.UNKNOWN
    assert not com1.verified_material_deterioration


def test_allocation_policy_uncertainty_does_not_become_a_confirmed_impact():
    scenario = build_supplier_delay_scenario()
    data = scenario.before.model_dump(exclude_computed_fields=True)
    data["snapshot_id"] = "snapshot-allocation-uncertain-v1"
    data["reservations"] = ()
    rows = []
    for commitment in data["confirmed_commitments"]:
        row = dict(commitment)
        line = dict(row["lines"][0])
        if row["commitment_id"] == "com-001":
            line.update(quantity=Decimal("80"), material_use_at=datetime.fromisoformat("2026-10-23T09:00:00+08:00"))
        else:
            line.update(quantity=Decimal("100"), material_use_at=datetime.fromisoformat("2026-10-23T12:00:00+08:00"))
        row["lines"] = (line,)
        rows.append(row)
    data["confirmed_commitments"] = tuple(rows)
    data["inventory_lots"] = tuple({**lot.model_dump(), "quantity": Decimal("130")} if lot.sku_id == "PATTY"
                                   else lot.model_dump() for lot in scenario.before.inventory_lots)
    baseline_op = type(scenario.before).model_validate(data)
    before = production_for(baseline_op)
    captured = before.operational.captured_at + timedelta(minutes=30)
    after_op_data = before.operational.model_dump(exclude_computed_fields=True)
    after_op_data.update(snapshot_id="snapshot-allocation-uncertain-v2", snapshot_version=2, captured_at=captured)
    after_op = type(before.operational).model_validate(after_op_data)
    p_data = before.production.model_dump(exclude_computed_fields=True)
    p_data["sources"] = tuple({**source, "observed_at": captured,
        "evidence_refs": ("synthetic-p4-capacity-change-v2",) if source["kind"] == "jobs"
        else source["evidence_refs"]} for source in p_data["sources"])
    p_data["jobs"] = (ProductionJob(job_id="nonoverlapping-job", tenant_id=after_op.tenant_id,
        resource_ids=("p4-line-1",), start_at=datetime.fromisoformat("2026-10-23T14:00:00+08:00"),
        end_at=datetime.fromisoformat("2026-10-23T15:00:00+08:00"), source_refs=("p4-jobs",)),)
    after = EvaluationSnapshot.model_validate({"operational": after_op, "production": ProductionData.model_validate(p_data),
        "as_of": captured, "current_snapshot_version": 2})
    change = OperationalChange(event_id="evt-allocation-capacity", tenant_id=after_op.tenant_id,
        correlation_id="corr-allocation-capacity", event_type=OperationalChangeType.CAPACITY_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.PRODUCTION_RESOURCE, resource_id="p4-line-1"),),
        evidence_refs=("synthetic-p4-capacity-change-v2",))
    result = assess_impact(before, after, change, before_commitments=core_commitments(before.operational),
        after_commitments=core_commitments(after.operational))

    com2 = next(row for row in result.impacts if row.commitment_id == "com-002")
    assert com2.before_assessment.status is FeasibilityState.UNKNOWN
    assert com2.after_assessment.status is FeasibilityState.UNKNOWN
    assert com2.after_assessment.evidence_complete is True
    assert com2.after_assessment.allocation_dependent is True
    assert com2.classification is ImpactClassification.UNKNOWN
    assert com2.material_deltas == ()
    assert not any(intent.event.event_type == "commitment.at_risk" for intent in com2.event_intents)

    conflict_data = after.production.model_dump(exclude_computed_fields=True)
    conflict_data["jobs"] = (ProductionJob(job_id="independent-hard-conflict",
        tenant_id=after.operational.tenant_id, resource_ids=("p4-line-1",),
        start_at=datetime.fromisoformat("2026-10-23T12:00:00+08:00"),
        end_at=datetime.fromisoformat("2026-10-23T13:00:00+08:00"), source_refs=("p4-jobs",)),)
    after_with_conflict = EvaluationSnapshot.model_validate({"operational": after.operational,
        "production": ProductionData.model_validate(conflict_data), "as_of": after.as_of,
        "current_snapshot_version": after.current_snapshot_version})
    conflict_change = change.model_copy(update={"event_id": "evt-allocation-independent-hard"})
    conflict_result = assess_impact(before, after_with_conflict, conflict_change,
        before_commitments=core_commitments(before.operational),
        after_commitments=core_commitments(after.operational))
    affected = next(row for row in conflict_result.impacts if row.commitment_id == "com-002")
    assert affected.after_assessment.status is FeasibilityState.INFEASIBLE
    assert affected.classification is ImpactClassification.CONFIRMED_IMPACT
    assert any(delta.code == "JOB_CONFLICT" and delta.is_new for delta in affected.hard_constraint_deltas)


def test_shortage_delta_is_independent_of_ambient_decimal_precision():
    scenario = build_supplier_delay_scenario()
    delayed_data = scenario.after.model_dump(exclude_computed_fields=True)
    delayed_data.update(snapshot_id="snapshot-precision-v1", snapshot_version=1)
    before = type(scenario.after).model_validate(delayed_data)
    captured = before.captured_at + timedelta(minutes=30)
    after_data = before.model_dump(exclude_computed_fields=True)
    after_data.update(snapshot_id="snapshot-precision-v2", snapshot_version=2, captured_at=captured)
    after_data["inventory_lots"] = tuple({**lot, "quantity": Decimal("78.766")} if lot["sku_id"] == "PATTY"
                                         else lot for lot in after_data["inventory_lots"])
    after_data["sources"] = tuple({**source, "observed_at": captured} for source in after_data["sources"])
    after_snapshot = type(before).model_validate(after_data)
    lot_id = next(lot.lot_id for lot in before.inventory_lots if lot.sku_id == "PATTY")
    source_refs = next(lot.source_refs for lot in after_snapshot.inventory_lots if lot.lot_id == lot_id)
    evidence_refs = tuple(sorted(ref for source in after_snapshot.sources if source.source_id in source_refs
                                 for ref in source.evidence_refs))
    change = OperationalChange(event_id="evt-precision", tenant_id=after_snapshot.tenant_id,
        correlation_id="corr-precision", event_type=OperationalChangeType.INVENTORY_CHANGED,
        occurred_at=after_snapshot.captured_at, before_snapshot_version=before.snapshot_version,
        after_snapshot_version=after_snapshot.snapshot_version,
        resource_keys=(ResourceKey(kind=ResourceKind.INVENTORY_LOT, resource_id=lot_id),),
        evidence_refs=evidence_refs)
    with localcontext(Context(prec=1)):
        result = assess_impact(wrapped(before), wrapped(after_snapshot), change,
            before_commitments=core_commitments(before), after_commitments=core_commitments(after_snapshot))
    delta = next(row.delta for row in next(row for row in result.impacts if row.commitment_id == "com-001").material_deltas
                 if row.resource_id == "PATTY")
    assert delta == Decimal("1.234")


def test_capacity_event_does_not_claim_concurrent_supplier_shortage_as_its_causal_impact():
    scenario = build_supplier_delay_scenario()
    before = production_for(scenario.before)
    after_base = production_for(scenario.after)
    captured = after_base.operational.captured_at
    production_data = after_base.production.model_dump(exclude_computed_fields=True)
    production_data["sources"] = tuple({**source, "observed_at": captured,
        "evidence_refs": (*source["evidence_refs"], "capacity-nonoverlap-job-p4-v2")
        if source["kind"] == "jobs" else source["evidence_refs"]}
        for source in production_data["sources"])
    production_data["jobs"] = (ProductionJob(job_id="capacity-nonoverlap-p4",
        tenant_id=after_base.operational.tenant_id, resource_ids=("p4-line-1",),
        start_at=datetime.fromisoformat("2026-10-23T14:00:00+08:00"),
        end_at=datetime.fromisoformat("2026-10-23T15:00:00+08:00"), source_refs=("p4-jobs",)),)
    after = EvaluationSnapshot.model_validate({"operational": after_base.operational,
        "production": ProductionData.model_validate(production_data), "as_of": captured,
        "current_snapshot_version": after_base.current_snapshot_version})
    change = OperationalChange(event_id="evt-capacity-with-supplier-delay",
        tenant_id=after.operational.tenant_id, correlation_id="corr-capacity-with-supplier-delay",
        event_type=OperationalChangeType.CAPACITY_CHANGED, occurred_at=captured,
        before_snapshot_version=before.operational.snapshot_version,
        after_snapshot_version=after.operational.snapshot_version,
        resource_keys=(ResourceKey(kind=ResourceKind.PRODUCTION_JOB, resource_id="capacity-nonoverlap-p4"),),
        evidence_refs=("capacity-nonoverlap-job-p4-v2",))

    result = assess_impact(before, after, change,
        before_commitments=core_commitments(scenario.before),
        after_commitments=core_commitments(scenario.after))

    com1 = next(row for row in result.impacts if row.commitment_id == "com-001")
    assert com1.before_assessment.status is FeasibilityState.FEASIBLE
    assert com1.after_assessment.status is FeasibilityState.INFEASIBLE
    assert next(delta.delta for delta in com1.material_deltas if delta.resource_id == "PATTY") == Decimal("40")
    assert com1.verified_material_deterioration
    assert com1.classification is ImpactClassification.UNKNOWN
    assert "UNATTRIBUTED_CONCURRENT_DEPENDENCY_CHANGE" in com1.reasons
    assert com1.commitment_id not in result.confirmed_impacted_commitment_ids
    assert not any(intent.event.event_type == "commitment.at_risk" for intent in com1.event_intents)
    assert result.verified_unaffected_commitment_ids == ("com-002",)


def test_multi_resource_capacity_event_confirms_when_all_changed_jobs_are_declared():
    scenario = build_supplier_delay_scenario()
    before = production_for(scenario.before)
    captured = before.operational.captured_at + timedelta(minutes=30)
    operational_data = before.operational.model_dump(exclude_computed_fields=True)
    operational_data.update(snapshot_id="snapshot-multi-capacity-v2", snapshot_version=2,
                            captured_at=captured)
    after_operational = type(before.operational).model_validate(operational_data)
    production_data = before.production.model_dump(exclude_computed_fields=True)
    conflict_ref = "capacity-conflict-job-p4-v2"
    unrelated_ref = "capacity-nonoverlap-job-p4-v2"
    production_data["sources"] = tuple({**source, "observed_at": captured,
        "evidence_refs": (*source["evidence_refs"], conflict_ref) if source["source_id"] == "p4-jobs"
        else source["evidence_refs"]} for source in production_data["sources"]) + (
        ProductionSource(source_id="p4-jobs-nonoverlap", tenant_id=after_operational.tenant_id,
            kind="jobs", source_ref="synthetic://p2/phase4/jobs/nonoverlap", observed_at=captured,
            valid_through=datetime.fromisoformat("2026-10-26T00:00:00+08:00"),
            evidence_refs=(unrelated_ref,)),)
    production_data["jobs"] = (
        ProductionJob(job_id="capacity-conflict-p4", tenant_id=after_operational.tenant_id,
            resource_ids=("p4-line-1",), start_at=datetime.fromisoformat("2026-10-23T09:00:00+08:00"),
            end_at=datetime.fromisoformat("2026-10-23T10:00:00+08:00"), source_refs=("p4-jobs",)),
        ProductionJob(job_id="capacity-nonoverlap-p4", tenant_id=after_operational.tenant_id,
            resource_ids=("p4-line-1",), start_at=datetime.fromisoformat("2026-10-23T14:00:00+08:00"),
            end_at=datetime.fromisoformat("2026-10-23T15:00:00+08:00"),
            source_refs=("p4-jobs-nonoverlap",)),
    )
    after = EvaluationSnapshot.model_validate({"operational": after_operational,
        "production": ProductionData.model_validate(production_data), "as_of": captured,
        "current_snapshot_version": 2})
    change = OperationalChange(event_id="evt-multi-capacity", tenant_id=after_operational.tenant_id,
        correlation_id="corr-multi-capacity", event_type=OperationalChangeType.CAPACITY_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.PRODUCTION_JOB, resource_id="capacity-conflict-p4"),
                       ResourceKey(kind=ResourceKind.PRODUCTION_JOB, resource_id="capacity-nonoverlap-p4")),
        evidence_refs=(conflict_ref, unrelated_ref))

    result = assess_impact(before, after, change, before_commitments=core_commitments(scenario.before),
        after_commitments=core_commitments(scenario.before))

    assert result.confirmed_impacted_commitment_ids == ("com-001",)
    assert result.verified_unaffected_commitment_ids == ("com-002",)


def test_multi_lot_change_accepts_distinct_resource_linked_evidence():
    before_snapshot = build_supplier_delay_scenario().before
    captured = before_snapshot.captured_at + timedelta(minutes=30)
    data = before_snapshot.model_dump(exclude_computed_fields=True)
    data.update(snapshot_id="snapshot-two-lot-change-v2", snapshot_version=2, captured_at=captured)
    selected = before_snapshot.inventory_lots[:2]
    lot_sources = []
    evidence_refs = []
    resource_keys = []
    for index, lot in enumerate(selected, start=1):
        source_id = f"source-lot-change-{index}"
        evidence_ref = f"lot-change-evidence-{index}-v2"
        lot_sources.append(SourceEvidence(source_id=source_id, tenant_id=before_snapshot.tenant_id,
            kind=SourceKind.INVENTORY, source_ref=f"synthetic://p2/inventory/lot-{index}/v2",
            observed_at=captured, valid_through=datetime.fromisoformat("2026-10-26T00:00:00+08:00"),
            evidence_refs=(evidence_ref,)))
        evidence_refs.append(evidence_ref)
        resource_keys.append(ResourceKey(kind=ResourceKind.INVENTORY_LOT, resource_id=lot.lot_id))
    source_id_by_lot = {lot.lot_id: f"source-lot-change-{index}"
                        for index, lot in enumerate(selected, start=1)}
    data["inventory_lots"] = tuple({**lot.model_dump(), "source_refs": (source_id_by_lot[lot.lot_id],),
        "quantity": lot.quantity + Decimal("1")} if lot.lot_id in source_id_by_lot else lot.model_dump()
        for lot in before_snapshot.inventory_lots)
    data["sources"] = (*data["sources"], *lot_sources)
    after_snapshot = type(before_snapshot).model_validate(data)
    change = OperationalChange(event_id="evt-two-lot-change", tenant_id=after_snapshot.tenant_id,
        correlation_id="corr-two-lot-change", event_type=OperationalChangeType.INVENTORY_CHANGED,
        occurred_at=captured, before_snapshot_version=before_snapshot.snapshot_version,
        after_snapshot_version=after_snapshot.snapshot_version, resource_keys=tuple(resource_keys),
        evidence_refs=tuple(evidence_refs))

    result = assess_impact(wrapped(before_snapshot), wrapped(after_snapshot), change,
        before_commitments=core_commitments(before_snapshot), after_commitments=core_commitments(after_snapshot))

    assert len(result.candidate_commitment_ids) > 0


def test_inventory_event_rejects_unaccounted_evidence_reference():
    scenario = build_supplier_delay_scenario()
    captured = scenario.before.captured_at + timedelta(minutes=30)
    data = scenario.before.model_dump(exclude_computed_fields=True)
    data.update(snapshot_id="snapshot-inventory-unaccounted-v2", snapshot_version=2, captured_at=captured)
    data["inventory_lots"] = tuple({**lot.model_dump(), "quantity": Decimal("70")} if lot.lot_id == "lot-patty-001"
        else lot.model_dump() for lot in scenario.before.inventory_lots)
    data["sources"] = tuple({**source.model_dump(), "observed_at": captured,
        "evidence_refs": (*source.evidence_refs, "stock-adjustment-p4-v2")}
        if source.source_id == "source-inventory-001" else source.model_dump() for source in scenario.before.sources)
    after_snapshot = type(scenario.before).model_validate(data)
    change = OperationalChange(event_id="evt-inventory-unaccounted", tenant_id=after_snapshot.tenant_id,
        correlation_id="corr-inventory-unaccounted", event_type=OperationalChangeType.INVENTORY_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.INVENTORY_LOT, resource_id="lot-patty-001"),),
        evidence_refs=("stock-adjustment-p4-v2", "unrelated-unaccounted-evidence"))

    with pytest.raises(ValueError, match="change evidence is not linked"):
        assess_impact(wrapped(scenario.before), wrapped(after_snapshot), change,
            before_commitments=core_commitments(scenario.before), after_commitments=core_commitments(after_snapshot))


def test_inventory_event_rejects_resource_without_actual_change():
    scenario = build_supplier_delay_scenario()
    captured = scenario.before.captured_at + timedelta(minutes=30)
    data = scenario.before.model_dump(exclude_computed_fields=True)
    data.update(snapshot_id="snapshot-inventory-partial-v2", snapshot_version=2, captured_at=captured)
    data["inventory_lots"] = tuple({**lot.model_dump(), "quantity": Decimal("70")} if lot.lot_id == "lot-patty-001"
        else lot.model_dump() for lot in scenario.before.inventory_lots)
    data["sources"] = tuple({**source.model_dump(), "observed_at": captured,
        "evidence_refs": (*source.evidence_refs, "stock-adjustment-p4-v2")}
        if source.source_id == "source-inventory-001" else source.model_dump() for source in scenario.before.sources)
    after_snapshot = type(scenario.before).model_validate(data)
    change = OperationalChange(event_id="evt-inventory-partial", tenant_id=after_snapshot.tenant_id,
        correlation_id="corr-inventory-partial", event_type=OperationalChangeType.INVENTORY_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.INVENTORY_LOT, resource_id="lot-patty-001"),
                       ResourceKey(kind=ResourceKind.INVENTORY_LOT, resource_id="lot-bun-001")),
        evidence_refs=("stock-adjustment-p4-v2",))

    with pytest.raises(ValueError, match="no before/after data change"):
        assess_impact(wrapped(scenario.before), wrapped(after_snapshot), change,
            before_commitments=core_commitments(scenario.before), after_commitments=core_commitments(after_snapshot))


def test_supplier_eta_event_still_requires_typed_eta_change_evidence():
    scenario = build_supplier_delay_scenario()
    valid_change = supplier_change(scenario.before, scenario.after, scenario.changed_delivery_id)
    unsupported = valid_change.model_copy(update={"evidence_refs": ("supplier-quote-v1",)})

    with pytest.raises(ValueError, match="requires its linked ETA-change evidence"):
        assess_impact(wrapped(scenario.before), wrapped(scenario.after), unsupported,
            before_commitments=core_commitments(scenario.before), after_commitments=core_commitments(scenario.after))


def _retime_commitment(snapshot, *, snapshot_id, version, captured_at, deadline, material_use_at=None,
                       commitment_version=None, evidence_ref=None):
    data = snapshot.model_dump(exclude_computed_fields=True)
    data.update(snapshot_id=snapshot_id, snapshot_version=version, captured_at=captured_at)
    commitments = []
    for row in data["confirmed_commitments"]:
        if row["commitment_id"] != "com-001":
            commitments.append(row)
            continue
        lines = row["lines"]
        if material_use_at is not None:
            lines = ({**lines[0], "material_use_at": material_use_at},)
        row = {**row, "delivery_deadline": deadline, "lines": lines,
            "commitment_version": commitment_version or row["commitment_version"]}
        commitments.append(row)
    data["confirmed_commitments"] = tuple(commitments)
    if evidence_ref:
        data["sources"] = tuple({**source, "observed_at": captured_at,
            "evidence_refs": (*source["evidence_refs"], evidence_ref)}
            if source["source_id"] == "source-commitments-001" else source
            for source in data["sources"])
    return type(snapshot).model_validate(data)


def test_deadline_extension_is_reported_as_improved_existing_lateness_not_new_impact():
    original = build_supplier_delay_scenario().before
    start = datetime.fromisoformat("2026-10-23T09:00:00+08:00")
    before_operational = _retime_commitment(original, snapshot_id="snapshot-deadline-improve-v1", version=1,
        captured_at=original.captured_at, deadline=datetime.fromisoformat("2026-10-23T11:00:00+08:00"),
        material_use_at=start)
    captured = original.captured_at + timedelta(minutes=30)
    after_operational = _retime_commitment(before_operational, snapshot_id="snapshot-deadline-improve-v2", version=2,
        captured_at=captured, deadline=datetime.fromisoformat("2026-10-23T11:05:00+08:00"), material_use_at=start,
        commitment_version=2, evidence_ref="deadline-extension-p4-v2")
    before = production_for(before_operational)
    after = production_for(after_operational)
    change = OperationalChange(event_id="evt-deadline-extension", tenant_id=after_operational.tenant_id,
        correlation_id="corr-deadline-extension", event_type=OperationalChangeType.ORDER_REQUEST_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.COMMITMENT, resource_id="com-001"),),
        evidence_refs=("deadline-extension-p4-v2",))

    result = assess_impact(before, after, change, before_commitments=core_commitments(before_operational),
        after_commitments=core_commitments(after_operational))

    impact = next(row for row in result.impacts if row.commitment_id == "com-001")
    assert impact.before_assessment.status is FeasibilityState.INFEASIBLE
    assert impact.after_assessment.status is FeasibilityState.INFEASIBLE
    before_operation = next(row for row in impact.before_assessment.capacity.operations
                            if row.commitment_id == "com-001")
    after_operation = next(row for row in impact.after_assessment.capacity.operations
                           if row.commitment_id == "com-001")
    assert before_operation.finish_at + timedelta(minutes=30) == datetime.fromisoformat(
        "2026-10-23T11:10:00+08:00")
    assert after_operation.finish_at + timedelta(minutes=30) == datetime.fromisoformat(
        "2026-10-23T11:10:00+08:00")
    deadline_delta = next(delta for delta in impact.hard_constraint_deltas if delta.code == "DELIVERY_DEADLINE")
    assert (deadline_delta.before_shortage, deadline_delta.after_shortage, deadline_delta.delta,
            deadline_delta.severity_change) == (Decimal("10"), Decimal("5"), Decimal("-5"), "IMPROVED")
    assert impact.classification is ImpactClassification.PRE_EXISTING_UNCHANGED
    assert impact.commitment_id not in result.confirmed_impacted_commitment_ids


def test_worsened_existing_deadline_violation_uses_numeric_lateness_delta():
    original = build_supplier_delay_scenario().before
    start = datetime.fromisoformat("2026-10-23T10:40:00+08:00")
    deadline = datetime.fromisoformat("2026-10-23T12:30:00+08:00")
    before_operational = _retime_commitment(original, snapshot_id="snapshot-deadline-worsen-v1", version=1,
        captured_at=original.captured_at, deadline=deadline, material_use_at=start)
    captured = original.captured_at + timedelta(minutes=30)
    after_operational = _retime_commitment(before_operational, snapshot_id="snapshot-deadline-worsen-v2", version=2,
        captured_at=captured, deadline=deadline, material_use_at=start)
    before = production_for(before_operational)
    after_base = production_for(after_operational)
    production_data = after_base.production.model_dump(exclude_computed_fields=True)
    production_data["sources"] = tuple({**source, "observed_at": captured,
        "evidence_refs": (*source["evidence_refs"], "process-lead-change-p4-v2")
        if source["kind"] == "processes" else source["evidence_refs"]}
        for source in production_data["sources"])
    production_data["processes"] = tuple(ProductionProcess.model_validate({**process.model_dump(),
        "delivery_lead_minutes": Decimal("40")}) if process.sku_id == "BURGER" else process
        for process in after_base.production.processes)
    after = EvaluationSnapshot.model_validate({"operational": after_base.operational,
        "production": ProductionData.model_validate(production_data), "as_of": captured,
        "current_snapshot_version": 2})
    change = OperationalChange(event_id="evt-process-lead-change", tenant_id=after_operational.tenant_id,
        correlation_id="corr-process-lead-change", event_type=OperationalChangeType.CAPACITY_CHANGED,
        occurred_at=captured, before_snapshot_version=1, after_snapshot_version=2,
        resource_keys=(ResourceKey(kind=ResourceKind.PRODUCTION_RESOURCE, resource_id="p4-line-1"),),
        evidence_refs=("process-lead-change-p4-v2",))

    result = assess_impact(before, after, change, before_commitments=core_commitments(before_operational),
        after_commitments=core_commitments(after_operational))

    impact = next(row for row in result.impacts if row.commitment_id == "com-001")
    before_operation = next(row for row in impact.before_assessment.capacity.operations
                            if row.commitment_id == "com-001")
    after_operation = next(row for row in impact.after_assessment.capacity.operations
                           if row.commitment_id == "com-001")
    assert before_operation.finish_at + timedelta(minutes=30) == datetime.fromisoformat(
        "2026-10-23T12:50:00+08:00")
    assert after_operation.finish_at + timedelta(minutes=40) == datetime.fromisoformat(
        "2026-10-23T13:00:00+08:00")
    deadline_delta = next(delta for delta in impact.hard_constraint_deltas if delta.code == "DELIVERY_DEADLINE")
    assert (deadline_delta.before_shortage, deadline_delta.after_shortage, deadline_delta.delta,
            deadline_delta.severity_change) == (Decimal("20"), Decimal("30"), Decimal("10"), "WORSENED")
    assert impact.classification is ImpactClassification.CONFIRMED_IMPACT
