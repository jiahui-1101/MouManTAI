from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.dependencies import RequestContext
from app.core.events import CoreEventType, OutboxStatus
from app.core.integration import CoreIntegrationFacade
from app.core.models import (
    AuditEventRecord,
    Base,
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
)
from app.core.schemas import (
    AgreementState,
    BusinessContext,
    CommitmentCreateRequest,
    CommitmentTerms,
    CommitmentTransitionRequest,
    ContextStatus,
    CustomerIdentityStatus,
    FeasibilityState,
    FulfilmentState,
    ProposalConfirmRequest,
    ProposalCreateRequest,
    RequestedItem,
    RiskState,
)
from app.core.service import CommitmentService


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_amendment_protection_on_confirmed_commitment(db_session: Session) -> None:
    """Verifies that an incoming context update on a CONFIRMED commitment:
    1. Does NOT overwrite agreed customer terms on the commitment record.
    2. Creates an active CommitmentProposalRecord with revised terms.
    3. Transitions commitment agreement_state to OFFERED.
    4. Increments commitment_version.
    5. Emits CoreEventType.COMMITMENT_PROPOSAL_OFFERED outbox and audit events.
    """
    service = CommitmentService()
    facade = CoreIntegrationFacade(service=service)
    ctx = RequestContext(
        tenant_id="tenant_p1_amend",
        actor_id="user_staff_01",
        actor_role="STAFF",
        correlation_id="corr_amend_01",
    )

    # 1. Create and confirm initial commitment
    orig_terms = CommitmentTerms(
        sku="BURGER_ORIG",
        quantity=Decimal("100"),
        unit="pcs",
        deadline=_now() + timedelta(days=2),
    )
    com = service.request(
        db_session,
        ctx,
        CommitmentCreateRequest(
            order_id="ord_amend_101",
            customer_id="cust_amend_101",
            terms=orig_terms,
            evidence_refs=["ev_initial_order"],
        ),
    )
    # Move to OFFERED then CONFIRMED
    service.transition(
        db_session,
        ctx,
        com.commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="OFFERED",
            expected_commitment_version=1,
            reason="Offer initial terms",
        ),
    )
    manager_ctx = RequestContext(
        tenant_id="tenant_p1_amend",
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_amend_mgr",
    )
    service.transition(
        db_session,
        manager_ctx,
        com.commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="CONFIRMED",
            expected_commitment_version=2,
            evidence_refs=["ev_signed_agreement"],
            reason="Customer signed initial terms",
        ),
    )
    record = db_session.get(CommitmentRecord, (ctx.tenant_id, com.commitment_id))
    assert record is not None
    assert record.agreement_state == AgreementState.CONFIRMED.value
    assert record.commitment_version == 3
    assert record.terms["sku"] == "BURGER_ORIG"
    assert record.terms["quantity"] == "100"

    # 2. Context update arrives with revised order (quantity 150)
    amended_ctx = BusinessContext(
        tenant_id="tenant_p1_amend",
        context_id="ctx_amend_002",
        order_id="ord_amend_101",
        customer_id="cust_amend_101",
        customer_identity_status=CustomerIdentityStatus.LINK_VERIFIED,
        source_message_ids=["msg_amend_002"],
        requested_items=[
            RequestedItem(sku="BURGER_ORIG", quantity=Decimal("150"), unit="pcs"),
        ],
        requested_delivery_at=_now() + timedelta(days=3),
        field_evidence={"quantity": ["ev_msg_amend_qty"]},
        conflicts=[],
        missing_fields=[],
        context_version=2,
        status=ContextStatus.INFORMATION_READY,
    )

    updated_com = facade.handle_context_updated(db_session, ctx, amended_ctx)

    # Invariant 3: Original confirmed terms MUST NOT be overwritten
    db_session.refresh(record)
    assert record.terms["sku"] == "BURGER_ORIG"
    assert record.terms["quantity"] == "100"
    assert record.agreement_state == AgreementState.OFFERED.value
    assert record.commitment_version == 4

    # A ProposalRecord is created with revised terms
    prop = db_session.scalars(
        select(CommitmentProposalRecord).where(
            CommitmentProposalRecord.tenant_id == ctx.tenant_id,
            CommitmentProposalRecord.commitment_id == com.commitment_id,
            CommitmentProposalRecord.status == "ACTIVE",
        )
    ).first()
    assert prop is not None
    assert prop.proposal_version == 1
    assert prop.revised_terms["sku"] == "BURGER_ORIG"
    assert prop.revised_terms["quantity"] == "150"

    # Outbox event COMMITMENT_PROPOSAL_OFFERED is emitted for the amendment (version 4)
    outbox_evt = db_session.scalars(
        select(OutboxEventRecord).where(
            OutboxEventRecord.tenant_id == ctx.tenant_id,
            OutboxEventRecord.commitment_id == com.commitment_id,
            OutboxEventRecord.event_type == CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
            OutboxEventRecord.commitment_version == 4,
        )
    ).first()
    assert outbox_evt is not None
    assert outbox_evt.payload["proposal_id"] == prop.proposal_id


