import json
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.core.schemas import Commitment
from app.db.base import Base
from app.feasibility.demo_seed import (
    DemoSnapshotSeedConflict,
    build_upstream_demo_fixture,
    seed_upstream_demo_snapshots,
)
from app.feasibility.impact import ImpactClassification
from app.feasibility.persisted_sources import (
    OperationalSnapshotRecord,
    SupplierDelayEventRecord,
)
from app.feasibility.supplier_pipeline import SupplierDelayInputs, recalculate_supplier_delay

TENANT = "tenant_upstream_demo_test"


def _commitment(commitment_id: str, quantity: str, *, version: int = 3) -> Commitment:
    return Commitment.model_validate({
        "tenant_id": TENANT,
        "commitment_id": commitment_id,
        "order_id": f"order-{commitment_id}",
        "customer_id": f"customer-{commitment_id}",
        "terms": {
            "sku": "BURGER",
            "quantity": quantity,
            "unit": "pcs",
            "deadline": "2026-10-24T15:00:00+08:00",
        },
        "agreement_state": "CONFIRMED",
        "feasibility_state": "NOT_ASSESSED",
        "risk_state": "NORMAL",
        "recovery_state": "NONE",
        "fulfilment_state": "NOT_STARTED",
        "commitment_version": version,
        "evidence_refs": [f"synthetic-confirmation-{commitment_id}"],
        "updated_at": datetime(2026, 10, 23, tzinfo=UTC),
    })


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        OperationalSnapshotRecord.__table__,
        SupplierDelayEventRecord.__table__,
    ])
    return engine, Session(engine)


def test_demo_fixture_reuses_p2_evaluator_and_preserves_unaffected_commitment():
    target, control = _commitment("com-upstream-target", "100"), _commitment("com-upstream-control", "20")
    before, after, request = build_upstream_demo_fixture(TENANT, target, control)

    inputs = SupplierDelayInputs(
        request=request,
        before_snapshot_id=before.operational.snapshot_id,
        after_snapshot_id=after.operational.snapshot_id,
        previous_eta=next(row for row in before.operational.incoming_deliveries if row.delivery_id == "delivery-patty-001").expected_at,
        updated_eta=next(row for row in after.operational.incoming_deliveries if row.delivery_id == "delivery-patty-001").expected_at,
        before=before,
        after=after,
        before_commitments=(target, control),
        after_commitments=(target, control),
    )

    result = recalculate_supplier_delay(inputs, tenant_id=TENANT)
    impacts = {row.commitment_id: row for row in result.impacts}
    assert before.current_snapshot_version == before.operational.snapshot_version == 1
    assert after.current_snapshot_version == after.operational.snapshot_version == 2
    assert impacts[target.commitment_id].classification is ImpactClassification.CONFIRMED_IMPACT
    assert impacts[target.commitment_id].after_assessment.status.value == "INFEASIBLE"
    assert impacts[control.commitment_id].classification is ImpactClassification.VERIFIED_UNAFFECTED
    assert impacts[control.commitment_id].after_assessment.status.value == "FEASIBLE"
    assert request.change.tenant_id == TENANT


def test_seed_is_idempotent_and_does_not_commit_or_duplicate_rows():
    engine, session = _session()
    target, control = _commitment("com-upstream-target", "100"), _commitment("com-upstream-control", "20")
    try:
        first = seed_upstream_demo_snapshots(session, TENANT, target, control)
        assert first.created is True
        assert session.scalar(select(OperationalSnapshotRecord).where(
            OperationalSnapshotRecord.tenant_id == TENANT,
            OperationalSnapshotRecord.is_current.is_(True),
        )).snapshot_version == 1

        second = seed_upstream_demo_snapshots(session, TENANT, target, control)
        assert second.created is False
        assert session.query(OperationalSnapshotRecord).filter_by(tenant_id=TENANT).count() == 2
        assert session.in_transaction()
    finally:
        session.close()
        engine.dispose()


def test_seed_refuses_partial_or_different_persisted_snapshot_history():
    engine, session = _session()
    target, control = _commitment("com-upstream-target", "100"), _commitment("com-upstream-control", "20")
    try:
        first = seed_upstream_demo_snapshots(session, TENANT, target, control)
        session.commit()
        session.delete(session.scalar(select(OperationalSnapshotRecord).where(
            OperationalSnapshotRecord.tenant_id == TENANT,
            OperationalSnapshotRecord.snapshot_version == 2,
        )))
        session.commit()

        with pytest.raises(DemoSnapshotSeedConflict, match="not the exact two-version"):
            seed_upstream_demo_snapshots(session, TENANT, target, control)
        assert first.created is True
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "tenant_other"),
    ("agreement_state", "OFFERED"),
])
def test_fixture_rejects_wrong_tenant_or_unconfirmed_commitment(field, value):
    target, control = _commitment("com-upstream-target", "100"), _commitment("com-upstream-control", "20")
    payload = target.model_dump(mode="json")
    payload[field] = value
    mismatched = Commitment.model_validate(payload)

    with pytest.raises(DomainError):
        build_upstream_demo_fixture(TENANT, mismatched, control)


def test_seed_replay_after_durable_delay_accepts_only_matching_event_digest():
    target, control = _commitment("com-upstream-target", "100"), _commitment("com-upstream-control", "20")
    engine, session = _session()
    try:
        seeded = seed_upstream_demo_snapshots(session, TENANT, target, control)
        rows = session.scalars(select(OperationalSnapshotRecord).where(
            OperationalSnapshotRecord.tenant_id == TENANT,
        ).order_by(OperationalSnapshotRecord.snapshot_version)).all()
        rows[0].is_current = False
        rows[1].is_current = True
        digest = sha256(json.dumps(
            seeded.supplier_delay.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        session.add(SupplierDelayEventRecord(
            tenant_id=TENANT,
            event_id=seeded.supplier_delay.change.event_id,
            before_snapshot_version=1,
            after_snapshot_version=2,
            evidence_ref=seeded.supplier_delay.source_evidence.evidence_ref,
            impact_id="impact-demo-test",
            event_digest=digest,
            impact_payload={},
            occurred_at=seeded.supplier_delay.change.occurred_at,
        ))
        session.flush()

        replay = seed_upstream_demo_snapshots(session, TENANT, target, control)
        assert replay.created is False
        assert rows[0].is_current is False and rows[1].is_current is True
        assert session.query(OperationalSnapshotRecord).filter_by(tenant_id=TENANT).count() == 2
    finally:
        session.close()
        engine.dispose()
