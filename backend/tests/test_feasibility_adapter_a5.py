"""Tests for P5 snapshot freshness verification and intent suppression (A5, D-013, D-032).

Verifies:
1. Snapshot drift detection: when expected_snapshot_version differs from authoritative snapshot version,
   AuthoritativeAssessmentWriter raises DomainError with code SNAPSHOT_DRIFT_CONFLICT and status_code 409.
2. Intent suppression & single authoritative at_risk event:
   P2's local intents are suppressed by the adapter. Only CommitmentService.assess() emits the single
   authoritative commitment.at_risk outbox event on a verified aggregate transition.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import CoreEventType
from app.core.models import CommitmentRecord, OutboxEventRecord, ResourceStockRecord
from app.core.schemas import (
    AgreementState,
    ConstraintReason,
    FeasibilityState,
    RecoveryState,
    RiskState,
)
from app.core.service import CommitmentService
from app.feasibility.adapters import AuthoritativeAssessmentWriter
from app.feasibility.api_schemas import AssessCommitmentRequest
from app.feasibility.production_fixtures import build_production_example
from app.feasibility.service import EvaluationResult


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_commitment(
    session: Session,
    tenant_id: str = "tenant_test_01",
    commitment_id: str = "com_drift_001",
    agreement_state: AgreementState = AgreementState.CONFIRMED,
    feasibility_state: FeasibilityState = FeasibilityState.NOT_ASSESSED,
    risk_state: RiskState = RiskState.NORMAL,
    recovery_state: RecoveryState = RecoveryState.NONE,
    commitment_version: int = 1,
) -> CommitmentRecord:
    record = CommitmentRecord(
        tenant_id=tenant_id,
        commitment_id=commitment_id,
        order_id=f"ord_{commitment_id}",
        customer_id="cust_test_001",
        terms={
            "sku": "BURGER_TEST",
            "quantity": "50",
            "unit": "pcs",
            "deadline": (_now() + timedelta(days=2)).isoformat(),
        },
        agreement_state=agreement_state.value,
        feasibility_state=feasibility_state.value,
        risk_state=risk_state.value,
        recovery_state=recovery_state.value,
        fulfilment_state="NOT_STARTED",
        commitment_version=commitment_version,
        evidence_refs=["ev_init_001"],
        updated_at=_now(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def test_snapshot_drift_conflict_returns_409(session: Session) -> None:
    """A mismatch between expected_snapshot_version and authoritative snapshot returns HTTP 409 SNAPSHOT_DRIFT_CONFLICT."""
    tenant_id = "tenant-synthetic-p2"
    com_record = _seed_commitment(session, tenant_id=tenant_id, commitment_id="com_drift_001", commitment_version=1)

    # Seed authoritative resource with snapshot_version = 5
    res = ResourceStockRecord(
        tenant_id=tenant_id,
        resource_id="res_patty_01",
        unit="kg",
        total_quantity=Decimal("100"),
        reserved_quantity=Decimal("10"),
        snapshot_version=5,
        updated_at=_now(),
    )
    session.add(res)
    session.commit()

    writer = AuthoritativeAssessmentWriter()
    context = RequestContext(
        tenant_id=tenant_id,
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_drift_test",
    )

    from app.feasibility.adapters import AuthoritativeEvaluationAuthority

    authority = AuthoritativeEvaluationAuthority()
    snapshot, commitment = authority.resolve_current(context, "com_drift_001", 1)

    # Caller expects snapshot version 4, but authoritative DB snapshot is version 5
    request = AssessCommitmentRequest(
        expected_commitment_version=1,
        expected_snapshot_version=4,
    )
    from app.feasibility.service import evaluate

    base_result = evaluate(snapshot, None, commitment)
    result = base_result

    with pytest.raises(DomainError) as exc_info:
        writer.assess(
            session,
            context,
            commitment,
            request,
            snapshot=snapshot,
            result=result,
        )

    assert exc_info.value.code == "SNAPSHOT_DRIFT_CONFLICT"
    assert exc_info.value.status_code == 409
    assert exc_info.value.details["expected_snapshot_version"] == 4
    assert exc_info.value.details["current_snapshot_version"] == 5


def test_intent_suppression_and_single_authoritative_at_risk_outbox_event(session: Session) -> None:
    """Local P2 intents are suppressed; only CommitmentService.assess emits exactly one commitment.at_risk event."""
    tenant_id = "tenant-synthetic-p2"
    com_record = _seed_commitment(
        session,
        tenant_id=tenant_id,
        commitment_id="com_suppress_001",
        agreement_state=AgreementState.CONFIRMED,
        feasibility_state=FeasibilityState.FEASIBLE,
        risk_state=RiskState.NORMAL,
        commitment_version=1,
    )

    # Seed authoritative resource with snapshot_version = 1
    res = ResourceStockRecord(
        tenant_id=tenant_id,
        resource_id="res_patty_02",
        unit="kg",
        total_quantity=Decimal("50"),
        reserved_quantity=Decimal("50"),
        snapshot_version=1,
        updated_at=_now(),
    )
    session.add(res)
    session.commit()

    writer = AuthoritativeAssessmentWriter()
    context = RequestContext(
        tenant_id=tenant_id,
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_suppress_test",
    )

    from app.feasibility.adapters import AuthoritativeEvaluationAuthority

    authority = AuthoritativeEvaluationAuthority()
    snapshot, commitment = authority.resolve_current(context, "com_suppress_001", 1)

    request = AssessCommitmentRequest(
        expected_commitment_version=1,
        expected_snapshot_version=1,
    )
    from app.feasibility.service import evaluate

    base_result = evaluate(snapshot, None, commitment)
    # INFEASIBLE result triggers transition to AT_RISK on CONFIRMED commitment
    result = base_result.model_copy(
        update={
            "status": FeasibilityState.INFEASIBLE,
            "constraints": (
                ConstraintReason(
                    code="OUT_OF_STOCK",
                    resource_id="res_patty_02",
                    shortage=Decimal("20"),
                    unit="kg",
                    severity="HARD",
                ),
            ),
            "evidence_refs": ("ev_shortage_01",),
        }
    )

    assessment = writer.assess(
        session,
        context,
        commitment,
        request,
        snapshot=snapshot,
        result=result,
    )

    assert assessment.status == FeasibilityState.INFEASIBLE
    assert assessment.commitment_id == "com_suppress_001"

    # Verify commitment state updated
    session.refresh(com_record)
    assert com_record.commitment_version == 2
    assert com_record.risk_state == RiskState.AT_RISK.value
    assert com_record.feasibility_state == FeasibilityState.INFEASIBLE.value

    # Verify EXACTLY ONE commitment.at_risk outbox event was emitted (no duplicates, no local intents leaked)
    at_risk_events = session.scalars(
        select(OutboxEventRecord).where(
            OutboxEventRecord.tenant_id == tenant_id,
            OutboxEventRecord.commitment_id == "com_suppress_001",
            OutboxEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
        )
    ).all()
    assert len(at_risk_events) == 1
    assert at_risk_events[0].payload["commitment_id"] == "com_suppress_001"
