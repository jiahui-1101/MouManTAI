"""Deterministic, isolated P2 source fixture for the upstream synthetic demo.

The fixture reuses P2's published supplier-delay scenario and persisted
snapshot schema. It never writes Core Commitment state. A caller-owned
transaction is required; the CLI additionally requires explicit isolated-demo
and disposable-database gates.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.schemas import Commitment
from app.core.service import CommitmentService

from .api_schemas import SupplierDelayRequest
from .persisted_sources import (
    OperationalSnapshotRecord,
    SupplierDelayEventRecord,
    stage_snapshot,
)
from .pipeline_fixtures import build_pipeline_example
from .production import EvaluationSnapshot


class DemoSnapshotSeedConflict(RuntimeError):
    """Persisted fixture state differs from the deterministic demo contract."""


@dataclass(frozen=True)
class UpstreamDemoSnapshotSeed:
    before: EvaluationSnapshot
    after: EvaluationSnapshot
    supplier_delay: SupplierDelayRequest
    created: bool


def _set_tenant(value, old_tenant: str, tenant_id: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "tenant_id" and child == old_tenant:
                value[key] = tenant_id
            else:
                _set_tenant(child, old_tenant, tenant_id)
    elif isinstance(value, list):
        for child in value:
            _set_tenant(child, old_tenant, tenant_id)


def _checked_commitment(commitment: Commitment, tenant_id: str, expected_quantity: str) -> None:
    if commitment.tenant_id != tenant_id or commitment.agreement_state.value != "CONFIRMED":
        raise DomainError(
            "P2_DEMO_COMMITMENT_NOT_CONFIRMED",
            "P2 demo source requires tenant-matched confirmed Core commitments",
            status_code=409,
        )
    if (
        commitment.terms.sku != "BURGER"
        or commitment.terms.quantity != Decimal(expected_quantity)
        or commitment.terms.unit != "pcs"
        or commitment.terms.deadline is None
        or commitment.terms.deadline.tzinfo is None
    ):
        raise DomainError(
            "P2_DEMO_COMMITMENT_TERMS_MISMATCH",
            f"P2 demo source requires {expected_quantity} offset-aware BURGER pcs",
            status_code=409,
        )


def build_upstream_demo_fixture(
    tenant_id: str,
    affected_commitment: Commitment,
    unaffected_commitment: Commitment,
) -> tuple[EvaluationSnapshot, EvaluationSnapshot, SupplierDelayRequest]:
    """Bind P2's known one-affected/one-unaffected fixture to real Core rows."""
    if not tenant_id.strip():
        raise ValueError("tenant_id is required")
    _checked_commitment(affected_commitment, tenant_id, "100")
    _checked_commitment(unaffected_commitment, tenant_id, "20")
    if affected_commitment.commitment_id == unaffected_commitment.commitment_id:
        raise ValueError("affected and unaffected commitments must be distinct")

    inputs = build_pipeline_example(mode="complete")
    old_tenant = inputs.before.operational.tenant_id
    tenant_fingerprint = sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    snapshot_prefix = f"snapshot-upstream-{tenant_fingerprint}"
    commitment_map = {
        "com-001": affected_commitment,
        "com-002": unaffected_commitment,
    }

    def bind_snapshot(snapshot: EvaluationSnapshot, version: int) -> EvaluationSnapshot:
        data = snapshot.model_dump(mode="json", exclude_computed_fields=True)
        _set_tenant(data, old_tenant, tenant_id)
        operational = data["operational"]
        operational["snapshot_id"] = f"{snapshot_prefix}-v{version}"
        operational["snapshot_version"] = version
        data["current_snapshot_version"] = version

        for source in operational["sources"]:
            source["source_ref"] = f"synthetic://p2/upstream/{tenant_fingerprint}/{source['source_id']}"

        for row in operational["confirmed_commitments"]:
            original_id = row["commitment_id"]
            core = commitment_map.get(original_id)
            if core is None:
                raise ValueError("P2 source fixture contains an unexpected commitment")
            row.update(
                tenant_id=tenant_id,
                commitment_id=core.commitment_id,
                commitment_version=core.commitment_version,
                delivery_deadline=core.terms.deadline.isoformat(),
            )
            line = row["lines"][0]
            line.update(
                line_id=f"{core.commitment_id}-line-1",
                sku_id=core.terms.sku,
                quantity=str(core.terms.quantity),
                unit=core.terms.unit,
            )

        for reservation in operational["reservations"]:
            if reservation["commitment_id"] == "com-002":
                reservation["commitment_id"] = unaffected_commitment.commitment_id
                reservation["reservation_id"] = f"reservation-{unaffected_commitment.commitment_id}-patty"

        production = data.get("production")
        if production is not None:
            for plan in production["plans"]:
                core = commitment_map.get(plan["commitment_id"])
                if core is None:
                    raise ValueError("P2 production fixture contains an unexpected commitment")
                plan["commitment_id"] = core.commitment_id
                plan["commitment_version"] = core.commitment_version
                plan["line_id"] = f"{core.commitment_id}-line-1"

        return EvaluationSnapshot.model_validate(data)

    before = bind_snapshot(inputs.before, 1)
    after = bind_snapshot(inputs.after, 2)
    request_data = inputs.request.model_dump(mode="json")
    event_id = f"evt-upstream-delay-{tenant_fingerprint}"
    request_data["change"].update(
        tenant_id=tenant_id,
        event_id=event_id,
        correlation_id=f"corr-upstream-delay-{tenant_fingerprint}",
    )
    request_data["source_evidence"]["tenant_id"] = tenant_id
    supplier_delay = SupplierDelayRequest.model_validate(request_data)
    return before, after, supplier_delay


