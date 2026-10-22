"""Unit tests for Section 4 alias methods and policy authorization (A7, R43, R55)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.policy import authorize
from app.core.schemas import (
    AgreementState,
    CommitmentCreateRequest,
    CommitmentTerms,
    CommitmentTransitionRequest,
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


def test_d015_proposal_terms_safety(session: Session) -> None:
    """Verifies D-015 proposal terms invariants:
    1. Offering a proposal preserves existing accepted Commitment terms.
    2. Rejecting a proposal preserves existing terms.
    3. Explicit customer acceptance applies revised terms with correct version updates.
    """
    service = CommitmentService()
    ctx = RequestContext(
        tenant_id="tenant_d015_test",
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_d015_test",
    )

    # 1. Create and confirm original commitment
    orig_terms = CommitmentTerms(
        sku="BURGER_ORIGINAL",
        quantity="100",
        unit="pcs",
        deadline=_now() + timedelta(days=3),
    )
    com = service.request(
        session,
        ctx,
        CommitmentCreateRequest(
            order_id="ord_d015_001",
            customer_id="cust_d015_001",
            terms=orig_terms,
            evidence_refs=["ev_d015_init"],
        ),
    )
    service.transition(
        session,
        ctx,
        com.commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="OFFERED",
            expected_commitment_version=1,
            reason="Initial offer",
        ),
    )
    conf_trans = service.transition(
        session,
        ctx,
        com.commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="CONFIRMED",
            expected_commitment_version=2,
            evidence_refs=["ev_d015_signed_init"],
            reason="Initial confirmation",
        ),
    )
    assert conf_trans.commitment.agreement_state == AgreementState.CONFIRMED
    assert conf_trans.commitment.terms.sku == "BURGER_ORIGINAL"
    assert conf_trans.commitment.terms.quantity == Decimal("100")

    # 2. Offer proposal with revised terms (quantity 80)
    revised_terms_v1 = CommitmentTerms(
        sku="BURGER_REVISED_V1",
        quantity="80",
        unit="pcs",
        deadline=_now() + timedelta(days=4),
    )
    offer_trans = service.create_proposal(
        session,
        ctx,
        com.commitment_id,
        ProposalCreateRequest(
            proposal_id="prop_d015_01",
            proposal_version=1,
            expected_commitment_version=3,
            revised_terms=revised_terms_v1,
            evidence_refs=["ev_plan_v1"],
            reason="Offer reduced quantity",
        ),
    )
    assert offer_trans.commitment.agreement_state == AgreementState.OFFERED
    # Invariant: offering proposal MUST NOT overwrite accepted commitment terms
    assert offer_trans.commitment.terms.sku == "BURGER_ORIGINAL"
    assert offer_trans.commitment.terms.quantity == Decimal("100")

    refreshed_offered = service.get(session, ctx, com.commitment_id)
    assert refreshed_offered.terms.sku == "BURGER_ORIGINAL"
    assert refreshed_offered.terms.quantity == Decimal("100")

    # 3. Customer rejects proposal
    rej_trans = service.confirm_proposal(
        session,
        ctx,
        com.commitment_id,
        ProposalConfirmRequest(
            proposal_id="prop_d015_01",
            proposal_version=1,
            expected_commitment_version=4,
            decision="REJECT",
            evidence_refs=["ev_customer_reject_note"],
            reason="Customer declined revised terms",
        ),
    )
    assert rej_trans.commitment.agreement_state == AgreementState.REJECTED
    # Invariant: rejecting proposal preserves original terms
    assert rej_trans.commitment.terms.sku == "BURGER_ORIGINAL"
    assert rej_trans.commitment.terms.quantity == Decimal("100")

    # 4. Offer second proposal (quantity 95)
    revised_terms_v2 = CommitmentTerms(
        sku="BURGER_REVISED_V2",
        quantity="95",
        unit="pcs",
        deadline=_now() + timedelta(days=5),
    )
    offer_trans_2 = service.create_proposal(
        session,
        ctx,
        com.commitment_id,
        ProposalCreateRequest(
            proposal_id="prop_d015_02",
            proposal_version=2,
            expected_commitment_version=5,
            revised_terms=revised_terms_v2,
            evidence_refs=["ev_plan_v2"],
            reason="Offer second revision",
        ),
    )
    assert offer_trans_2.commitment.agreement_state == AgreementState.OFFERED
    assert offer_trans_2.commitment.terms.sku == "BURGER_ORIGINAL"
    assert offer_trans_2.commitment.terms.quantity == Decimal("100")

    # 5. Customer explicitly accepts second proposal
    accept_trans = service.confirm_proposal(
        session,
        ctx,
        com.commitment_id,
        ProposalConfirmRequest(
            proposal_id="prop_d015_02",
            proposal_version=2,
            expected_commitment_version=6,
            decision="ACCEPT",
            evidence_refs=["ev_customer_signed_amendment"],
            reason="Customer signed amendment",
        ),
    )
    assert accept_trans.commitment.agreement_state == AgreementState.CONFIRMED
    # Invariant: explicit customer acceptance applies revised terms
    assert accept_trans.commitment.terms.sku == "BURGER_REVISED_V2"
    assert accept_trans.commitment.terms.quantity == Decimal("95")
    assert accept_trans.commitment.commitment_version == 7

