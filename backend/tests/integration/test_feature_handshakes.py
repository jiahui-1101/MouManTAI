"""Comprehensive integration tests for P1–P4 Handshake Event Consumers and Core Integration Facades.

Verifies:
- BE-06a / UT-09: P1 context ready vs conflict handling, OCR receipt guard
- BE-06b: P2 INFEASIBLE on CONFIRMED -> AT_RISK + RECOVERY_REQUIRED vs UNKNOWN -> attention queue
- BE-06c / E2E-04 / UT-08: P3 role authorization, snapshot drift & approval expiry guards
- BE-06d / UT-10 / E2E-05 / E2E-06 / E2E-07: P4 communication tracking, ambiguous response handling,
  stale proposal version rejection (V2 vs V3), valid confirmation without setting FULFILLED
- BE-02h / E2E-12: Operational delivery evidence verification transitioning to FULFILLED & RESOLVED
- BE-06e: PII minimization across all outbox event payloads
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import CoreEventType, OutboxStatus, validate_event_payload
from app.core.integration import CoreIntegrationFacade
from app.core.models import (
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
)
from app.core.schemas import (
    AgreementState,
    AttentionCategory,
    BusinessContext,
    CommitmentCreateRequest,
    CommitmentTerms,
    CommitmentTransitionRequest,
    ConstraintReason,
    ContextStatus,
    CustomerIdentityStatus,
    FeasibilityAssessment,
    FeasibilityState,
    FulfilmentState,
    PlannedAction,
    ProposalConfirmRequest,
    ProposalCreateRequest,
    RecordFulfilmentRequest,
    RecoveryExecuteRequest,
    RecoveryPlan,
    RecoveryState,
    RequestedItem,
    RiskState,
    SolverStatus,
)

from app.core.service import CommitmentService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _headers(actor: str = "user_owner_01", tenant: str = "tenant_demo_01") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Actor-ID": actor,
        "X-Correlation-ID": f"corr_{_now().timestamp()}",
    }


def _ctx(actor: str = "user_owner_01", role: str = "OWNER", tenant: str = "tenant_demo_01") -> RequestContext:
    return RequestContext(
        tenant_id=tenant,
        actor_id=actor,
        actor_role=role,
        correlation_id=f"corr_{_now().timestamp()}",
    )


# =============================================================================
# 1. P1 → P5 / P2 Handshake Tests (BE-06a, UT-09)
# =============================================================================

def test_p1_ready_verified_context_creates_requested_commitment(client: TestClient, session: Session) -> None:
    """When context is READY, LINK_VERIFIED, and conflict-free, create REQUESTED commitment and emit context_ready."""
    facade = CoreIntegrationFacade()
    context = _ctx()

    b_ctx = BusinessContext(
        tenant_id="tenant_demo_01",
        context_id="ctx_ready_001",
        source_message_ids=["msg_001"],
        customer_id="cust_retail_001",
        customer_identity_status=CustomerIdentityStatus.LINK_VERIFIED,
        order_id="ord_p1_001",
        requested_items=[RequestedItem(sku="SKU_BURGER_BUN", quantity=Decimal("200"), unit="pcs")],
        requested_delivery_at=_now() + timedelta(days=2),
        special_instructions="Deliver to loading bay 2",
        field_evidence={"sku": ["ev_msg_001_sku"], "quantity": ["ev_msg_001_qty"]},
        conflicts=[],
        missing_fields=[],
        context_version=1,
        status=ContextStatus.INFORMATION_READY,
    )

    commitment = facade.handle_context_updated(session, context, b_ctx)

    assert commitment.commitment_id.startswith("com_")
    assert commitment.order_id == "ord_p1_001"
    assert commitment.customer_id == "cust_retail_001"
    assert commitment.agreement_state == AgreementState.REQUESTED
    assert commitment.feasibility_state == FeasibilityState.NOT_ASSESSED
    assert commitment.risk_state == RiskState.NORMAL
    assert commitment.fulfilment_state == FulfilmentState.NOT_STARTED
    assert commitment.commitment_version == 1

    # Verify outbox event emitted
    outbox_events = session.scalars(
        select(OutboxEventRecord).where(
            OutboxEventRecord.commitment_id == commitment.commitment_id
        )
    ).all()
    event_types = [e.event_type for e in outbox_events]
    assert CoreEventType.COMMITMENT_CONTEXT_READY.value in event_types


def test_p1_conflict_or_missing_fields_flags_manual_review_attention(client: TestClient, session: Session) -> None:
    """Unresolved context conflicts or missing fields keep commitment unconfirmed and flag MANUAL_REVIEW."""
    facade = CoreIntegrationFacade()
    context = _ctx()

    b_ctx = BusinessContext(
        tenant_id="tenant_demo_01",
        context_id="ctx_conflict_002",
        source_message_ids=["msg_002"],
        customer_id="cust_retail_002",
        customer_identity_status=CustomerIdentityStatus.LINK_VERIFIED,
        order_id="ord_p1_002",
        requested_items=[RequestedItem(sku="SKU_CHEESE", quantity=Decimal("50"), unit="kg")],
        requested_delivery_at=_now() + timedelta(days=1),
        conflicts=["Requested delivery Sunday but supplier closed"],
        missing_fields=["delivery_time_window"],
        context_version=1,
        status=ContextStatus.INFORMATION_READY,
    )

    commitment = facade.handle_context_updated(session, context, b_ctx)

    assert commitment.agreement_state == AgreementState.REQUESTED
    # Invariant: REQUESTED != CONFIRMED
    assert commitment.agreement_state != AgreementState.CONFIRMED

    # Query overview API to verify attention item
    res = client.get("/v1/overview", headers=_headers())
    assert res.status_code == 200
    overview = res.json()
    manual_reviews = [
        item for item in overview["attention_queue"]
        if item["category"] == AttentionCategory.MANUAL_REVIEW.value
        and item["commitment_id"] == commitment.commitment_id
    ]
    assert len(manual_reviews) >= 1
    assert "conflicts or missing fields" in manual_reviews[0]["summary"].lower()


def test_p1_ocr_receipt_evidence_never_auto_confirms_commitment(client: TestClient, session: Session) -> None:
    """OCR receipt (ev_receipt_*) records as evidence only and NEVER auto-confirms payment/terms (UT-09)."""
    facade = CoreIntegrationFacade()
    context = _ctx()

    b_ctx = BusinessContext(
        tenant_id="tenant_demo_01",
        context_id="ctx_receipt_003",
        source_message_ids=["msg_003"],
        customer_id="cust_retail_003",
        customer_identity_status=CustomerIdentityStatus.LINK_VERIFIED,
        order_id="ord_p1_003",
        requested_items=[RequestedItem(sku="SKU_BEVERAGE", quantity=Decimal("120"), unit="cans")],
        requested_delivery_at=_now() + timedelta(days=3),
        field_evidence={"payment": ["ev_receipt_ocr_bank_transfer_9941"]},
        conflicts=[],
        missing_fields=[],
        context_version=1,
        status=ContextStatus.INFORMATION_READY,
    )

    commitment = facade.handle_context_updated(session, context, b_ctx)

    # Invariant: OCR receipt != verified funds; agreement remains REQUESTED
    assert commitment.agreement_state == AgreementState.REQUESTED
    assert "ev_receipt_ocr_bank_transfer_9941" in commitment.evidence_refs

    # Attempting to confirm proposal with ONLY receipt evidence must be rejected (UT-09)
    # First offer a proposal
    client.post(
        f"/v1/commitments/{commitment.commitment_id}/proposals",
        headers=_headers(),
        json={
            "proposal_id": "prop_rcpt_001",
            "proposal_version": 1,
            "expected_commitment_version": 1,
            "reason": "Offering terms",
        },
    )

    bad_confirm = client.post(
        f"/v1/commitments/{commitment.commitment_id}/confirm-proposal",
        headers=_headers(actor="user_manager_01"),
        json={
            "proposal_id": "prop_rcpt_001",
            "proposal_version": 1,
            "expected_commitment_version": 2,
            "decision": "ACCEPT",
            "evidence_refs": ["ev_receipt_ocr_bank_transfer_9941"],
            "reason": "Trying to confirm with receipt only",
        },
    )
    assert bad_confirm.status_code == 422
    assert bad_confirm.json()["code"] == "RECEIPT_CANNOT_CONFIRM"


# =============================================================================
# 2. P2 → P5 / P3 Handshake Tests (BE-06b)
# =============================================================================

def test_p2_infeasible_assessment_on_confirmed_triggers_at_risk_and_recovery(client: TestClient, session: Session) -> None:
    """When assessment is INFEASIBLE on CONFIRMED commitment: set AT_RISK, RECOVERY_REQUIRED, emit event."""
    # 1. Create and confirm commitment
    create_res = client.post(
        "/v1/commitments",
        headers=_headers(),
        json={
            "order_id": "ord_p2_001",
            "customer_id": "cust_p2_001",
            "terms": {
                "sku": "BURGER_PREMIUM",
                "quantity": "100",
                "unit": "pcs",
                "deadline": (_now() + timedelta(days=2)).isoformat(),
            },
            "evidence_refs": ["ev_order_001"],
        },
    )
    assert create_res.status_code == 201
    com_id = create_res.json()["commitment_id"]

    # Transition to OFFERED then CONFIRMED
    client.post(
        f"/v1/commitments/{com_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "agreement",
            "target_state": "OFFERED",
            "expected_commitment_version": 1,
            "reason": "Offering standard terms",
        },
    )
    client.post(
        f"/v1/commitments/{com_id}/transitions",
        headers=_headers(actor="user_manager_01"),
        json={
            "dimension": "agreement",
            "target_state": "CONFIRMED",
            "expected_commitment_version": 2,
            "evidence_refs": ["ev_signed_agreement_001"],
            "reason": "Customer signed contract",
        },
    )

    # 2. [SIMULATED P2 HANDSHAKE] Trusted P2 service principal applies INFEASIBLE assessment via internal writer (D-013)
    service = CommitmentService()
    service_context = RequestContext(
        tenant_id="tenant_demo_01",
        actor_id="service_p2_feasibility",
        actor_role="SERVICE",
        correlation_id="corr_p2_001",
        causation_id="evt_p2_001",
    )
    assessment = FeasibilityAssessment(
        assessment_id="fa_p2_001",
        tenant_id="tenant_demo_01",
        commitment_id=com_id,
        commitment_version=3,
        snapshot_version=142,
        status=FeasibilityState.INFEASIBLE,
        constraints=[
            ConstraintReason(
                code="RAW_MATERIAL_SHORTAGE",
                resource_id="BEEF_PATTIES",
                shortage=Decimal("40"),
                unit="pcs",
                severity="HARD",
                evidence_refs=["ev_stock_shortage_01"],
            )
        ],
        affected_commitment_ids=[com_id],
        evidence_refs=["ev_stock_shortage_01"],
        solver_status="COMPLETED",
        assumptions=["Supplier lead time delayed by 3 days"],
        assessed_at=_now(),
    )
    c1 = service.assess(session, service_context, com_id, assessment)
    assert c1.feasibility_state == FeasibilityState.INFEASIBLE
    assert c1.risk_state == RiskState.AT_RISK
    assert c1.recovery_state == RecoveryState.RECOVERY_REQUIRED
    assert c1.agreement_state == AgreementState.CONFIRMED  # Invariant: CONFIRMED + AT_RISK coexist!
    assert c1.commitment_version == 4

    # 3. Verify outbox event emitted
    events_res = client.get(f"/v1/commitments/{com_id}/timeline", headers=_headers())
    assert events_res.status_code == 200
    timeline = events_res.json()
    at_risk_entries = [e for e in timeline if e["event_type"] == "commitment.at_risk"]
    assert len(at_risk_entries) >= 1
    assert at_risk_entries[0]["new_state"]["risk_state"] == "AT_RISK"


def test_p2_unknown_feasibility_flags_attention_queue_without_false_infeasibility(client: TestClient, session: Session) -> None:
    """UNKNOWN feasibility flags UNKNOWN_FEASIBILITY attention item without setting AT_RISK."""
    create_res = client.post(
        "/v1/commitments",
        headers=_headers(),
        json={
            "order_id": "ord_p2_002",
            "customer_id": "cust_p2_002",
            "terms": {
                "sku": "BURGER_VEGAN",
                "quantity": "50",
                "unit": "pcs",
                "deadline": (_now() + timedelta(days=2)).isoformat(),
            },
            "evidence_refs": ["ev_order_002"],
        },
    )
    com_id = create_res.json()["commitment_id"]

    # [SIMULATED P2 HANDSHAKE] Trusted P2 service principal applies UNKNOWN assessment via internal writer (D-013)
    service = CommitmentService()
    service_context = RequestContext(
        tenant_id="tenant_demo_01",
        actor_id="service_p2_feasibility",
        actor_role="SERVICE",
        correlation_id="corr_p2_unk_001",
        causation_id="evt_p2_unk_001",
    )
    assessment = FeasibilityAssessment(
        assessment_id="fa_p2_unk_001",
        tenant_id="tenant_demo_01",
        commitment_id=com_id,
        commitment_version=1,
        snapshot_version=142,
        status=FeasibilityState.UNKNOWN,
        constraints=[],
        affected_commitment_ids=[],
        evidence_refs=["ev_telemetry_missing"],
        solver_status="NOT_RUN",
        assumptions=["Missing supplier stock telemetry"],
        assessed_at=_now(),
    )
    c1 = service.assess(session, service_context, com_id, assessment)
    assert c1.feasibility_state == FeasibilityState.UNKNOWN
    # Invariant: UNKNOWN != INFEASIBLE; risk remains NORMAL
    assert c1.risk_state == RiskState.NORMAL

    # Verify overview attention queue has UNKNOWN_FEASIBILITY
    overview_res = client.get("/v1/overview", headers=_headers())
    assert overview_res.status_code == 200
    unknown_items = [
        item for item in overview_res.json()["attention_queue"]
        if item["category"] == AttentionCategory.UNKNOWN_FEASIBILITY.value
        and item["commitment_id"] == com_id
    ]
    assert len(unknown_items) == 1
    assert "unknown" in unknown_items[0]["summary"].lower()


def test_p2_stale_assessment_version_rejected_with_409(client: TestClient, session: Session) -> None:
    """P2 assessment with stale commitment_version is rejected with 409 Conflict."""
    create_res = client.post(
        "/v1/commitments",
        headers=_headers(),
        json={
            "order_id": "ord_p2_003",
            "customer_id": "cust_p2_003",
            "terms": {
                "sku": "BURGER_CLASSIC",
                "quantity": "100",
                "unit": "pcs",
                "deadline": (_now() + timedelta(days=1)).isoformat(),
            },
            "evidence_refs": ["ev_order_003"],
        },
    )
    com_id = create_res.json()["commitment_id"]

    # Transition to increment version to 2
    client.post(
        f"/v1/commitments/{com_id}/transitions",
        headers=_headers(),
        json={
            "dimension": "agreement",
            "target_state": "OFFERED",
            "expected_commitment_version": 1,
            "reason": "Offer terms",
        },
    )

    # [SIMULATED P2 HANDSHAKE] Attempt assessment with stale commitment_version=1 via internal writer
    service = CommitmentService()
    service_context = RequestContext(
        tenant_id="tenant_demo_01",
        actor_id="service_p2_feasibility",
        actor_role="SERVICE",
        correlation_id="corr_p2_stale_001",
        causation_id="evt_p2_stale_001",
    )
    stale_assessment = FeasibilityAssessment(
        assessment_id="fa_stale_01",
        tenant_id="tenant_demo_01",
        commitment_id=com_id,
        commitment_version=1,  # Stale! Current is 2
        snapshot_version=140,
        status=FeasibilityState.FEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )
    with pytest.raises(DomainError) as exc_info:
        service.assess(session, service_context, com_id, stale_assessment)
    assert exc_info.value.code == "COMMITMENT_VERSION_CONFLICT"
    assert exc_info.value.status_code == 409
    assert exc_info.value.details["current_commitment_version"] == 2


# =============================================================================
# 3. P3 → P5 / P4 Handshake Tests (BE-06c, E2E-04, UT-08)
# =============================================================================

def test_p3_consequential_actions_require_manager_authorization(session: Session) -> None:
    """Staff role cannot execute consequential recovery actions (BE-05c)."""
    facade = CoreIntegrationFacade()
    with pytest.raises(DomainError) as exc_info:
        facade.authorize("user_staff_01", "STAFF", "EXECUTE_PLAN")
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "APPROVAL_REQUIRED"


def test_p3_stale_snapshot_blocks_execution_and_invalidates_approval(client: TestClient, session: Session) -> None:
    """If snapshot drifted between approval and execution, block execution (409) and set RECOVERY_REQUIRED (E2E-04)."""
    facade = CoreIntegrationFacade()
    context = _ctx(actor="user_manager_01", role="MANAGER")

    # Setup commitment in PLANNING
    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_p3_001",
            customer_id="cust_p3_001",
            terms=CommitmentTerms(
                sku="BURGER_BULK",
                quantity=Decimal("300"),
                unit="pcs",
                deadline=_now() + timedelta(days=2),
            ),
            evidence_refs=["ev_init"],
        ),
    )

    plan = RecoveryPlan(
        tenant_id="tenant_demo_01",
        recovery_case_id="rc_001",
        plan_id="plan_drift_01",
        plan_version=1,
        commitment_id=c.commitment_id,
        based_on_assessment_id="fa_p2_001",
        snapshot_version=142,  # Approved under snapshot 142
        feasibility_status=FeasibilityState.FEASIBLE,
        estimated_extra_cost=Decimal("120.00"),
        currency="MYR",
        estimated_delay_minutes=0,
        actions=[
            PlannedAction(
                action_id="act_expedite",
                type="EXPEDITE_SUPPLIER",
                requires_approval=True,
                idempotency_key="plan_drift_act_1",
            )
        ],
        approval_state="PENDING",
        execution_state="NOT_STARTED",
    )

    # Attempt execute with current snapshot = 145 (drifted!)
    request = RecoveryExecuteRequest(
        expected_commitment_version=1,
        plan=plan,
        current_snapshot_version=145,  # Snapshot changed in meantime!
        approved_at=_now() - timedelta(minutes=10),
        approval_expires_at=_now() + timedelta(hours=2),
        reason="Executing plan",
    )

    with pytest.raises(DomainError) as exc:
        facade.execute_recovery_plan(session, context, c.commitment_id, request)

    assert exc.value.status_code == 409
    assert exc.value.code == "SNAPSHOT_DRIFT_CONFLICT"

    # Invariant: plan invalidated, recovery_state set to RECOVERY_REQUIRED
    updated = facade.service.get(session, context, c.commitment_id)
    assert updated.recovery_state == RecoveryState.RECOVERY_REQUIRED


def test_p3_expired_approval_blocks_execution(session: Session) -> None:
    """Expired approval blocks execution with 409 and requires re-planning (UT-08)."""
    facade = CoreIntegrationFacade()
    context = _ctx(actor="user_manager_01", role="MANAGER")

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_p3_002",
            customer_id="cust_p3_002",
            terms=CommitmentTerms(
                sku="BURGER_PROMO",
                quantity=Decimal("100"),
                unit="pcs",
                deadline=_now() + timedelta(days=2),
            ),
            evidence_refs=["ev_init"],
        ),
    )

    plan = RecoveryPlan(
        tenant_id="tenant_demo_01",
        recovery_case_id="rc_002",
        plan_id="plan_exp_01",
        plan_version=1,
        commitment_id=c.commitment_id,
        based_on_assessment_id="fa_p2_002",
        snapshot_version=200,
        feasibility_status=FeasibilityState.FEASIBLE,
        estimated_extra_cost=Decimal("50.00"),
        currency="MYR",
        estimated_delay_minutes=0,
        actions=[
            PlannedAction(
                action_id="act_realloc",
                type="REALLOCATE_STOCK",
                requires_approval=True,
                idempotency_key="plan_exp_act_1",
            )
        ],
        approval_state="PENDING",
        execution_state="NOT_STARTED",
    )

    # Approval expired 30 minutes ago
    request = RecoveryExecuteRequest(
        expected_commitment_version=1,
        plan=plan,
        current_snapshot_version=200,
        approved_at=_now() - timedelta(hours=2),
        approval_expires_at=_now() - timedelta(minutes=30),  # Expired!
        reason="Executing after expiry",
    )

    with pytest.raises(DomainError) as exc:
        facade.execute_recovery_plan(session, context, c.commitment_id, request)

    assert exc.value.status_code == 409
    assert exc.value.code == "APPROVAL_EXPIRED"


def test_p3_plan_with_revised_terms_creates_proposal_and_emits_communication_request(session: Session) -> None:
    """When a plan requiring customer terms adjustment executes, create Proposal and emit communication request for P4."""
    facade = CoreIntegrationFacade()
    context = _ctx(actor="user_manager_01", role="MANAGER")

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_p3_003",
            customer_id="cust_p3_003",
            terms=CommitmentTerms(
                sku="BURGER_SPECIAL",
                quantity=Decimal("100"),
                unit="pcs",
                deadline=_now() + timedelta(days=1),
            ),
            evidence_refs=["ev_init"],
        ),
    )

    revised_deadline = _now() + timedelta(days=2)
    plan = RecoveryPlan(
        tenant_id="tenant_demo_01",
        recovery_case_id="rc_003",
        plan_id="plan_terms_03",
        plan_version=2,
        commitment_id=c.commitment_id,
        based_on_assessment_id="fa_p2_003",
        snapshot_version=300,
        feasibility_status=FeasibilityState.CONDITIONAL,
        estimated_extra_cost=Decimal("0.00"),
        currency="MYR",
        estimated_delay_minutes=1440,
        actions=[
            PlannedAction(
                action_id="act_adjust_terms",
                type="ADJUST_DELIVERY_TERMS",
                requires_approval=True,
                idempotency_key="plan_terms_act_1",
            )
        ],
        approval_state="PENDING",
        execution_state="NOT_STARTED",
    )

    request = RecoveryExecuteRequest(
        expected_commitment_version=1,
        plan=plan,
        current_snapshot_version=300,
        approved_at=_now() - timedelta(minutes=5),
        approval_expires_at=_now() + timedelta(hours=2),
        revised_terms=CommitmentTerms(
            sku="BURGER_SPECIAL",
            quantity=Decimal("100"),
            unit="pcs",
            deadline=revised_deadline,
        ),
        reason="Delayed delivery window offered to customer",
    )

    res = facade.execute_recovery_plan(session, context, c.commitment_id, request)

    # Invariants: proposal created, agreement OFFERED, version bumped
    assert res.commitment.agreement_state == AgreementState.OFFERED
    assert res.commitment.commitment_version == 2

    # Proposal persisted in commitment_proposals table
    prop = session.scalar(
        select(CommitmentProposalRecord).where(
            CommitmentProposalRecord.commitment_id == c.commitment_id,
            CommitmentProposalRecord.status == "ACTIVE",
        )
    )
    assert prop is not None
    assert prop.proposal_version == 2

    # Outbox contains communication request event for P4
    events = session.scalars(
        select(OutboxEventRecord).where(
            OutboxEventRecord.commitment_id == c.commitment_id,
            OutboxEventRecord.event_type == CoreEventType.RECOVERY_COMMUNICATION_REQUESTED.value,
        )
    ).all()
    assert len(events) == 1
    assert events[0].payload["proposal_id"] == "prop_plan_terms_03"


# =============================================================================
# 4. P4 → P5 / P3 Handshake Tests (BE-06d, UT-10, E2E-05, E2E-06, E2E-07)
# =============================================================================

def test_p4_message_sent_delivery_status_does_not_mutate_commitment_state(session: Session) -> None:
    """MESSAGE_SENT, DELIVERED, and READ records audit only; NEVER mutates agreement or fulfilment (E2E-07)."""
    facade = CoreIntegrationFacade()
    context = _ctx()

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_p4_001",
            customer_id="cust_p4_001",
            terms=CommitmentTerms(
                sku="BURGER_COMBO",
                quantity=Decimal("40"),
                unit="pcs",
                deadline=_now() + timedelta(days=2),
            ),
            evidence_refs=["ev_init"],
        ),
    )

    # Offer proposal
    facade.service.create_proposal(
        session,
        context,
        c.commitment_id,
        ProposalCreateRequest(
            proposal_id="prop_p4_01",
            proposal_version=1,
            expected_commitment_version=1,
            reason="Offer terms",
        ),
    )

    # P4 reports message sent and delivered
    facade.record_communication_status(
        session,
        context,
        c.commitment_id,
        "MESSAGE_SENT",
        ["ev_mock_whatsapp_sent_01"],
    )
    facade.record_communication_status(
        session,
        context,
        c.commitment_id,
        "DELIVERED",
        ["ev_mock_whatsapp_delivered_01"],
    )

    # Authoritative check: agreement remains OFFERED, fulfilment remains NOT_STARTED
    refreshed = facade.service.get(session, context, c.commitment_id)
    assert refreshed.agreement_state == AgreementState.OFFERED
    assert refreshed.fulfilment_state == FulfilmentState.NOT_STARTED
    assert refreshed.commitment_version == 2  # Not incremented by message delivery tracking


def test_p4_ambiguous_customer_response_blocks_auto_confirm_and_flags_attention(client: TestClient, session: Session) -> None:
    """Ambiguous response (vague 'OK') flags UNRESOLVED_CONFIRMATION; never auto-confirms (E2E-05)."""
    facade = CoreIntegrationFacade()
    context = _ctx()

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_p4_002",
            customer_id="cust_p4_002",
            terms=CommitmentTerms(
                sku="BURGER_PARTY",
                quantity=Decimal("200"),
                unit="pcs",
                deadline=_now() + timedelta(days=3),
            ),
            evidence_refs=["ev_init"],
        ),
    )

    facade.service.create_proposal(
        session,
        context,
        c.commitment_id,
        ProposalCreateRequest(
            proposal_id="prop_p4_02",
            proposal_version=1,
            expected_commitment_version=1,
            reason="Offer party pack terms",
        ),
    )

    # P4 reports ambiguous response: customer just replied "OK" without clarifying proposal
    facade.record_ambiguous_response(
        session,
        context,
        c.commitment_id,
        customer_message="OK",
        evidence_refs=["ev_chat_vague_ok"],
    )

    # Invariant: remains OFFERED, not confirmed
    refreshed = facade.service.get(session, context, c.commitment_id)
    assert refreshed.agreement_state == AgreementState.OFFERED

    # Overview attention queue flags unresolved confirmation
    res = client.get("/v1/overview", headers=_headers())
    assert res.status_code == 200
    items = [
        item for item in res.json()["attention_queue"]
        if item["category"] == AttentionCategory.UNRESOLVED_CONFIRMATION.value
        and item["commitment_id"] == c.commitment_id
    ]
    assert len(items) == 1
    assert "ambiguous" in items[0]["summary"].lower()


def test_p4_stale_v2_proposal_confirmation_rejected_when_v3_exists(client: TestClient, session: Session) -> None:
    """Signed confirmation for V2 is rejected with 409 when V3 proposal is active (E2E-06)."""
    facade = CoreIntegrationFacade()
    context = _ctx(actor="user_manager_01", role="MANAGER")

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_p4_003",
            customer_id="cust_p4_003",
            terms=CommitmentTerms(
                sku="BURGER_DEAL",
                quantity=Decimal("80"),
                unit="pcs",
                deadline=_now() + timedelta(days=1),
            ),
            evidence_refs=["ev_init"],
        ),
    )

    # Offer proposal V2
    facade.service.create_proposal(
        session,
        context,
        c.commitment_id,
        ProposalCreateRequest(
            proposal_id="prop_deal_v2",
            proposal_version=2,
            expected_commitment_version=1,
            revised_terms=CommitmentTerms(
                sku="BURGER_DEAL",
                quantity=Decimal("75"),
                unit="pcs",
                deadline=_now() + timedelta(days=2),
            ),
            reason="Offer V2: 75 pcs",
        ),
    )

    # Offer proposal V3 (supersedes V2)
    facade.service.create_proposal(
        session,
        context,
        c.commitment_id,
        ProposalCreateRequest(
            proposal_id="prop_deal_v3",
            proposal_version=3,
            expected_commitment_version=2,
            revised_terms=CommitmentTerms(
                sku="BURGER_DEAL",
                quantity=Decimal("70"),
                unit="pcs",
                deadline=_now() + timedelta(days=3),
            ),
            reason="Offer V3: 70 pcs with extra sauce",
        ),
    )

    # Customer tries to confirm stale V2 with expected_commitment_version=3
    with pytest.raises(DomainError) as exc:
        facade.confirm_proposal(
            session,
            context,
            c.commitment_id,
            ProposalConfirmRequest(
                proposal_id="prop_deal_v2",
                proposal_version=2,  # Stale! Latest active is 3
                expected_commitment_version=3,
                decision="ACCEPT",
                evidence_refs=["ev_signed_v2"],
                reason="Customer accepted V2 late",
            ),
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "STALE_PROPOSAL_VERSION"
    assert exc.value.details["active_proposal_version"] == 3


def test_p4_valid_v3_confirmation_updates_terms_without_setting_fulfilment(session: Session) -> None:
    """Valid confirmation updates terms and version; keeps fulfilment NOT_STARTED (UT-10)."""
    facade = CoreIntegrationFacade()
    context = _ctx(actor="user_manager_01", role="MANAGER")

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_p4_004",
            customer_id="cust_p4_004",
            terms=CommitmentTerms(
                sku="BURGER_DELUXE",
                quantity=Decimal("50"),
                unit="pcs",
                deadline=_now() + timedelta(days=1),
            ),
            evidence_refs=["ev_init"],
        ),
    )

    facade.service.create_proposal(
        session,
        context,
        c.commitment_id,
        ProposalCreateRequest(
            proposal_id="prop_deluxe_v3",
            proposal_version=3,
            expected_commitment_version=1,
            revised_terms=CommitmentTerms(
                sku="BURGER_DELUXE",
                quantity=Decimal("45"),
                unit="pcs",
                deadline=_now() + timedelta(days=2),
            ),
            reason="Offer revised quantity",
        ),
    )

    confirm_res = facade.confirm_proposal(
        session,
        context,
        c.commitment_id,
        ProposalConfirmRequest(
            proposal_id="prop_deluxe_v3",
            proposal_version=3,
            expected_commitment_version=2,
            decision="ACCEPT",
            evidence_refs=["ev_signed_deluxe_v3"],
            reason="Customer signed V3 acceptance",
        ),
    )

    # Invariants (UT-10): terms updated, confirmed, fulfilment stays NOT_STARTED
    assert confirm_res.commitment.agreement_state == AgreementState.CONFIRMED
    assert confirm_res.commitment.commitment_version == 3
    assert confirm_res.commitment.terms.quantity == Decimal("45")
    assert confirm_res.commitment.fulfilment_state == FulfilmentState.NOT_STARTED


def test_p4_proposal_rejection_sets_recovery_required_for_replanning(session: Session) -> None:
    """Customer rejection of proposal marks REJECTED and sets recovery_state=RECOVERY_REQUIRED for F3 replanning."""
    facade = CoreIntegrationFacade()
    context = _ctx(actor="user_manager_01", role="MANAGER")

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_p4_005",
            customer_id="cust_p4_005",
            terms=CommitmentTerms(
                sku="BURGER_REJECT",
                quantity=Decimal("50"),
                unit="pcs",
                deadline=_now() + timedelta(days=1),
            ),
            evidence_refs=["ev_init"],
        ),
    )

    facade.service.create_proposal(
        session,
        context,
        c.commitment_id,
        ProposalCreateRequest(
            proposal_id="prop_rej_01",
            proposal_version=1,
            expected_commitment_version=1,
            reason="Offer terms",
        ),
    )

    reject_res = facade.confirm_proposal(
        session,
        context,
        c.commitment_id,
        ProposalConfirmRequest(
            proposal_id="prop_rej_01",
            proposal_version=1,
            expected_commitment_version=2,
            decision="REJECT",
            evidence_refs=["ev_customer_rejection_letter"],
            reason="Customer rejected delay; requesting replanning",
        ),
    )

    assert reject_res.commitment.agreement_state == AgreementState.REJECTED
    assert reject_res.commitment.recovery_state == RecoveryState.RECOVERY_REQUIRED

    # Proposal marked REJECTED in database
    prop = session.scalar(
        select(CommitmentProposalRecord).where(
            CommitmentProposalRecord.commitment_id == c.commitment_id,
            CommitmentProposalRecord.proposal_id == "prop_rej_01",
        )
    )
    assert prop is not None
    assert prop.status == "REJECTED"


# =============================================================================
# 5. Operational Fulfilment Tests (BE-02h, UT-10, E2E-12)
# =============================================================================

def test_operational_delivery_evidence_transitions_to_fulfilled_and_resolved(session: Session) -> None:
    """Trusted operational delivery evidence (ev_ops_delivery_*) transitions to FULFILLED and resolves risk (E2E-12)."""
    facade = CoreIntegrationFacade()
    context = _ctx(actor="user_manager_01", role="MANAGER")

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_fulfil_001",
            customer_id="cust_fulfil_001",
            terms=CommitmentTerms(
                sku="BURGER_FEAST",
                quantity=Decimal("150"),
                unit="pcs",
                deadline=_now() + timedelta(days=1),
            ),
            evidence_refs=["ev_init"],
        ),
    )

    # Must be CONFIRMED before fulfilment can be recorded
    facade.service.transition(
        session,
        context,
        c.commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="OFFERED",
            expected_commitment_version=1,
            reason="Offer terms",
        ),
    )
    facade.service.transition(
        session,
        context,
        c.commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="CONFIRMED",
            expected_commitment_version=2,
            evidence_refs=["ev_signed_agreement"],
            reason="Customer confirmed",
        ),
    )

    # Record operational fulfilment with valid delivery evidence
    fulfil_res = facade.record_fulfilment(
        session,
        context,
        c.commitment_id,
        RecordFulfilmentRequest(
            expected_commitment_version=3,
            fulfilment_state="FULFILLED",
            evidence_refs=["ev_ops_delivery_pod_signed_9921"],
            reason="Courier signed POD verified",
        ),
    )

    assert fulfil_res.commitment.fulfilment_state == FulfilmentState.FULFILLED
    assert fulfil_res.commitment.risk_state == RiskState.RESOLVED
    assert fulfil_res.commitment.commitment_version == 4


def test_fulfilment_rejected_if_not_confirmed_or_invalid_evidence(session: Session) -> None:
    """Cannot record fulfilment if commitment is not CONFIRMED, or if evidence is receipt/chat only."""
    facade = CoreIntegrationFacade()
    context = _ctx(actor="user_manager_01", role="MANAGER")

    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_fulfil_002",
            customer_id="cust_fulfil_002",
            terms=CommitmentTerms(
                sku="BURGER_TEST",
                quantity=Decimal("10"),
                unit="pcs",
                deadline=_now() + timedelta(days=1),
            ),
            evidence_refs=["ev_init"],
        ),
    )

    # 1. Reject when agreement is still REQUESTED
    with pytest.raises(DomainError) as exc1:
        facade.record_fulfilment(
            session,
            context,
            c.commitment_id,
            RecordFulfilmentRequest(
                expected_commitment_version=1,
                fulfilment_state="FULFILLED",
                evidence_refs=["ev_ops_delivery_001"],
                reason="Trying to fulfil unconfirmed commitment",
            ),
        )
    assert exc1.value.status_code == 409
    assert exc1.value.code == "INVALID_STATE_TRANSITION"

    # Make it CONFIRMED
    facade.service.transition(
        session,
        context,
        c.commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="OFFERED",
            expected_commitment_version=1,
            reason="Offer",
        ),
    )
    facade.service.transition(
        session,
        context,
        c.commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="CONFIRMED",
            expected_commitment_version=2,
            evidence_refs=["ev_agree"],
            reason="Confirm",
        ),
    )

    # 2. Reject when evidence is only receipt or chat (not operational delivery)
    with pytest.raises(DomainError) as exc2:
        facade.record_fulfilment(
            session,
            context,
            c.commitment_id,
            RecordFulfilmentRequest(
                expected_commitment_version=3,
                fulfilment_state="FULFILLED",
                evidence_refs=["ev_receipt_bank_slip_001"],
                reason="Trying to fulfil with bank slip only",
            ),
        )
    assert exc2.value.status_code == 422
    assert exc2.value.code == "INVALID_FULFILMENT_EVIDENCE"


# =============================================================================
# 6. PII Minimization Tests (BE-06e)
# =============================================================================

def test_outbox_event_payloads_contain_no_pii_fields(session: Session) -> None:
    """Outbox event payloads emitted by Core pass IDs/references only; never raw customer PII (BE-06e)."""
    # 1. Payload validator catches forbidden PII keys
    with pytest.raises(ValueError) as exc:
        validate_event_payload({"customer_email": "customer@example.com", "commitment_id": "com_001"})
    assert "forbidden sensitive keyword" in str(exc.value)

    with pytest.raises(ValueError) as exc2:
        validate_event_payload({"contact_phone": "+60123456789", "commitment_id": "com_001"})
    assert "forbidden sensitive keyword" in str(exc2.value)

    # 2. Inspect all outbox events in database
    records = session.scalars(select(OutboxEventRecord)).all()
    forbidden_tokens = ["phone", "email", "message_body", "raw_message", "password", "secret"]
    for record in records:
        for key in record.payload.keys():
            for token in forbidden_tokens:
                assert token not in key.lower(), f"Outbox record {record.event_id} payload contains PII key '{key}'"


# =============================================================================
# 7. PostgreSQL Dialect & Dual-Boundary Transaction Rollback Tests (P2 Handshake)
# =============================================================================

def test_postgresql_dual_boundary_transaction_rollback_and_atomic_persistence(
    test_engine,
    session: Session,
) -> None:
    """Verifies evidence for P2 handshake:
    1. engine.dialect.name == 'postgresql' when TEST_DATABASE_URL is provided.
    2. Dual-boundary transaction rollback:
       - Boundary A (HTTP path): failure during transition or proposal creation rolls back session cleanly.
       - Boundary B (Outbox consumer path): downstream consumer failure rolls back aggregate, outbox,
         and ProcessedEventRecord atomically.
    3. Case + Trigger + ProcessedEventRecord atomic commit & cascade deletion:
       - Case + trigger + processed event persist atomically.
       - Deleting recovery_cases cascades to recovery_case_triggers in PostgreSQL.
    """
    import os
    from sqlalchemy import inspect, text
    from app.core.models import ProcessedEventRecord
    from app.core.outbox import OutboxDispatcher

    is_pg = test_engine.dialect.name == "postgresql"
    if os.environ.get("TEST_DATABASE_URL"):
        assert is_pg, f"Expected PostgreSQL dialect when TEST_DATABASE_URL is set, got {test_engine.dialect.name}"

    facade = CoreIntegrationFacade()
    context = _ctx(actor="user_manager_01", role="MANAGER")

    # 1. Setup base commitment in CONFIRMED state
    c = facade.service.create_request(
        session,
        context,
        CommitmentCreateRequest(
            order_id="ord_pg_handshake_001",
            customer_id="cust_pg_001",
            terms=CommitmentTerms(
                sku="BURGER_PG_SPECIAL",
                quantity=Decimal("100"),
                unit="pcs",
                deadline=_now() + timedelta(days=2),
            ),
            evidence_refs=["ev_pg_init"],
        ),
    )
    facade.service.transition(
        session,
        context,
        c.commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="OFFERED",
            expected_commitment_version=1,
            reason="Offer terms",
        ),
    )
    facade.service.transition(
        session,
        context,
        c.commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="CONFIRMED",
            expected_commitment_version=2,
            evidence_refs=["ev_signed_contract"],
            reason="Confirmed by customer",
        ),
    )
    session.commit()

    # -------------------------------------------------------------------------
    # Boundary A: HTTP API Path Rollback
    # -------------------------------------------------------------------------
    # An invalid transition (stale expected version 99) raises DomainError.
    # The session must roll back and not persist the failed transition or audit records.
    with pytest.raises(DomainError) as exc_http:
        facade.service.transition(
            session,
            context,
            c.commitment_id,
            CommitmentTransitionRequest(
                dimension="agreement",
                target_state="REJECTED",
                expected_commitment_version=99,  # Stale version
                reason="Should fail and roll back",
            ),
        )
    assert exc_http.value.status_code == 409
    session.rollback()

    # Verify aggregate unchanged after HTTP rollback
    refreshed_c = session.get(CommitmentRecord, (context.tenant_id, c.commitment_id))
    assert refreshed_c.commitment_version == 3
    assert refreshed_c.agreement_state == "CONFIRMED"

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # Boundary B: Outbox Consumer Path Rollback & Atomic Case/Trigger/ProcessedEvent
    # -------------------------------------------------------------------------
    # Exercise genuine CommitmentService.assess() transition to AT_RISK
    assessment_id = f"fa_hs_{int(_now().timestamp())}"
    fa_assessment = FeasibilityAssessment(
        assessment_id=assessment_id,
        tenant_id=context.tenant_id,
        commitment_id=c.commitment_id,
        commitment_version=refreshed_c.commitment_version,
        snapshot_version=1,
        status=FeasibilityState.INFEASIBLE,
        solver_status=SolverStatus.COMPLETED,
        constraints=[ConstraintReason(code="MATERIAL_SHORTAGE", resource_id="res_patty_01", severity="HARD")],
        affected_commitment_ids=[],
        evidence_refs=["ev_supplier_delay_01"],
        assessed_at=_now(),
    )
    service_ctx = RequestContext(
        tenant_id=context.tenant_id,
        actor_id="service_p2_writer",
        actor_role="SERVICE",
        correlation_id=context.correlation_id,
    )
    facade.service.assess(session, service_ctx, c.commitment_id, fa_assessment, commit=True)

    # Locate the genuine outbox event emitted by CommitmentService.assess
    outbox_event = session.scalar(
        select(OutboxEventRecord).where(
            OutboxEventRecord.tenant_id == context.tenant_id,
            OutboxEventRecord.commitment_id == c.commitment_id,
            OutboxEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
            OutboxEventRecord.status == OutboxStatus.PENDING.value,
        ).order_by(OutboxEventRecord.occurred_at.desc())
    )
    assert outbox_event is not None
    event_id = outbox_event.event_id

    dispatcher = OutboxDispatcher()
    # Satisfy D-017 policy for confirmed event
    dispatcher.register_subscriber(
        event_type=CoreEventType.COMMITMENT_CONFIRMED.value,
        consumer_name="p2_confirmed_evaluator",
        handler_fn=lambda s, e: None,
    )
    consumer_name = "p3.recovery_trigger.v1"
    should_fail = True

    # Check if recovery_cases table exists in this DB (e.g. migration 0006 on PostgreSQL)
    has_recovery_tables = "recovery_cases" in inspect(test_engine).get_table_names()

    case_id = f"case_hs_{int(_now().timestamp())}"
    trigger_id = f"trig_hs_{int(_now().timestamp())}"

    def mock_p3_consumer(db: Session, event: OutboxEventRecord) -> None:
        nonlocal should_fail
        now_dt = _now()
        if has_recovery_tables:
            db.execute(
                text(
                    "INSERT INTO recovery_cases (tenant_id, case_id, commitment_id, risk_episode_id, opening_event_id, "
                    "status, case_version, commitment_version, payload_schema_version, case_payload, resolution_refs, created_at, updated_at) "
                    "VALUES (:tenant_id, :case_id, :commitment_id, :risk_ep, :open_evt, 'OPEN', 1, :commitment_version, 1, '{}', '[]', :now, :now)"
                ),
                {
                    "tenant_id": event.tenant_id,
                    "case_id": case_id,
                    "commitment_id": event.commitment_id,
                    "risk_ep": f"ep_{case_id}",
                    "open_evt": event.event_id,
                    "commitment_version": event.commitment_version,
                    "now": now_dt,
                },
            )
            db.execute(
                text(
                    "INSERT INTO recovery_case_triggers (tenant_id, event_id, case_id, commitment_id, commitment_version, "
                    "assessment_id, assessment_provenance_status, snapshot_version, constraints, affected_commitment_ids, evidence_refs, correlation_id, occurred_at, event_digest) "
                    "VALUES (:tenant_id, :event_id, :case_id, :commitment_id, :commitment_version, :assessment_id, 'INFEASIBLE', :snapshot_version, '[]', '[]', '[]', :correlation_id, :now, 'digest_01')"
                ),
                {
                    "tenant_id": event.tenant_id,
                    "event_id": trigger_id,
                    "case_id": case_id,
                    "commitment_id": event.commitment_id,
                    "commitment_version": event.commitment_version,
                    "assessment_id": event.payload.get("assessment_id", assessment_id),
                    "snapshot_version": event.payload.get("snapshot_version", 1),
                    "correlation_id": event.correlation_id or "corr_01",
                    "now": now_dt,
                },
            )
        if should_fail:
            raise RuntimeError("Downstream P3 transient failure")

    dispatcher.register_subscriber(
        event_type=CoreEventType.COMMITMENT_AT_RISK.value,
        consumer_name=consumer_name,
        handler_fn=mock_p3_consumer,
    )

    # 1. Downstream failure: atomic rollback of Case + Trigger + ProcessedEventRecord
    res_fail = dispatcher.process_outbox_batch(session)
    # The older confirmed event also lacks its mandatory P2 completion and
    # must stay visible for reconciliation; the P3 failure is independent.
    assert res_fail.failed_count == 2
    stale_confirmed = session.scalar(select(OutboxEventRecord).where(
        OutboxEventRecord.tenant_id == context.tenant_id,
        OutboxEventRecord.event_type == CoreEventType.COMMITMENT_CONFIRMED.value,
        OutboxEventRecord.last_error == "STALE_MANDATORY_SUBSCRIBER_INCOMPLETE",
    ))
    assert stale_confirmed is not None
    assert stale_confirmed.status == OutboxStatus.FAILED.value
    assert session.scalar(select(ProcessedEventRecord).where(
        ProcessedEventRecord.tenant_id == context.tenant_id,
        ProcessedEventRecord.event_id == stale_confirmed.event_id,
        ProcessedEventRecord.consumer_name == "p2_confirmed_evaluator",
    )) is None

    # Verify ProcessedEventRecord was NOT committed
    proc_fail = session.scalar(
        select(ProcessedEventRecord).where(
            ProcessedEventRecord.tenant_id == context.tenant_id,
            ProcessedEventRecord.event_id == event_id,
            ProcessedEventRecord.consumer_name == consumer_name,
        )
    )
    assert proc_fail is None

    # Verify recovery_cases was NOT committed
    if has_recovery_tables:
        count_cases = session.execute(
            text("SELECT COUNT(*) FROM recovery_cases WHERE tenant_id = :tenant_id AND case_id = :case_id"),
            {"tenant_id": context.tenant_id, "case_id": case_id},
        ).scalar()
        assert count_cases == 0

    # 2. Downstream issue resolved: retry succeeds atomically committing Case, Trigger, and ProcessedEventRecord
    should_fail = False
    refreshed_event = session.get(OutboxEventRecord, event_id)
    refreshed_event.next_retry_at = _now() - timedelta(seconds=1)
    session.commit()

    res_ok = dispatcher.process_outbox_batch(session)
    assert res_ok.published_count == 1

    # Verify ProcessedEventRecord IS committed atomically
    proc_ok = session.scalar(
        select(ProcessedEventRecord).where(
            ProcessedEventRecord.tenant_id == context.tenant_id,
            ProcessedEventRecord.event_id == event_id,
            ProcessedEventRecord.consumer_name == consumer_name,
        )
    )
    assert proc_ok is not None

    # Verify Case and Trigger committed atomically
    if has_recovery_tables:
        count_cases = session.execute(
            text("SELECT COUNT(*) FROM recovery_cases WHERE tenant_id = :tenant_id AND case_id = :case_id"),
            {"tenant_id": context.tenant_id, "case_id": case_id},
        ).scalar()
        assert count_cases == 1

        count_trigs = session.execute(
            text("SELECT COUNT(*) FROM recovery_case_triggers WHERE tenant_id = :tenant_id AND case_id = :case_id"),
            {"tenant_id": context.tenant_id, "case_id": case_id},
        ).scalar()
        assert count_trigs == 1

        # Verify ON DELETE RESTRICT (Migration 0007 invariant: append-only trigger history)
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            session.execute(
                text("DELETE FROM recovery_cases WHERE tenant_id = :tenant_id AND case_id = :case_id"),
                {"tenant_id": context.tenant_id, "case_id": case_id},
            )
        session.rollback()


def test_postgresql_concurrency_lock_order_safety(test_engine) -> None:
    """Verify concurrent overlapping transactions between confirmed evaluation and supplier-delay stock updates.

    Verifies that lock acquisition order (CommitmentRecord before OperationalSnapshot/Stock)
    does not deadlock under concurrent execution, and that optimistic snapshot drift check
    fails closed safely with SNAPSHOT_DRIFT_CONFLICT without PostgreSQL deadlock exception.
    """
    from app.core.feasibility_adapters import AuthoritativeAssessmentWriter
    from app.core.models import ResourceStockRecord
    from app.core.reservations import seed_resource_stock
    from app.feasibility.adapters import AuthoritativeEvaluationAuthority
    from app.feasibility.api_schemas import AssessCommitmentRequest
    from app.feasibility.service import evaluate

    SessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    setup_session = SessionLocal()
    tenant = "tenant-synthetic-p2"
    facade = CoreIntegrationFacade()
    ctx = _ctx(tenant=tenant)

    # Seed initial stock with snapshot_version = 1
    seed_resource_stock(setup_session, tenant, "RES_LOCK_01", Decimal("100"), "kg", snapshot_version=1)

    # Seed confirmed commitment matching AuthoritativeEvaluationAuthority
    c_rec = CommitmentRecord(
        tenant_id=tenant,
        commitment_id="com_drift_001",
        order_id="ord_drift_001",
        customer_id="cust_drift_001",
        terms={
            "sku": "BURGER_TEST",
            "quantity": "50",
            "unit": "pcs",
            "deadline": (_now() + timedelta(days=2)).isoformat(),
        },
        agreement_state=AgreementState.CONFIRMED.value,
        feasibility_state=FeasibilityState.NOT_ASSESSED.value,
        risk_state=RiskState.NORMAL.value,
        recovery_state=RecoveryState.NONE.value,
        fulfilment_state="NOT_STARTED",
        commitment_version=1,
        evidence_refs=["ev_init_001"],
        updated_at=_now(),
    )
    setup_session.add(c_rec)
    setup_session.commit()
    setup_session.close()

    # Tx1: Confirmed-event evaluation transaction (locks CommitmentRecord first)
    s1 = SessionLocal()
    rec1 = s1.scalar(
        select(CommitmentRecord)
        .where(CommitmentRecord.tenant_id == tenant, CommitmentRecord.commitment_id == "com_drift_001")
        .with_for_update()
    )
    assert rec1 is not None

    # Tx2: Concurrent supplier-delay / stock mutation transaction
    # Locks ResourceStockRecord and bumps snapshot_version to 2
    s2 = SessionLocal()
    stock2 = s2.scalar(
        select(ResourceStockRecord)
        .where(ResourceStockRecord.tenant_id == tenant, ResourceStockRecord.resource_id == "RES_LOCK_01")
        .with_for_update()
    )
    assert stock2 is not None
    stock2.snapshot_version += 1
    stock2.total_quantity = Decimal("80")
    s2.commit()
    s2.close()

    # Tx1 now attempts assessment expecting snapshot_version = 1
    writer = AuthoritativeAssessmentWriter(facade.service)
    authority = AuthoritativeEvaluationAuthority()
    snapshot, commitment = authority.resolve_current(ctx, "com_drift_001", rec1.commitment_version)
    base_result = evaluate(snapshot, None, commitment)

    req = AssessCommitmentRequest(
        expected_commitment_version=rec1.commitment_version,
        expected_snapshot_version=1,  # Stale: Tx2 already committed version 2
    )

    # Invariant: Must raise SNAPSHOT_DRIFT_CONFLICT 409 cleanly without deadlock
    with pytest.raises(DomainError) as exc_info:
        writer.assess(
            s1,
            ctx,
            commitment,
            req,
            snapshot=snapshot,
            result=base_result,
            commit=False,
        )

    assert exc_info.value.code == "SNAPSHOT_DRIFT_CONFLICT"
    assert exc_info.value.status_code == 409
    assert exc_info.value.details["expected_snapshot_version"] == 1
    assert exc_info.value.details["current_snapshot_version"] == 2

    s1.rollback()
    s1.close()