def seed_upstream_demo_snapshots(
    db: Session,
    tenant_id: str,
    affected_commitment: Commitment,
    unaffected_commitment: Commitment,
) -> UpstreamDemoSnapshotSeed:
    """Create or verify the two immutable snapshot rows in the caller transaction.

    A replay after the supplier-delay event is accepted only when the persisted
    event digest matches and snapshot 2 is current. Partial or conflicting state
    is rejected; this function never resets the active snapshot.
    """
    before, after, supplier_delay = build_upstream_demo_fixture(
        tenant_id, affected_commitment, unaffected_commitment
    )
    expected = {1: before, 2: after}
    rows = db.scalars(
        select(OperationalSnapshotRecord)
        .where(OperationalSnapshotRecord.tenant_id == tenant_id)
        .order_by(OperationalSnapshotRecord.snapshot_version)
    ).all()

    if not rows:
        stage_snapshot(db, before, current=True)
        stage_snapshot(db, after, current=False)
        return UpstreamDemoSnapshotSeed(before, after, supplier_delay, created=True)

    if len(rows) != 2:
        raise DemoSnapshotSeedConflict("Existing tenant snapshot history is not the exact two-version demo fixture")

    for row in rows:
        snapshot = expected.get(row.snapshot_version)
        if (
            snapshot is None
            or row.snapshot_id != snapshot.operational.snapshot_id
            or row.payload != snapshot.model_dump(mode="json", exclude_computed_fields=True)
        ):
            raise DemoSnapshotSeedConflict("Existing P2 snapshot differs from the deterministic demo fixture")

    digest = sha256(
        json.dumps(
            supplier_delay.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    event = db.get(
        SupplierDelayEventRecord,
        (tenant_id, supplier_delay.change.event_id),
    )
    if event is not None and event.event_digest != digest:
        raise DemoSnapshotSeedConflict("Persisted supplier event ID has conflicting content")

    expected_current = {1: event is None, 2: event is not None}
    if any(row.is_current != expected_current[row.snapshot_version] for row in rows):
        raise DemoSnapshotSeedConflict("P2 demo current-snapshot state is inconsistent with supplier event history")

    return UpstreamDemoSnapshotSeed(before, after, supplier_delay, created=False)


def _run_cli() -> None:
    parser = argparse.ArgumentParser(description="Seed/verify isolated upstream P2 demo snapshots")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--affected-commitment-id", required=True)
    parser.add_argument("--unaffected-commitment-id", required=True)
    args = parser.parse_args()

    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1" or os.getenv("P2_DEMO_SEED_APPROVED") != "1":
        raise SystemExit("Refusing P2 demo seeding without explicit isolated-demo approval flags")
    database_url = os.getenv("DATABASE_URL", "")
    try:
        database_name = (make_url(database_url).database or "").lower()
    except ArgumentError:
        database_name = ""
    if not any(token in database_name for token in ("test", "demo")):
        raise SystemExit("Refusing P2 demo seeding: DATABASE_URL must name a disposable test/demo database")

    from app.db.session import SessionLocal

    service = CommitmentService()
    context = RequestContext(
        tenant_id=args.tenant_id,
        actor_id="service_p2_feasibility",
        actor_role="SERVICE",
        correlation_id=f"corr-p2-demo-seed-{sha256(args.tenant_id.encode()).hexdigest()[:12]}",
    )
    with SessionLocal.begin() as db:
        affected = service.get(db, context, args.affected_commitment_id)
        unaffected = service.get(db, context, args.unaffected_commitment_id)
        result = seed_upstream_demo_snapshots(db, args.tenant_id, affected, unaffected)

    print(json.dumps({
        "created": result.created,
        "tenant_id": args.tenant_id,
        "before_snapshot_id": result.before.operational.snapshot_id,
        "before_snapshot_version": result.before.operational.snapshot_version,
        "after_snapshot_id": result.after.operational.snapshot_id,
        "after_snapshot_version": result.after.operational.snapshot_version,
        "supplier_delay_request": result.supplier_delay.model_dump(mode="json"),
        "source_mode": "SYNTHETIC_ISOLATED_DEMO",
    }, sort_keys=True))


if __name__ == "__main__":
    _run_cli()
