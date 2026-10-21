"""Identity guards and route collision tests for CommitmentService.assess (D-013, Task T3.1-C-FIX).

Tests verify:
1. Public Core /assess route returns 404 (Core route removed; P2 owns public route).
2. Duplicate-route guard across all mounted routers in app.routes.
3. Tenant mismatch: assessment.tenant_id != context.tenant_id -> 400 TENANT_MISMATCH (no mutation).
4. Commitment ID mismatch: assessment.commitment_id != commitment_id -> 400 COMMITMENT_ID_MISMATCH (no mutation).
5. Cross-tenant isolation: another tenant's commitment is not found (404) and never modified.
6. Role-based caller authorization: normal users (STAFF, MANAGER, OWNER) denied with 403 CALLER_NOT_AUTHORIZED;
   trusted service principals (SERVICE, SYSTEM) succeed.
7. Concurrency guard: stale commitment_version -> 409 COMMITMENT_VERSION_CONFLICT (no state change).
8. Risk invariants:
   - INFEASIBLE on CONFIRMED -> AT_RISK with commitment.at_risk outbox event.
   - INFEASIBLE on non-CONFIRMED (e.g. REQUESTED) -> no AT_RISK, no commitment.at_risk event.
   - UNKNOWN -> feasibility_state=UNKNOWN, no AT_RISK.
   - CONDITIONAL -> feasibility_state=CONDITIONAL, no AT_RISK.
9. Single-target mutation scope: assessment on com_001 listing com_002 in affected_commitment_ids does NOT mutate com_002.
10. Idempotency: duplicate assessment_id produces one mutation and one audit event.
11. Atomic transaction rollback: failure in outbox/audit write rolls back state and audit completely.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import CoreEventType
from app.core.models import AuditEventRecord, CommitmentRecord, OutboxEventRecord
from app.core.schemas import (
    AgreementState,
    CommitmentTerms,
    ConstraintReason,
    FeasibilityAssessment,
    FeasibilityState,
    RecoveryState,
    RiskState,
)
from app.core.service import CommitmentService
from app.main import app


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _service_context(
    tenant_id: str = "tenant_test_01",
    actor_id: str = "service_p2_feasibility",
    actor_role: str = "SERVICE",
) -> RequestContext:
    return RequestContext(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=f"corr_test_{_now().timestamp()}",
        causation_id="evt_test_p2_cause",
    )


def _seed_commitment(
    session: Session,
    tenant_id: str = "tenant_test_01",
    commitment_id: str = "com_test_001",
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


# =============================================================================
# 1. Route Absence & Duplicate Guard
# =============================================================================

def test_public_core_assess_route_is_absent(client: TestClient) -> None:
    """Core must NOT expose POST /v1/commitments/{id}/assess (D-013). Returns 404."""
    res = client.post(
        "/v1/commitments/com_any/assess",
        headers={
            "X-Tenant-ID": "tenant_test_01",
            "X-Actor-ID": "user_staff_01",
        },
        json={"status": "FEASIBLE"},
    )
    assert res.status_code == 404, f"Expected 404 Not Found, got {res.status_code}"


def test_no_duplicate_http_routes_across_routers() -> None:
    """Duplicate-route guard: no two route handlers may share the same (HTTP method, path)."""
    seen: set[tuple[str, str]] = set()
    duplicates: list[tuple[str, str]] = []

    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if methods and path:
            for method in methods:
                if method in {"HEAD", "OPTIONS"}:
                    continue
                key = (method, path)
                if key in seen:
                    duplicates.append(key)
                seen.add(key)

    assert not duplicates, f"Duplicate HTTP route definitions found: {duplicates}"


# =============================================================================
# 2. Identity Guards
# =============================================================================

def test_tenant_mismatch_rejected_and_leaves_commitment_unchanged(session: Session) -> None:
    """Assessment tenant_id != context.tenant_id -> 400 TENANT_MISMATCH, leaves state untouched."""
    record = _seed_commitment(session, tenant_id="tenant_alpha", commitment_id="com_01")
    service = CommitmentService()
    ctx = _service_context(tenant_id="tenant_alpha")

    assessment = FeasibilityAssessment(
        assessment_id="fa_mismatch_tenant",
        tenant_id="tenant_bravo",  # Mismatch!
        commitment_id="com_01",
        commitment_version=1,
        snapshot_version=1,
        status=FeasibilityState.INFEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        evidence_refs=["ev_01"],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    with pytest.raises(DomainError) as exc_info:
        service.assess(session, ctx, "com_01", assessment)

    assert exc_info.value.code == "TENANT_MISMATCH"
    assert exc_info.value.status_code == 400

    # Verify commitment was not modified
    session.refresh(record)
    assert record.commitment_version == 1
    assert record.risk_state == RiskState.NORMAL.value
    assert record.feasibility_state == FeasibilityState.NOT_ASSESSED.value


def test_commitment_id_mismatch_rejected_and_leaves_commitment_unchanged(session: Session) -> None:
    """Assessment commitment_id != argument commitment_id -> 400 COMMITMENT_ID_MISMATCH."""
    record = _seed_commitment(session, tenant_id="tenant_alpha", commitment_id="com_target")
    service = CommitmentService()
    ctx = _service_context(tenant_id="tenant_alpha")

    assessment = FeasibilityAssessment(
        assessment_id="fa_mismatch_com",
        tenant_id="tenant_alpha",
        commitment_id="com_other",  # Mismatch!
        commitment_version=1,
        snapshot_version=1,
        status=FeasibilityState.INFEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        evidence_refs=["ev_01"],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    with pytest.raises(DomainError) as exc_info:
        service.assess(session, ctx, "com_target", assessment)

    assert exc_info.value.code == "COMMITMENT_ID_MISMATCH"
    assert exc_info.value.status_code == 400

    session.refresh(record)
    assert record.commitment_version == 1
    assert record.risk_state == RiskState.NORMAL.value


def test_cross_tenant_isolation_commitment_not_found(session: Session) -> None:
    """Commitment belonging to tenant_alpha is invisible to tenant_bravo context -> 404."""
    _seed_commitment(session, tenant_id="tenant_alpha", commitment_id="com_secret")
    service = CommitmentService()
    ctx = _service_context(tenant_id="tenant_bravo")

    assessment = FeasibilityAssessment(
        assessment_id="fa_cross_tenant",
        tenant_id="tenant_bravo",
        commitment_id="com_secret",
        commitment_version=1,
        snapshot_version=1,
        status=FeasibilityState.INFEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        evidence_refs=["ev_01"],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    with pytest.raises(DomainError) as exc_info:
        service.assess(session, ctx, "com_secret", assessment)

    assert exc_info.value.code == "COMMITMENT_NOT_FOUND"
    assert exc_info.value.status_code == 404


# =============================================================================
# 3. Caller Authorization Guard (Service Principal)
# =============================================================================

@pytest.mark.parametrize("actor_id,role", [
    ("user_staff_01", "STAFF"),
    ("user_manager_01", "MANAGER"),
    ("user_owner_01", "OWNER"),
])
def test_normal_users_cannot_invoke_internal_writer(session: Session, actor_id: str, role: str) -> None:
    """Normal user actors (STAFF, MANAGER, OWNER) are denied with 403 CALLER_NOT_AUTHORIZED."""
    _seed_commitment(session, tenant_id="tenant_test_01", commitment_id="com_auth_01")
    service = CommitmentService()
    user_ctx = RequestContext(
        tenant_id="tenant_test_01",
        actor_id=actor_id,
        actor_role=role,
        correlation_id="corr_user_test",
    )

    assessment = FeasibilityAssessment(
        assessment_id="fa_auth_test",
        tenant_id="tenant_test_01",
        commitment_id="com_auth_01",
        commitment_version=1,
        snapshot_version=1,
        status=FeasibilityState.FEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    with pytest.raises(DomainError) as exc_info:
        service.assess(session, user_ctx, "com_auth_01", assessment)

    assert exc_info.value.code == "CALLER_NOT_AUTHORIZED"
    assert exc_info.value.status_code == 403


def test_trusted_service_principal_can_invoke_internal_writer(session: Session) -> None:
    """Trusted service principal (service_p2_feasibility, SERVICE) is authorized."""
    _seed_commitment(session, tenant_id="tenant_test_01", commitment_id="com_service_ok")
    service = CommitmentService()
    ctx = _service_context(tenant_id="tenant_test_01", actor_id="service_p2_feasibility", actor_role="SERVICE")

    assessment = FeasibilityAssessment(
        assessment_id="fa_service_ok",
        tenant_id="tenant_test_01",
        commitment_id="com_service_ok",
        commitment_version=1,
        snapshot_version=1,
        status=FeasibilityState.FEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    updated = service.assess(session, ctx, "com_service_ok", assessment)
    assert updated.feasibility_state == FeasibilityState.FEASIBLE
    assert updated.commitment_version == 2


# =============================================================================
# 4. Concurrency Guard
# =============================================================================

def test_stale_commitment_version_rejected_with_409(session: Session) -> None:
    """Stale commitment_version returns 409 Conflict with current version details."""
    record = _seed_commitment(session, tenant_id="tenant_test_01", commitment_id="com_stale", commitment_version=3)
    service = CommitmentService()
    ctx = _service_context(tenant_id="tenant_test_01")

    assessment = FeasibilityAssessment(
        assessment_id="fa_stale",
        tenant_id="tenant_test_01",
        commitment_id="com_stale",
        commitment_version=2,  # Stale! Current is 3
        snapshot_version=1,
        status=FeasibilityState.FEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    with pytest.raises(DomainError) as exc_info:
        service.assess(session, ctx, "com_stale", assessment)

    assert exc_info.value.code == "COMMITMENT_VERSION_CONFLICT"
    assert exc_info.value.status_code == 409
    assert exc_info.value.details["current_commitment_version"] == 3

    session.refresh(record)
    assert record.commitment_version == 3


# =============================================================================
# 5. Feasibility State & Risk Invariants (D-007)
# =============================================================================

def test_infeasible_on_confirmed_triggers_at_risk_and_recovery(session: Session) -> None:
    """CONFIRMED + INFEASIBLE -> AT_RISK, RECOVERY_REQUIRED, commitment.at_risk outbox event."""
    record = _seed_commitment(session, commitment_id="com_inf_conf", agreement_state=AgreementState.CONFIRMED)
    service = CommitmentService()
    ctx = _service_context()

    assessment = FeasibilityAssessment(
        assessment_id="fa_inf_conf",
        tenant_id="tenant_test_01",
        commitment_id="com_inf_conf",
        commitment_version=1,
        snapshot_version=10,
        status=FeasibilityState.INFEASIBLE,
        constraints=[
            ConstraintReason(
                code="OUT_OF_STOCK",
                resource_id="PATTY",
                shortage=Decimal("20"),
                unit="pcs",
                severity="HARD",
            )
        ],
        affected_commitment_ids=["com_inf_conf"],
        evidence_refs=["ev_stock_fail"],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    updated = service.assess(session, ctx, "com_inf_conf", assessment)
    assert updated.risk_state == RiskState.AT_RISK
    assert updated.recovery_state == RecoveryState.RECOVERY_REQUIRED
    assert updated.agreement_state == AgreementState.CONFIRMED
    assert updated.commitment_version == 2

    # Check outbox event
    outbox = session.scalars(
        select(OutboxEventRecord).where(
            OutboxEventRecord.commitment_id == "com_inf_conf",
            OutboxEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
        )
    ).all()
    assert len(outbox) == 1
    assert outbox[0].payload["assessment_id"] == "fa_inf_conf"


def test_infeasible_on_unconfirmed_does_not_trigger_at_risk(session: Session) -> None:
    """REQUESTED + INFEASIBLE -> feasibility=INFEASIBLE, but risk_state remains NORMAL (no false alarm)."""
    record = _seed_commitment(session, commitment_id="com_inf_req", agreement_state=AgreementState.REQUESTED)
    service = CommitmentService()
    ctx = _service_context()

    assessment = FeasibilityAssessment(
        assessment_id="fa_inf_req",
        tenant_id="tenant_test_01",
        commitment_id="com_inf_req",
        commitment_version=1,
        snapshot_version=10,
        status=FeasibilityState.INFEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    updated = service.assess(session, ctx, "com_inf_req", assessment)
    assert updated.feasibility_state == FeasibilityState.INFEASIBLE
    assert updated.risk_state == RiskState.NORMAL  # Invariant: not CONFIRMED -> no AT_RISK!
    assert updated.commitment_version == 2

    # Verify no commitment.at_risk event was emitted
    at_risk_events = session.scalars(
        select(OutboxEventRecord).where(
            OutboxEventRecord.commitment_id == "com_inf_req",
            OutboxEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
        )
    ).all()
    assert len(at_risk_events) == 0


def test_unknown_and_conditional_do_not_trigger_at_risk(session: Session) -> None:
    """UNKNOWN != INFEASIBLE and CONDITIONAL != INFEASIBLE; neither triggers AT_RISK on CONFIRMED."""
    _seed_commitment(session, commitment_id="com_unk", agreement_state=AgreementState.CONFIRMED)
    _seed_commitment(session, commitment_id="com_cond", agreement_state=AgreementState.CONFIRMED)
    service = CommitmentService()
    ctx = _service_context()

    # Assess UNKNOWN
    unk_assessment = FeasibilityAssessment(
        assessment_id="fa_unk_01",
        tenant_id="tenant_test_01",
        commitment_id="com_unk",
        commitment_version=1,
        snapshot_version=1,
        status=FeasibilityState.UNKNOWN,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="NOT_RUN",
        assessed_at=_now(),
    )
    res_unk = service.assess(session, ctx, "com_unk", unk_assessment)
    assert res_unk.feasibility_state == FeasibilityState.UNKNOWN
    assert res_unk.risk_state == RiskState.NORMAL

    # Assess CONDITIONAL
    cond_assessment = FeasibilityAssessment(
        assessment_id="fa_cond_01",
        tenant_id="tenant_test_01",
        commitment_id="com_cond",
        commitment_version=1,
        snapshot_version=1,
        status=FeasibilityState.CONDITIONAL,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )
    res_cond = service.assess(session, ctx, "com_cond", cond_assessment)
    assert res_cond.feasibility_state == FeasibilityState.CONDITIONAL
    assert res_cond.risk_state == RiskState.NORMAL


# =============================================================================
# 6. Single-Target Mutation Scope
# =============================================================================

def test_assessment_does_not_mutate_affected_commitment_ids(session: Session) -> None:
    """An assessment on com_001 listing com_002 in affected_commitment_ids mutates ONLY com_001."""
    com1 = _seed_commitment(session, commitment_id="com_scope_001", agreement_state=AgreementState.CONFIRMED)
    com2 = _seed_commitment(session, commitment_id="com_scope_002", agreement_state=AgreementState.CONFIRMED)
    service = CommitmentService()
    ctx = _service_context()

    assessment = FeasibilityAssessment(
        assessment_id="fa_scope_01",
        tenant_id="tenant_test_01",
        commitment_id="com_scope_001",
        commitment_version=1,
        snapshot_version=10,
        status=FeasibilityState.INFEASIBLE,
        constraints=[
            ConstraintReason(
                code="SHARED_LINE_DOWN",
                resource_id="LINE_A",
                shortage=Decimal("1"),
                unit="shift",
                severity="HARD",
            )
        ],
        affected_commitment_ids=["com_scope_001", "com_scope_002"],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    service.assess(session, ctx, "com_scope_001", assessment)

    session.refresh(com1)
    session.refresh(com2)

    # com_scope_001 was mutated
    assert com1.commitment_version == 2
    assert com1.risk_state == RiskState.AT_RISK.value

    # com_scope_002 remains strictly untouched
    assert com2.commitment_version == 1
    assert com2.risk_state == RiskState.NORMAL.value
    assert com2.feasibility_state == FeasibilityState.NOT_ASSESSED.value


# =============================================================================
# 7. Idempotency on assessment_id
# =============================================================================

def test_duplicate_assessment_id_is_idempotent(session: Session) -> None:
    """Submitting the same assessment_id twice is idempotent: one mutation, one audit entry."""
    _seed_commitment(session, commitment_id="com_idemp", agreement_state=AgreementState.CONFIRMED)
    service = CommitmentService()
    ctx = _service_context()

    assessment = FeasibilityAssessment(
        assessment_id="fa_idemp_01",
        tenant_id="tenant_test_01",
        commitment_id="com_idemp",
        commitment_version=1,
        snapshot_version=5,
        status=FeasibilityState.INFEASIBLE,
        constraints=[],
        affected_commitment_ids=["com_idemp"],
        evidence_refs=["ev_idemp_01"],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    first_res = service.assess(session, ctx, "com_idemp", assessment)
    assert first_res.commitment_version == 2

    # Second call with identical assessment_id
    second_res = service.assess(session, ctx, "com_idemp", assessment)
    assert second_res.commitment_version == 2

    # Verify audit records count
    audits = session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.commitment_id == "com_idemp",
            AuditEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
        )
    ).all()
    assert len(audits) == 1

    # Verify outbox records count
    outbox = session.scalars(
        select(OutboxEventRecord).where(
            OutboxEventRecord.commitment_id == "com_idemp",
            OutboxEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
        )
    ).all()
    assert len(outbox) == 1


# =============================================================================
# 8. Transaction Atomic Rollback on Failure
# =============================================================================

def test_outbox_failure_rolls_back_state_and_audit(session: Session) -> None:
    """If outbox/commit fails, the entire transaction rolls back; commitment remains unchanged."""
    record = _seed_commitment(session, commitment_id="com_atomic_fail", agreement_state=AgreementState.CONFIRMED)
    service = CommitmentService()
    ctx = _service_context()

    assessment = FeasibilityAssessment(
        assessment_id="fa_atomic_fail",
        tenant_id="tenant_test_01",
        commitment_id="com_atomic_fail",
        commitment_version=1,
        snapshot_version=1,
        status=FeasibilityState.INFEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )

    # Force an error during db.commit
    with patch.object(session, "commit", side_effect=RuntimeError("Simulated DB storage failure")):
        with pytest.raises(RuntimeError, match="Simulated DB storage failure"):
            service.assess(session, ctx, "com_atomic_fail", assessment)

    session.refresh(record)
    # Verification: record rolled back cleanly
    assert record.commitment_version == 1
    assert record.risk_state == RiskState.NORMAL.value
    assert record.feasibility_state == FeasibilityState.NOT_ASSESSED.value

    # Verification: no audit or outbox entries persisted
    audits = session.scalars(
        select(AuditEventRecord).where(AuditEventRecord.commitment_id == "com_atomic_fail")
    ).all()
    assert len(audits) == 0

    outbox = session.scalars(
        select(OutboxEventRecord).where(OutboxEventRecord.commitment_id == "com_atomic_fail")
    ).all()
    assert len(outbox) == 0