def test_multi_item_support_and_zero_guessing_delivery(db_session: Session) -> None:
    """Verifies that:
    1. Multi-item requests store all items in terms['items'].
    2. Missing requested_delivery_at is NOT defaulted to now; deadline is None,
       and requires_manual_review is flagged with missing_fields=['deadline'].
    """
    facade = CoreIntegrationFacade()
    ctx = RequestContext(
        tenant_id="tenant_p1_multi",
        actor_id="user_staff_01",
        actor_role="STAFF",
        correlation_id="corr_multi_01",
    )

    b_ctx = BusinessContext(
        tenant_id="tenant_p1_multi",
        context_id="ctx_multi_001",
        order_id="ord_multi_001",
        customer_id="cust_multi_001",
        customer_identity_status=CustomerIdentityStatus.LINK_VERIFIED,
        source_message_ids=["msg_multi_001"],
        requested_items=[
            RequestedItem(sku="BURGER_BUN", quantity=Decimal("50"), unit="pcs"),
            RequestedItem(sku="PATTY_BEEF", quantity=Decimal("50"), unit="pcs"),
            RequestedItem(sku="CHEESE_SLICE", quantity=Decimal("100"), unit="pcs"),
        ],
        requested_delivery_at=None,  # Missing delivery time
        field_evidence={"sku": ["ev_multi_sku"]},
        conflicts=[],
        missing_fields=[],
        context_version=1,
        status=ContextStatus.INFORMATION_READY,
    )

    com = facade.handle_context_updated(db_session, ctx, b_ctx)

    record = db_session.get(CommitmentRecord, (ctx.tenant_id, com.commitment_id))
    assert record is not None

    # Multi-item items array is populated
    assert "items" in record.terms
    assert len(record.terms["items"]) == 3
    assert record.terms["items"][0]["sku"] == "BURGER_BUN"
    assert record.terms["items"][1]["sku"] == "PATTY_BEEF"
    assert record.terms["items"][2]["sku"] == "CHEESE_SLICE"

    # Zero-guessing delivery: deadline is None, flagged for review
    assert record.terms.get("deadline") is None
    assert record.terms.get("requires_manual_review") is True
    assert "deadline" in record.terms.get("missing_fields", [])


def test_confirm_proposal_verifies_proposal_identity_and_derives_event_payload(db_session: Session) -> None:
    """Verifies that confirm_proposal:
    1. Validates proposal_id matches the active proposal row (raises 409 PROPOSAL_ID_MISMATCH on mismatch).
    2. Derives outbox event payload's proposal identity directly from the verified row.
    """
    from app.core.errors import DomainError

    service = CommitmentService()
    ctx = RequestContext(
        tenant_id="tenant_p2_recon",
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_p2_recon",
        causation_id="caus_p2_recon",
    )

    created = service.create_request(
        db_session,
        ctx,
        CommitmentCreateRequest(
            order_id="ord_prop_check",
            customer_id="cust_prop_check",
            terms=CommitmentTerms(sku="BURGER", quantity=Decimal("10"), unit="pcs", deadline=_now() + timedelta(days=2)),
            evidence_refs=["ev_create"],
        ),
    )

    service.create_proposal(
        db_session,
        ctx,
        created.commitment_id,
        ProposalCreateRequest(
            proposal_id="prop_deal_v1_canonical",
            proposal_version=1,
            expected_commitment_version=1,
            revised_terms=CommitmentTerms(sku="BURGER", quantity=Decimal("12"), unit="pcs", deadline=_now() + timedelta(days=2)),
            reason="Offer 12 pcs deal",
            evidence_refs=["ev_prop"],
        ),
    )

    # 1. Attempt confirmation with mismatching proposal_id on matching proposal_version
    with pytest.raises(DomainError) as exc:
        service.confirm_proposal(
            db_session,
            ctx,
            created.commitment_id,
            ProposalConfirmRequest(
                proposal_id="prop_wrong_id",
                proposal_version=1,
                expected_commitment_version=2,
                decision="ACCEPT",
                evidence_refs=["ev_signed"],
                reason="Customer accepted",
            ),
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "PROPOSAL_ID_MISMATCH"
    assert exc.value.details["active_proposal_id"] == "prop_deal_v1_canonical"
    assert exc.value.details["submitted_proposal_id"] == "prop_wrong_id"

    # 2. Confirm with correct proposal_id succeeds and outbox payload contains verified proposal identity
    res = service.confirm_proposal(
        db_session,
        ctx,
        created.commitment_id,
        ProposalConfirmRequest(
            proposal_id="prop_deal_v1_canonical",
            proposal_version=1,
            expected_commitment_version=2,
            decision="ACCEPT",
            evidence_refs=["ev_signed"],
            reason="Customer accepted",
        ),
    )

    assert res.commitment.agreement_state == AgreementState.CONFIRMED

    # Assert outbox event has verified proposal identity
    outbox = db_session.scalars(
        select(OutboxEventRecord).where(
            OutboxEventRecord.tenant_id == ctx.tenant_id,
            OutboxEventRecord.commitment_id == created.commitment_id,
            OutboxEventRecord.event_type == CoreEventType.COMMITMENT_CONFIRMED.value,
        )
    ).first()
    assert outbox is not None
    assert outbox.payload["proposal_id"] == "prop_deal_v1_canonical"
    assert outbox.payload["proposal_version"] == 1
    assert outbox.payload["decision"] == "ACCEPT"

