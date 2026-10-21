"""Unit tests for Section 4 alias methods and policy authorization (A7, R43, R55)."""

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.policy import authorize
from app.core.schemas import (
    AgreementState,
    CommitmentCreateRequest,
    CommitmentTerms,
    ConstraintReason,
    FeasibilityAssessment,
    FeasibilityState,
    ProposalConfirmRequest,
    ProposalCreateRequest,
    RecordFulfilmentRequest,
)
from app.core.service import CommitmentService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_policy_authorization() -> None:
    # OWNER and MANAGER authorized
    authorize("user_owner_01", "OWNER", "EXECUTE_PLAN")
    authorize("user_manager_01", "MANAGER", "EXECUTE_PLAN")

    # Non-consequential action allowed for staff
    authorize("user_staff_01", "STAFF", "VIEW_REPORT")

    # Consequential action forbidden for staff
    with pytest.raises(DomainError) as exc_info:
        authorize("user_staff_01", "STAFF", "EXECUTE_PLAN")
    assert exc_info.value.code == "APPROVAL_REQUIRED"
    assert exc_info.value.status_code == 403


def test_section_4_alias_methods(session: Session) -> None:
    service = CommitmentService()
    ctx = RequestContext(
        tenant_id="tenant_alias_test",
        actor_id="user_owner_01",
        actor_role="OWNER",
        correlation_id="corr_alias_test",
    )

    # 1. request alias
    req = CommitmentCreateRequest(
        order_id="ord_alias_001",
        customer_id="cust_alias_001",
        terms=CommitmentTerms(
            sku="BURGER",
            quantity="50",
            unit="pcs",
            deadline=_now() + timedelta(days=2),
        ),
        evidence_refs=["ev_order_01"],
    )
    com = service.request(session, ctx, req)
    assert com.agreement_state == AgreementState.REQUESTED
    assert com.commitment_id.startswith("com_")

    # 2. offer alias
    prop = service.offer(
        session,
        ctx,
        com.commitment_id,
        ProposalCreateRequest(
            expected_commitment_version=1,
            revised_terms=CommitmentTerms(
                sku="BURGER",
                quantity="50",
                unit="pcs",
                deadline=_now() + timedelta(days=3),
            ),
            reason="Offer alternative deadline",
        ),
    )
    proposal_id = str(prop.domain_event.payload["proposal_id"])
    assert proposal_id.startswith("prop_")

    # 3. confirm alias
    trans = service.confirm(
        session,
        ctx,
        com.commitment_id,
        ProposalConfirmRequest(
            proposal_id=proposal_id,
            proposal_version=1,
            expected_commitment_version=2,
            decision="ACCEPT",
            reason="Customer accepted",
            evidence_refs=["ev_accept_01"],
        ),
    )
    assert trans.commitment.agreement_state == AgreementState.CONFIRMED

    # 4. mark_risk delegate (requires trusted service context per D-013)
    service_ctx = RequestContext(
        tenant_id=ctx.tenant_id,
        actor_id="service_p2_evaluator",
        actor_role="SERVICE",
        correlation_id="corr_alias_eval",
    )
    fa = FeasibilityAssessment(
        assessment_id="fa_alias_01",
        tenant_id=ctx.tenant_id,
        commitment_id=com.commitment_id,
        commitment_version=3,
        snapshot_version=1,
        status=FeasibilityState.INFEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="COMPLETED",
        assessed_at=_now(),
    )
    at_risk_com = service.mark_risk(session, service_ctx, com.commitment_id, fa)
    assert at_risk_com.risk_state.value == "AT_RISK"

    # 5. start_recovery delegate
    rec_trans = service.start_recovery(
        session,
        ctx,
        com.commitment_id,
        expected_commitment_version=4,
        reason="Trigger recovery planning",
    )
    assert rec_trans.commitment.recovery_state.value == "PLANNING"

    # 6. record_action_outcome delegate
    act_trans = service.record_action_outcome(
        session,
        ctx,
        com.commitment_id,
        expected_commitment_version=5,
        dimension="recovery",
        target_state="PENDING_APPROVAL",
        reason="Plan formulated, awaiting approval",
        evidence_refs=["ev_rec_plan_01"],
    )
    assert act_trans.commitment.recovery_state.value == "PENDING_APPROVAL"

    # 7. verify_fulfilment alias
    ful_trans = service.verify_fulfilment(
        session,
        ctx,
        com.commitment_id,
        RecordFulfilmentRequest(
            expected_commitment_version=6,
            evidence_refs=["ev_pod_01"],
            reason="Operational delivery verified by carrier scan",
            fulfilment_state="FULFILLED",
        ),
    )
    assert ful_trans.commitment.fulfilment_state.value == "FULFILLED"
