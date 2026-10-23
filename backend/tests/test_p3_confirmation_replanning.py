"""P3 response adapter regressions against P4's persisted synthetic producer."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.communication.confirmation_schemas import CreateConfirmation
from app.communication.models import ConfirmationDecisionRecord
from app.communication.schemas import CreateCommunicationRequest
from app.communication.service import CommunicationRequestService
from app.communication.tests.test_confirmation_integration import (
    confirmation_service,
    fixture_sent,
)
from app.communication.tests.test_confirmations import FixtureInbound, text
from app.communication.tests.test_requests import NOW
from app.communication.tests.test_review import MANAGER
from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import CoreEventType
from app.core.manager_approval import ManagerApprovalRecord, ManagerApprovalService
from app.core.models import (
    AuditEventRecord,
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
)
from app.core.outbox import OutboxDispatcher
from app.core.schemas import (
    AgreementState,
    CommitmentTerms,
    DomainEvent,
    FeasibilityState,
    RiskState,
)
from app.recovery.confirmation_responses import (
    CONSUMER_NAME,
    P3ConfirmationContextResolver,
    P3ConfirmationResponseConsumer,
    _json_payloads_match_exactly,
    register_p3_confirmation_response_consumer,
)
from app.recovery.durable_actions import DurableActionService
from app.recovery.durable_communication import (
    DurableCommunicationHandoff,
    RequestCommunicationInput,
)
from app.recovery.durable_plans import DurablePlanService, RecoveryPlanRecord
from app.recovery.eventing import (
    EventPublicationReceipt,
    EventPublicationStatus,
    PendingRecoveryEventPublisher,
    RecoveryEventType,
)
from app.recovery.fixtures import load_demo_recovery_inputs
from app.recovery.models import RecoveryCaseStatus, RecoveryStrategy
from app.recovery.persistence import RecoveryCaseRecord
from app.recovery.proposal_identity import proposal_id_for_plan, require_proposal_binding
from app.recovery.service import RecoveryPlanner
from tests.test_p2_persisted_sources import _prepared_review

pytest_plugins = ("app.communication.tests.test_migration_persistence",)


@pytest.mark.parametrize(
    ("left", "right", "matches"),
    [
        (True, 1, False),
        (1, 1.0, False),
        (1, "1", False),
        ({"rows": [{"verified": True}]}, {"rows": [{"verified": 1}]}, False),
        ({"rows": [{"quantity": 1}]}, {"rows": [{"quantity": 1.0}]}, False),
        ({"rows": [{"verified": True}]}, {"rows": [{"verified": True}]}, True),
        ({"first": 1, "second": [True]}, {"second": [True], "first": 1}, True),
        ([1, 2], [2, 1], False),
        ({"first": 1}, {"first": 1, "extra": None}, False),
    ],
)
def test_audit_json_comparison_is_type_exact(left, right, matches):
    assert _json_payloads_match_exactly(left, right) is matches


class _TestOnlyReplanPublisher:
    """Port double for exercising P3 writes; it does not publish to Core/P5."""

    def __init__(self):
        self.events = []

    def publish(self, event, *, db=None, context=None):
        del db, context
        self.events.append(event)
        return EventPublicationReceipt(
            event_id=event.event_id,
            status=EventPublicationStatus.PUBLISHED,
            attempted_at=datetime.now(UTC),
        )


def test_canonical_proposal_identity_preserves_v1_and_uniquely_versions_successors():
    assert proposal_id_for_plan("plan_123", 1) == "plan_123"
    assert proposal_id_for_plan("plan_123", 2) == "plan_123_v2"
    assert proposal_id_for_plan("plan_123", 3) == "plan_123_v3"
    assert len({proposal_id_for_plan("plan_123", version) for version in (1, 2, 3)}) == 3
    assert require_proposal_binding("plan_123", 1, None, None) == ("plan_123", 1)
    assert require_proposal_binding("plan_123", 2, "plan_123_v2", 2) == ("plan_123_v2", 2)
    for proposal_id, proposal_version in (("plan_123", 2), ("plan_123__v2", 2), ("plan_123_v2", 1)):
        with pytest.raises(DomainError) as error:
            require_proposal_binding("plan_123", 2, proposal_id, proposal_version)
        assert error.value.code == "PROPOSAL_PLAN_IDENTITY_CONFLICT"


@pytest.mark.parametrize(
    ("intent", "event_type", "response_state"),
    [
        ("REJECT", "confirmation.rejected", "REJECTED"),
        ("COUNTEROFFER", "confirmation.counteroffer_received", "COUNTEROFFER_RECEIVED"),
    ],
)
def test_p3_validates_the_real_p4_terminal_event_and_tenant_binding(
    session, intent, event_type, response_state,
):
    sent, drafts, reviews = fixture_sent(session)
    inbound = FixtureInbound()
    p4 = confirmation_service(session, drafts, reviews, inbound)
    challenge = p4.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
    message = text(challenge, intent)
    if intent == "COUNTEROFFER":
        message += ' changes:{"quantity":"80"}'
    command = inbound.add(message)
    p4.respond(
        MANAGER,
        challenge.confirmation.confirmation_id,
        command,
        challenge.confirmation_token,
        now=NOW,
    )

    source = session.scalar(select(OutboxEventRecord).where(
        OutboxEventRecord.event_type == event_type,
    ))
    assert source is not None
    event = DomainEvent(
        event_id=source.event_id,
        schema_version=1,
        event_type=source.event_type,
        tenant_id=source.tenant_id,
        commitment_id=source.commitment_id,
        commitment_version=source.commitment_version,
        correlation_id=source.correlation_id,
        causation_id=source.causation_id,
        occurred_at=source.occurred_at.replace(tzinfo=UTC) if source.occurred_at.tzinfo is None else source.occurred_at,
        payload=source.payload,
    )
    assert P3ConfirmationResponseConsumer._validate_p4_evidence(session, event) == (
        intent, response_state,
    )
    if intent == "COUNTEROFFER":
        assert P3ConfirmationResponseConsumer._counteroffer_terms(session, event) == {"quantity": "80"}
        decision = session.get(ConfirmationDecisionRecord, (event.tenant_id, event.payload["decision_id"]))
        assert decision is not None
        original_changes = decision.proposed_changes
        decision.proposed_changes = {"quantity": "81"}
        session.flush()
        with pytest.raises(DomainError) as error:
            P3ConfirmationResponseConsumer._validate_p4_evidence(session, event)
        assert error.value.code == "P4_RESPONSE_BINDING_MISMATCH"
        decision.proposed_changes = original_changes
        session.flush()

    foreign_event = event.model_copy(update={"tenant_id": "tenant_foreign"})
    with pytest.raises(DomainError) as error:
        P3ConfirmationResponseConsumer._validate_p4_evidence(session, foreign_event)
    assert error.value.code == "P4_RESPONSE_SOURCE_MISMATCH"


def test_p3_rejects_p4_events_with_modified_payload(session):
    sent, drafts, reviews = fixture_sent(session)
    inbound = FixtureInbound()
    p4 = confirmation_service(session, drafts, reviews, inbound)
    challenge = p4.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
    command = inbound.add(text(challenge, "REJECT"))
    p4.respond(
        MANAGER,
        challenge.confirmation.confirmation_id,
        command,
        challenge.confirmation_token,
        now=NOW,
    )

    source = session.scalar(select(OutboxEventRecord).where(
        OutboxEventRecord.event_type == "confirmation.rejected",
    ))
    assert source is not None
    forged_payload = {**source.payload, "proposal_version": source.payload["proposal_version"] + 1}
    event = DomainEvent(
        event_id=source.event_id,
        schema_version=1,
        event_type=source.event_type,
        tenant_id=source.tenant_id,
        commitment_id=source.commitment_id,
        commitment_version=source.commitment_version,
        correlation_id=source.correlation_id,
        causation_id=source.causation_id,
        occurred_at=source.occurred_at.replace(tzinfo=UTC) if source.occurred_at.tzinfo is None else source.occurred_at,
        payload=forged_payload,
    )
    with pytest.raises(DomainError) as error:
        P3ConfirmationResponseConsumer._validate_p4_evidence(session, event)
    assert error.value.code == "P4_RESPONSE_SOURCE_MISMATCH"


def test_p3_audit_payload_match_is_exact_and_ambiguity_fails_closed(session, monkeypatch):
    event = _p4_response_event(session, monkeypatch, intent="REJECT")
    audit = session.scalar(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.commitment_id == event.commitment_id,
        AuditEventRecord.event_type == event.event_type,
        AuditEventRecord.causation_id == event.causation_id,
    ))
    assert audit is not None
    original_payload = dict(audit.new_state)
    audit.new_state = {**original_payload, "proposal_version": original_payload["proposal_version"] + 1}
    with pytest.raises(DomainError) as missing:
        P3ConfirmationResponseConsumer._validate_p4_evidence(session, event)
    assert missing.value.code == "P4_RESPONSE_AUDIT_MISSING"

    audit.new_state = original_payload
    duplicate_data = {column.name: getattr(audit, column.name) for column in AuditEventRecord.__table__.columns}
    duplicate_data["audit_id"] = "audit_duplicate_confirmation_response"
    session.add(AuditEventRecord(**duplicate_data))
    session.flush()
    with pytest.raises(DomainError) as ambiguous:
        P3ConfirmationResponseConsumer._validate_p4_evidence(session, event)
    assert ambiguous.value.code == "P4_RESPONSE_AUDIT_AMBIGUOUS"


def _persist_exact_p3_plan_for_p4_request(session, plan_version=2, evaluated_version=9):
    p2_fixtures = pytest.importorskip("app.feasibility.production_fixtures")
    snapshot, commitment = p2_fixtures.build_production_example()
    commitment = commitment.model_copy(update={
        "tenant_id": "tenant_a",
        "commitment_id": "com_001",
        "commitment_version": 10,
    })
    inputs = load_demo_recovery_inputs()
    planner = RecoveryPlanner(inputs=replace(
        inputs,
        commitment=commitment,
        assessment=inputs.assessment.model_copy(update={
            "tenant_id": commitment.tenant_id,
            "commitment_id": commitment.commitment_id,
            "commitment_version": evaluated_version,
        }),
        snapshot=inputs.snapshot.model_copy(update={
            "snapshot_id": snapshot.operational.snapshot_id,
            "snapshot_version": snapshot.operational.snapshot_version,
            "captured_at": snapshot.operational.captured_at,
        }),
    ))
    case = planner.generate(
        commitment.tenant_id,
        commitment.commitment_id,
        expected_commitment_version=commitment.commitment_version,
    )
    source_plan = next(
        plan for plan in case.plans
        if plan.strategy == RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT
    )
    plan = source_plan.model_copy(update={
        "plan_id": "plan_001",
        "plan_version": plan_version,
        "proposal_id": proposal_id_for_plan("plan_001", plan_version),
        "proposal_version": plan_version,
        "core_commitment_version": 10,
        "snapshot_id": snapshot.operational.snapshot_id,
        "snapshot_version": snapshot.operational.snapshot_version,
        "evaluation": source_plan.evaluation.model_copy(update={
            "plan_id": "plan_001",
            "plan_version": plan_version,
            "commitment_version": evaluated_version,
        }),
    })
    case = case.model_copy(update={
        "commitment": commitment,
        "commitment_version": commitment.commitment_version,
        "status": RecoveryCaseStatus.OPTIONS_READY,
        "plans": [plan],
        "storage_mode": "DURABLE_DATABASE",
    })
    if session.get(CommitmentRecord, (case.tenant_id, case.commitment_id)) is None:
        session.add(CommitmentRecord(
            tenant_id=commitment.tenant_id,
            commitment_id=commitment.commitment_id,
            order_id=commitment.order_id,
            customer_id=commitment.customer_id,
            terms=commitment.terms.model_dump(mode="json"),
            agreement_state=getattr(commitment.agreement_state, "value", commitment.agreement_state),
            feasibility_state=getattr(commitment.feasibility_state, "value", commitment.feasibility_state),
            risk_state=getattr(commitment.risk_state, "value", commitment.risk_state),
            recovery_state=getattr(commitment.recovery_state, "value", commitment.recovery_state),
            fulfilment_state=getattr(commitment.fulfilment_state, "value", commitment.fulfilment_state),
            commitment_version=commitment.commitment_version,
            evidence_refs=list(commitment.evidence_refs),
            updated_at=case.updated_at,
        ))
        session.flush()
    session.add(RecoveryCaseRecord(
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        commitment_id=case.commitment_id,
        risk_episode_id="evt_p3_response_context_opened",
        opening_event_id="evt_p3_response_context_opened",
        status=case.status.value,
        case_version=case.case_version,
        commitment_version=case.commitment_version,
        payload_schema_version=1,
        case_payload=case.model_dump(mode="json"),
        resolution_refs=[],
        created_at=case.created_at,
        updated_at=case.updated_at,
    ))
    session.flush()
    session.add(RecoveryPlanRecord(
        tenant_id=case.tenant_id,
        plan_id=plan.plan_id,
        plan_version=plan.plan_version,
        case_id=case.case_id,
        commitment_id=case.commitment_id,
        assessment_id=plan.based_on_assessment_id,
        snapshot_id=plan.snapshot_id or "snapshot_context_test",
        snapshot_version=plan.snapshot_version,
        core_commitment_version=10,
        evaluated_commitment_version=evaluated_version,
        payload=plan.model_dump(mode="json"),
        status="PENDING_APPROVAL",
        created_at=case.created_at,
    ))
    session.flush()
    return case, plan


def test_recovery_plan_orm_rejects_equal_core_and_evaluation_versions(session):
    constraint = next(
        item for item in RecoveryPlanRecord.__table__.constraints
        if item.name == "ck_recovery_plan_core_after_evaluation"
    )
    assert str(constraint.sqltext) == "core_commitment_version > evaluated_commitment_version"
    case, plan = _persist_exact_p3_plan_for_p4_request(session)
    session.add(RecoveryPlanRecord(
        tenant_id=case.tenant_id,
        plan_id="invalid_equal_version_plan",
        plan_version=1,
        case_id=case.case_id,
        commitment_id=case.commitment_id,
        assessment_id=plan.based_on_assessment_id,
        snapshot_id=plan.snapshot_id or "snapshot_context_test_equal",
        snapshot_version=plan.snapshot_version,
        core_commitment_version=9,
        evaluated_commitment_version=9,
        payload=plan.model_dump(mode="json"),
        status="PENDING_APPROVAL",
        created_at=case.created_at,
    ))
    with pytest.raises(IntegrityError):
        session.flush()


def test_durable_plan_generation_rejects_unadvanced_evaluation_version(monkeypatch):
    snapshot, commitment = pytest.importorskip(
        "app.feasibility.production_fixtures",
    ).build_production_example()
    current_version = commitment.commitment_version
    commitment = commitment.model_copy(update={
        "agreement_state": AgreementState.CONFIRMED,
        "risk_state": RiskState.AT_RISK,
        "feasibility_state": FeasibilityState.INFEASIBLE,
    })
    inputs = load_demo_recovery_inputs()
    assessment = inputs.assessment.model_copy(update={
        "tenant_id": commitment.tenant_id,
        "commitment_id": commitment.commitment_id,
        "commitment_version": current_version,
    })
    sources = [
        row.model_copy(update={"commitment_version": current_version})
        if row.commitment_id == commitment.commitment_id else row
        for row in snapshot.operational.confirmed_commitments
    ]
    snapshot = snapshot.model_copy(update={
        "operational": snapshot.operational.model_copy(update={
            "confirmed_commitments": tuple(sources),
        }),
    })
    service = DurablePlanService()
    monkeypatch.setattr(
        service,
        "_current",
        lambda *_args, **_kwargs: (SimpleNamespace(status=RecoveryCaseStatus.OPTIONS_READY), commitment, snapshot, assessment),
    )
    with pytest.raises(DomainError) as error:
        service.generate(
            object(),
            RequestContext(commitment.tenant_id, "p3_test", "SERVICE", "corr_equal_versions"),
            commitment.commitment_id,
            expected_commitment_version=current_version,
            assessment_id=None,
        )
    assert error.value.code == "P2_COMMITMENT_BINDING_MISMATCH"


def _persist_authorized_offer_transition(
    session,
    *,
    case,
    plan,
    commitment,
    previous_version: int,
    offered_version: int,
    proposal_terms: dict,
    offered_at: datetime,
):
    """Persist the exact approval → Core proposal offer evidence P3 must prove."""
    plan = plan.model_copy(update={
        "core_commitment_version": previous_version,
        "proposal_id": proposal_id_for_plan(plan.plan_id, plan.plan_version),
        "proposal_version": plan.plan_version,
    })
    case = case.model_copy(update={
        "commitment": commitment.model_copy(update={
            "commitment_version": previous_version,
            "agreement_state": AgreementState.CONFIRMED,
        }),
        "commitment_version": previous_version,
        "plans": [plan],
        "status": RecoveryCaseStatus.OPTIONS_READY,
        "storage_mode": "DURABLE_DATABASE",
    })
    core = session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id))
    if core is None:
        core = CommitmentRecord(
            tenant_id=commitment.tenant_id,
            commitment_id=commitment.commitment_id,
            order_id=commitment.order_id,
            customer_id=commitment.customer_id,
            terms=commitment.terms.model_dump(mode="json"),
            agreement_state="OFFERED",
            feasibility_state=getattr(commitment.feasibility_state, "value", commitment.feasibility_state),
            risk_state=getattr(commitment.risk_state, "value", commitment.risk_state),
            recovery_state=getattr(commitment.recovery_state, "value", commitment.recovery_state),
            fulfilment_state=getattr(commitment.fulfilment_state, "value", commitment.fulfilment_state),
            commitment_version=offered_version,
            evidence_refs=list(commitment.evidence_refs),
            updated_at=offered_at,
        )
        session.add(core)
    else:
        core.agreement_state = "OFFERED"
        core.commitment_version = offered_version
        core.updated_at = offered_at
    core.terms = commitment.terms.model_dump(mode="json")
    session.flush()

    case_row = session.get(RecoveryCaseRecord, (case.tenant_id, case.case_id))
    if case_row is None:
        case_row = RecoveryCaseRecord(
            tenant_id=case.tenant_id,
            case_id=case.case_id,
            commitment_id=case.commitment_id,
            risk_episode_id=f"episode_{case.case_id}",
            opening_event_id=f"evt_open_{case.case_id}",
            status=case.status.value,
            case_version=case.case_version,
            commitment_version=case.commitment_version,
            payload_schema_version=1,
            case_payload=case.model_dump(mode="json"),
            resolution_refs=[],
            created_at=case.created_at,
            updated_at=case.updated_at,
        )
        session.add(case_row)
    else:
        case_row.status = case.status.value
        case_row.case_version = case.case_version
        case_row.commitment_version = previous_version
        case_row.case_payload = case.model_dump(mode="json")
        case_row.updated_at = case.updated_at
    session.flush()

    plan_row = session.get(RecoveryPlanRecord, (plan.tenant_id, plan.plan_id, plan.plan_version))
    values = {
        "tenant_id": plan.tenant_id,
        "plan_id": plan.plan_id,
        "plan_version": plan.plan_version,
        "case_id": case.case_id,
        "commitment_id": plan.commitment_id,
        "assessment_id": plan.based_on_assessment_id,
        "snapshot_id": plan.snapshot_id,
        "snapshot_version": plan.snapshot_version,
        "core_commitment_version": previous_version,
        "evaluated_commitment_version": plan.evaluation.commitment_version,
        "payload": plan.model_dump(mode="json"),
        "status": "PENDING_APPROVAL",
        "created_at": offered_at - timedelta(minutes=2),
    }
    if plan_row is None:
        plan_row = RecoveryPlanRecord(**values)
        session.add(plan_row)
    else:
        for key, value in values.items():
            setattr(plan_row, key, value)
    session.flush()

    approval_id = f"approval_{plan.plan_id}_v{plan.plan_version}"
    approval_audit_id = f"audit_{approval_id}"
    proposal_id = proposal_id_for_plan(plan.plan_id, plan.plan_version)
    refs = [approval_audit_id, plan.based_on_assessment_id, plan.snapshot_id]
    approved_terms = CommitmentTerms.model_validate(proposal_terms).model_dump(mode="json")
    proposal = session.get(CommitmentProposalRecord, (plan.tenant_id, proposal_id))
    if proposal is None:
        proposal = CommitmentProposalRecord(
            tenant_id=plan.tenant_id,
            proposal_id=proposal_id,
            commitment_id=plan.commitment_id,
            proposal_version=plan.plan_version,
            revised_terms=approved_terms,
            status="ACTIVE",
            reason=f"Approved recovery plan {plan.plan_id} v{plan.plan_version}",
            evidence_refs=refs,
            created_at=offered_at,
            updated_at=offered_at,
        )
        session.add(proposal)
    else:
        proposal.commitment_id = plan.commitment_id
        proposal.proposal_version = plan.plan_version
        proposal.revised_terms = approved_terms
        proposal.status = "ACTIVE"
        proposal.evidence_refs = refs
        proposal.updated_at = offered_at
    session.flush()

    approval = ManagerApprovalRecord(
        tenant_id=plan.tenant_id,
        approval_id=approval_id,
        idempotency_key=f"key_{approval_id}",
        commitment_id=plan.commitment_id,
        case_id=case.case_id,
        plan_id=plan.plan_id,
        plan_version=plan.plan_version,
        proposal_id=proposal_id,
        proposal_version=plan.plan_version,
        snapshot_id=plan.snapshot_id,
        snapshot_version=plan.snapshot_version,
        commitment_version=previous_version,
        decision="APPROVED",
        action_scope=["CREATE_DELIVERY_CHANGE_PROPOSAL"],
        approved_terms=approved_terms,
        approved_amount=plan.estimated_extra_cost,
        actor_id="manager_fixture",
        actor_role="MANAGER",
        reason="Authorized exact proposal terms",
        decided_at=offered_at - timedelta(minutes=3),
        expires_at=offered_at + timedelta(hours=2),
        audit_id=approval_audit_id,
    )
    session.add(approval)
    session.add(AuditEventRecord(
        audit_id=approval_audit_id,
        tenant_id=plan.tenant_id,
        commitment_id=plan.commitment_id,
        event_type="recovery.plan_approved",
        actor_id=approval.actor_id,
        actor_role=approval.actor_role,
        dimension="recovery",
        previous_state={"plan_id": plan.plan_id},
        new_state={
            "approval_id": approval_id,
            "decision": "APPROVED",
            "plan_id": plan.plan_id,
            "plan_version": plan.plan_version,
            "snapshot_id": plan.snapshot_id,
            "commitment_version": previous_version,
        },
        evidence_refs=[plan.based_on_assessment_id, plan.snapshot_id],
        reason=approval.reason,
        correlation_id="corr_manager_approval",
        causation_id=None,
        occurred_at=approval.decided_at,
    ))

    previous_state = {
        "agreement_state": "CONFIRMED",
        "feasibility_state": getattr(core.feasibility_state, "value", core.feasibility_state),
        "risk_state": getattr(core.risk_state, "value", core.risk_state),
        "recovery_state": getattr(core.recovery_state, "value", core.recovery_state),
        "fulfilment_state": getattr(core.fulfilment_state, "value", core.fulfilment_state),
        "commitment_version": previous_version,
    }
    current_state = {**previous_state, "agreement_state": "OFFERED", "commitment_version": offered_version}
    offer_audit_id = f"audit_offer_{plan.plan_id}_v{plan.plan_version}"
    offer_event_id = f"evt_offer_{plan.plan_id}_v{plan.plan_version}"
    session.add(AuditEventRecord(
        audit_id=offer_audit_id,
        tenant_id=plan.tenant_id,
        commitment_id=plan.commitment_id,
        event_type=CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
        actor_id=approval.actor_id,
        actor_role=approval.actor_role,
        dimension="agreement",
        previous_state=previous_state,
        new_state=current_state,
        evidence_refs=refs,
        reason=f"Approved recovery plan {plan.plan_id} v{plan.plan_version}",
        correlation_id="corr_core_offer",
        causation_id=approval_id,
        occurred_at=offered_at,
    ))
    session.add(OutboxEventRecord(
        event_id=offer_event_id,
        tenant_id=plan.tenant_id,
        event_type=CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
        commitment_id=plan.commitment_id,
        commitment_version=offered_version,
        correlation_id="corr_core_offer",
        causation_id=approval_id,
        occurred_at=offered_at,
        payload={
            "commitment_id": plan.commitment_id,
            "proposal_id": proposal_id,
            "proposal_version": plan.plan_version,
            "audit_id": offer_audit_id,
            "evidence_refs": refs,
        },
        attempts=0,
        status="PUBLISHED",
    ))
    session.flush()
    return case, plan, case_row, plan_row, proposal, approval


def _p4_response_event(session, monkeypatch, intent="REJECT", plan_version=2):
    # Adapt P4's deliberately noncanonical generic fixture to a P3-owned
    # versioned source before P4 creates the request/confirmation chain.
    from app.communication.tests import test_migration_persistence as p4_fixture

    original_seed = p4_fixture.seed_core

    def canonical_seed(db):
        original_seed(db)
        old = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
        assert old is not None
        old.proposal_id = proposal_id_for_plan("plan_001", plan_version)
        old.proposal_version = plan_version
        source = db.get(OutboxEventRecord, "evt_001")
        assert source is not None
        source.payload = {
            **source.payload,
            "plan_version": plan_version,
            "proposal_id": old.proposal_id,
            "proposal_version": plan_version,
        }
        db.commit()

    monkeypatch.setattr(p4_fixture, "seed_core", canonical_seed)
    sent, drafts, reviews = fixture_sent(session)
    inbound = FixtureInbound()
    p4 = confirmation_service(session, drafts, reviews, inbound)
    challenge = p4.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
    message = text(challenge, intent)
    if intent == "COUNTEROFFER":
        message += ' changes:{"quantity":"80"}'
    command = inbound.add(message)
    p4.respond(
        MANAGER,
        challenge.confirmation.confirmation_id,
        command,
        challenge.confirmation_token,
        now=NOW,
    )
    source = session.scalar(select(OutboxEventRecord).where(
        OutboxEventRecord.event_type == (
            "confirmation.rejected" if intent == "REJECT"
            else "confirmation.counteroffer_received"
        ),
    ))
    assert source is not None
    return DomainEvent(
        event_id=source.event_id,
        schema_version=1,
        event_type=source.event_type,
        tenant_id=source.tenant_id,
        commitment_id=source.commitment_id,
        commitment_version=source.commitment_version,
        correlation_id=source.correlation_id,
        causation_id=source.causation_id,
        occurred_at=source.occurred_at.replace(tzinfo=UTC)
        if source.occurred_at.tzinfo is None else source.occurred_at,
        payload=source.payload,
    )


@pytest.mark.parametrize("plan_version", [1, 2])
def test_typed_resolver_follows_p4_source_request_and_outbound_to_exact_p3_plan(
    session, monkeypatch, plan_version,
):
    event = _p4_response_event(session, monkeypatch, plan_version=plan_version)
    case, plan = _persist_exact_p3_plan_for_p4_request(session, plan_version)

    resolved = P3ConfirmationContextResolver().resolve(session, event)

    assert resolved.tenant_id == "tenant_a"
    assert resolved.commitment_id == "com_001"
    assert resolved.recovery_case_id == case.case_id
    assert (resolved.plan_id, resolved.plan_version) == (plan.plan_id, plan.plan_version)
    assert (resolved.proposal_id, resolved.proposal_version) == (
        proposal_id_for_plan(plan.plan_id, plan_version), plan_version,
    )
    assert resolved.communication_id == event.payload["communication_id"]
    assert resolved.outbound_id == event.payload["outbound_id"]
    assert resolved.source_communication_event_id == "evt_001"
    assert resolved.trusted_evidence_ref == event.event_id
    assert resolved.evidence_refs == event.payload["evidence_refs"]


def test_typed_resolver_fails_closed_on_ambiguous_plan_association(session, monkeypatch):
    event = _p4_response_event(session, monkeypatch)
    case, plan = _persist_exact_p3_plan_for_p4_request(session)
    duplicate = plan.model_copy()
    session.add(RecoveryPlanRecord(
        tenant_id=case.tenant_id,
        plan_id="another_plan_same_proposal",
        plan_version=duplicate.plan_version,
        case_id=case.case_id,
        commitment_id=case.commitment_id,
        assessment_id=duplicate.based_on_assessment_id,
        snapshot_id=duplicate.snapshot_id or "snapshot_context_test_duplicate",
        snapshot_version=duplicate.snapshot_version,
        core_commitment_version=10,
        evaluated_commitment_version=duplicate.evaluation.commitment_version,
        payload=duplicate.model_dump(mode="json"),
        status="PENDING_APPROVAL",
        created_at=case.created_at,
    ))
    session.flush()

    with pytest.raises(DomainError) as error:
        P3ConfirmationContextResolver().resolve(session, event)

    assert error.value.code == "RECOVERY_PROPOSAL_PLAN_AMBIGUOUS"


def test_v1_approval_cannot_authorize_a_v2_communication_handoff(session, monkeypatch):
    _p4_response_event(session, monkeypatch)
    case, plan = _persist_exact_p3_plan_for_p4_request(session)
    monkeypatch.setattr(
        "app.recovery.durable_communication.trusted_isolated_manager",
        lambda _context, _key: "manager_test",
    )
    monkeypatch.setattr(
        "app.recovery.durable_communication.ManagerApprovalService.require_active",
        lambda _self, _db, _context, _plan: SimpleNamespace(
            approval_id="approval_v1", proposal_id=plan.plan_id, proposal_version=1,
        ),
    )
    with pytest.raises(DomainError) as error:
        DurableCommunicationHandoff().request(
            session,
            RequestContext(case.tenant_id, "manager_test", "MANAGER", "corr_approval_v2"),
            None,
            plan.plan_id,
            RequestCommunicationInput(
                expected_plan_version=plan.plan_version,
                expected_commitment_version=11,
                expected_snapshot_version=plan.snapshot_version,
            ),
        )
    assert error.value.code == "APPROVAL_SCOPE_CONFLICT"
    assert session.get(CommitmentProposalRecord, (case.tenant_id, "plan_001_v2")) is not None


def test_p5_writer_and_p3_handoff_bind_real_v2_approval_and_revoke(session, monkeypatch):
    plan, manager, key = _prepared_review(session, monkeypatch)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", manager.actor_id)
    approval_service = ManagerApprovalService()
    v1 = approval_service.decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=1, expected_commitment_version=2,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="p3-v1-approval", reason="Authorize original plan",
    )
    v1_handoff = DurableCommunicationHandoff().request(
        session, manager, key, plan.plan_id,
        RequestCommunicationInput(
            expected_plan_version=1, expected_commitment_version=2,
            expected_snapshot_version=plan.snapshot_version,
        ),
    )
    assert (v1_handoff.proposal_id, v1_handoff.proposal_version) == (plan.plan_id, 1)
    prior = session.get(RecoveryPlanRecord, (manager.tenant_id, plan.plan_id, 1))
    assert prior is not None
    payload = dict(prior.payload)
    payload.update({
        "plan_version": 2,
        "proposal_id": proposal_id_for_plan(plan.plan_id, 2),
        "proposal_version": 2,
        "core_commitment_version": v1_handoff.commitment_version,
        "evaluation": {**payload["evaluation"], "plan_version": 2},
    })
    prior.status = "SUPERSEDED"
    successor = RecoveryPlanRecord(
        tenant_id=prior.tenant_id, plan_id=prior.plan_id, plan_version=2,
        case_id=prior.case_id, commitment_id=prior.commitment_id,
        assessment_id=prior.assessment_id, snapshot_id=prior.snapshot_id,
        snapshot_version=prior.snapshot_version,
        core_commitment_version=v1_handoff.commitment_version,
        evaluated_commitment_version=prior.evaluated_commitment_version,
        payload=payload, status="PENDING_APPROVAL", created_at=datetime.now(UTC),
    )
    session.add(successor)
    session.commit()
    command = RequestCommunicationInput(
        expected_plan_version=2, expected_commitment_version=v1_handoff.commitment_version,
        expected_snapshot_version=plan.snapshot_version,
    )
    with pytest.raises(DomainError) as stale:
        DurableCommunicationHandoff().request(session, manager, key, plan.plan_id, command)
    assert stale.value.code == "APPROVAL_SCOPE_CONFLICT"

    v2 = approval_service.decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=2, expected_commitment_version=v1_handoff.commitment_version,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="p3-v2-approval", reason="Authorize successor terms",
    )
    assert (v1.proposal_id, v1.proposal_version) == (plan.plan_id, 1)
    assert (v2.plan_id, v2.plan_version, v2.proposal_id, v2.proposal_version) == (
        plan.plan_id, 2, proposal_id_for_plan(plan.plan_id, 2), 2,
    )
    assert v2.approved_amount == plan.estimated_extra_cost
    assert approval_service.decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=2, expected_commitment_version=v1_handoff.commitment_version,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="p3-v2-approval", reason="Authorize successor terms",
    ).approval_id == v2.approval_id
    original_terms = dict(session.get(CommitmentRecord, (manager.tenant_id, plan.commitment_id)).terms)
    handoff = DurableCommunicationHandoff().request(session, manager, key, plan.plan_id, command)
    assert (handoff.plan_id, handoff.plan_version, handoff.proposal_id, handoff.proposal_version) == (
        plan.plan_id, 2, v2.proposal_id, 2,
    )
    proposal = session.get(CommitmentProposalRecord, (manager.tenant_id, v2.proposal_id))
    assert proposal is not None and proposal.status == "ACTIVE"
    original_proposal = session.get(CommitmentProposalRecord, (manager.tenant_id, v1.proposal_id))
    assert original_proposal is not None and original_proposal.status == "SUPERSEDED"
    assert proposal.revised_terms == v2.approved_terms == handoff.approved_terms.model_dump(mode="json")
    assert session.get(CommitmentRecord, (manager.tenant_id, plan.commitment_id)).terms == original_terms
    assert DurableCommunicationHandoff().request(session, manager, key, plan.plan_id, command).source_event_id == handoff.source_event_id
    with pytest.raises(DomainError) as old_confirmation:
        CommunicationRequestService(session).read_current_basis(
            RequestContext(manager.tenant_id, "user_manager_01", "MANAGER", "corr_stale_v1"),
            CreateCommunicationRequest(source_event_id=v1_handoff.source_event_id),
            datetime.now(UTC),
        )
    assert old_confirmation.value.code == "COMMITMENT_VERSION_CONFLICT"

    revoked = approval_service.decide(
        session, manager, key, plan.plan_id, decision="REVOKED",
        expected_plan_version=2, expected_commitment_version=handoff.commitment_version,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="p3-v2-revocation", reason="Withdraw successor offer",
    )
    assert (revoked.proposal_id, revoked.proposal_version) == (v2.proposal_id, 2)
    assert session.get(type(v1), (manager.tenant_id, v1.approval_id)).proposal_id == plan.plan_id
    with pytest.raises(DomainError) as withdrawn:
        DurableCommunicationHandoff().request(session, manager, key, plan.plan_id, command)
    assert withdrawn.value.code == "APPROVAL_NOT_ACTIVE"


def test_stale_response_is_reconciled_once_without_invalidating_newer_plan(session, monkeypatch):
    event = _p4_response_event(session, monkeypatch)
    case, plan = _persist_exact_p3_plan_for_p4_request(session)
    newer = plan.model_copy(update={
        "plan_version": 3,
        "proposal_id": proposal_id_for_plan(plan.plan_id, 3),
        "proposal_version": 3,
        "evaluation": plan.evaluation.model_copy(update={
            "plan_version": 3,
        }),
    })
    case_row = session.get(RecoveryCaseRecord, (case.tenant_id, case.case_id))
    prior_plan_row = session.get(RecoveryPlanRecord, (case.tenant_id, plan.plan_id, plan.plan_version))
    assert case_row is not None and prior_plan_row is not None
    case = case.model_copy(update={
        "case_version": case.case_version + 1,
        "plans": [plan, newer],
    })
    case_row.case_version = case.case_version
    case_row.case_payload = case.model_dump(mode="json")
    prior_plan_row.status = "SUPERSEDED"
    assert session.query(RecoveryPlanRecord).filter_by(
        tenant_id=case.tenant_id, plan_id=plan.plan_id,
    ).count() == 1
    session.add(RecoveryPlanRecord(
        tenant_id=case.tenant_id,
        plan_id=newer.plan_id,
        plan_version=newer.plan_version,
        case_id=case.case_id,
        commitment_id=case.commitment_id,
        assessment_id=newer.based_on_assessment_id,
        snapshot_id=newer.snapshot_id or "snapshot_context_test_v3",
        snapshot_version=newer.snapshot_version,
        core_commitment_version=10,
        evaluated_commitment_version=newer.evaluation.commitment_version,
        payload=newer.model_dump(mode="json"),
        status="PENDING_APPROVAL",
        created_at=case.created_at,
    ))
    session.flush()
    plan_count_before = session.query(RecoveryPlanRecord).filter_by(
        tenant_id=case.tenant_id, plan_id=plan.plan_id,
    ).count()
    assert plan_count_before == 2

    consumer = P3ConfirmationResponseConsumer(PendingRecoveryEventPublisher())
    assert OutboxDispatcher.execute_consumer(session, event, CONSUMER_NAME, consumer) is True
    saved_case = session.get(RecoveryCaseRecord, (case.tenant_id, case.case_id))
    current_plan = session.get(RecoveryPlanRecord, (case.tenant_id, plan.plan_id, 3))
    assert saved_case is not None and current_plan is not None
    assert saved_case.case_payload["customer_response_events"][-1]["outcome"] == "STALE_IGNORED"
    assert saved_case.status == RecoveryCaseStatus.OPTIONS_READY.value
    assert current_plan.status == "PENDING_APPROVAL"
    assert prior_plan_row.status == "SUPERSEDED"
    assert session.get(ProcessedEventRecord, (event.tenant_id, event.event_id, CONSUMER_NAME)) is not None
    audit_count = session.query(AuditEventRecord).filter_by(
        tenant_id=event.tenant_id,
        causation_id=event.event_id,
        event_type="recovery.customer_reject",
    ).count()
    response_count = len(saved_case.case_payload["customer_response_events"])

    assert OutboxDispatcher.execute_consumer(session, event, CONSUMER_NAME, consumer) is False
    session.refresh(saved_case)
    assert len(saved_case.case_payload["customer_response_events"]) == response_count
    assert session.query(RecoveryPlanRecord).filter_by(
        tenant_id=case.tenant_id, plan_id=plan.plan_id,
    ).count() == plan_count_before
    assert session.query(AuditEventRecord).filter_by(
        tenant_id=event.tenant_id,
        causation_id=event.event_id,
        event_type="recovery.customer_reject",
    ).count() == audit_count == 1


def test_shared_dispatcher_holds_stale_p4_event_without_required_consumers(session, monkeypatch):
    event = _p4_response_event(session, monkeypatch)
    case, plan = _persist_exact_p3_plan_for_p4_request(session)
    commitment = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    assert commitment is not None
    commitment.commitment_version = event.commitment_version + 1
    for row in session.scalars(select(OutboxEventRecord)):
        if row.event_id != event.event_id:
            row.status = "PUBLISHED"
    session.commit()

    dispatcher = OutboxDispatcher()
    register_p3_confirmation_response_consumer(dispatcher, PendingRecoveryEventPublisher())
    result = dispatcher.process_outbox_batch(session)
    assert result.failed_count == 1
    source = session.get(OutboxEventRecord, event.event_id)
    assert source is not None
    assert source.status == "FAILED"
    assert source.last_error == "STALE_MANDATORY_SUBSCRIBER_INCOMPLETE"
    assert session.get(ProcessedEventRecord, (event.tenant_id, event.event_id, CONSUMER_NAME)) is None
    assert session.get(RecoveryPlanRecord, (case.tenant_id, plan.plan_id, plan.plan_version)).status == "PENDING_APPROVAL"
    case_row = session.get(RecoveryCaseRecord, (case.tenant_id, case.case_id))
    assert case_row is not None
    assert not case_row.case_payload.get("customer_response_events")
    supersession = session.scalars(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.causation_id == event.event_id,
        AuditEventRecord.event_type == "commitment.event_superseded",
    )).all()
    assert supersession == []


def test_p4_confirmation_schema_version_is_enforced(session, monkeypatch):
    event = _p4_response_event(session, monkeypatch)
    unsupported = event.model_copy(update={"schema_version": 2})

    with pytest.raises(DomainError) as error:
        P3ConfirmationResponseConsumer._validate_p4_evidence(session, unsupported)

    assert error.value.code == "P4_RESPONSE_SCHEMA_UNSUPPORTED"


def _counteroffer_fixture(session):
    p2_fixtures = pytest.importorskip("app.feasibility.production_fixtures")
    snapshot, commitment = p2_fixtures.build_production_example()
    original_version = 2
    evaluated_version = 1
    commitment = commitment.model_copy(update={"commitment_version": original_version})
    sources = [
        row.model_copy(update={"commitment_version": evaluated_version})
        if row.commitment_id == commitment.commitment_id else row
        for row in snapshot.operational.confirmed_commitments
    ]
    snapshot = snapshot.model_copy(update={
        "operational": snapshot.operational.model_copy(update={"confirmed_commitments": tuple(sources)}),
    })
    offered_commitment = commitment.model_copy(update={
        "agreement_state": AgreementState.OFFERED, "commitment_version": 3,
    })
    inputs = load_demo_recovery_inputs()
    planner = RecoveryPlanner(inputs=replace(
        inputs,
        commitment=commitment,
        assessment=inputs.assessment.model_copy(update={
            "tenant_id": commitment.tenant_id,
            "commitment_id": commitment.commitment_id,
            "commitment_version": evaluated_version,
        }),
        snapshot=inputs.snapshot.model_copy(update={
            "snapshot_id": snapshot.operational.snapshot_id,
            "snapshot_version": snapshot.operational.snapshot_version,
            "captured_at": snapshot.operational.captured_at,
        }),
    ))
    case = planner.generate(
        commitment.tenant_id, commitment.commitment_id,
        expected_commitment_version=original_version,
    )
    plan = next(
        item for item in case.plans
        if item.strategy == RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT
    ).model_copy(update={
        "plan_id": "plan_001",
        "plan_version": 1,
        "proposal_id": proposal_id_for_plan("plan_001", 1),
        "proposal_version": 1,
        "core_commitment_version": original_version,
        "snapshot_id": snapshot.operational.snapshot_id,
        "snapshot_version": snapshot.operational.snapshot_version,
        "evaluation": next(
            item for item in case.plans
            if item.strategy == RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT
        ).evaluation.model_copy(update={
            "plan_id": "plan_001", "plan_version": 1,
            "commitment_version": evaluated_version,
        }),
    })
    action = next(item for item in plan.actions if item.type == "CREATE_DELIVERY_CHANGE_PROPOSAL")
    terms_data = commitment.terms.model_dump(mode="json")
    terms_data.update({
        "quantity": action.parameters["partial_quantity"],
        "deadline": action.parameters["new_deadline"],
    })
    proposal_terms = CommitmentTerms.model_validate(terms_data).model_dump(mode="json")
    offered_at = datetime.now(UTC)
    case, plan, case_record, plan_record, proposal, approval = _persist_authorized_offer_transition(
        session,
        case=case,
        plan=plan,
        commitment=commitment,
        previous_version=original_version,
        offered_version=3,
        proposal_terms=proposal_terms,
        offered_at=offered_at,
    )
    response_event = SimpleNamespace(
        event_id="evt_counteroffer_test",
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=3,
        occurred_at=offered_at + timedelta(minutes=1),
        payload={"evidence_refs": ["p4:counteroffer-evidence"]},
    )
    session.flush()
    return locals()


def _run_counteroffer_replan(session, monkeypatch):
    p2_service = pytest.importorskip("app.feasibility.service")
    setup = _counteroffer_fixture(session)
    monkeypatch.setattr(
        "app.feasibility.persisted_sources.read_snapshot",
        lambda _db, _tenant: setup["snapshot"],
    )
    evaluate_calls = []
    canonical_evaluate = p2_service.evaluate

    def evaluate_spy(*args):
        evaluate_calls.append(args)
        return canonical_evaluate(*args)

    monkeypatch.setattr(p2_service, "evaluate", evaluate_spy)
    result = DurablePlanService().apply_counteroffer(
        session,
        tenant_id=setup["commitment"].tenant_id,
        commitment=setup["offered_commitment"],
        case_record=setup["case_record"],
        case=setup["case"],
        prior_plan_record=setup["plan_record"],
        prior_plan=setup["plan"],
        proposal=setup["proposal"],
        approval=setup["approval"],
        counteroffer={"quantity": "70"},
        response_event=setup["response_event"],
    )
    session.flush()
    return setup, evaluate_calls, result


def _assert_counteroffer_success(session, setup, evaluate_calls, result):
    _, updated_case, next_plan, outcome = result
    assert len(evaluate_calls) == 1
    assert evaluate_calls[0][0] is setup["snapshot"]
    assert str(evaluate_calls[0][1].quantity) == "70"
    assert evaluate_calls[0][2].agreement_state == "CONFIRMED"
    assert outcome in {"REPLANNED", "REPLAN_REQUIRED"}
    assert next_plan.plan_id == setup["plan"].plan_id
    assert next_plan.plan_version == 2
    assert (setup["plan"].core_commitment_version, setup["response_event"].commitment_version) == (2, 3)
    assert next_plan.evaluation.commitment_version == 1
    successor = session.get(RecoveryPlanRecord, (setup["plan"].tenant_id, next_plan.plan_id, 2))
    assert successor is not None and successor.core_commitment_version == 3
    plan_versions = [row[0] for row in session.query(RecoveryPlanRecord.plan_version).filter_by(
        tenant_id=setup["plan"].tenant_id, plan_id=next_plan.plan_id,
    ).order_by(RecoveryPlanRecord.plan_version).all()]
    assert plan_versions == [1, 2]
    assert next_plan.proposal_id == proposal_id_for_plan(setup["plan"].plan_id, 2)
    assert next_plan.proposal_version == 2
    assert next_plan.approval_state.value == "PENDING"
    assert next_plan.recommended is False
    assert next_plan.evaluation.feasibility_status == next_plan.feasibility_status
    assert updated_case.plans[-1].plan_version == 2
    assert setup["plan_record"].status in {"SUPERSEDED", "NEEDS_REPLAN"}
    assert session.query(ManagerApprovalRecord).filter_by(
        tenant_id=setup["plan"].tenant_id, plan_id=setup["plan"].plan_id,
    ).count() == 1
    core = session.get(CommitmentRecord, (setup["commitment"].tenant_id, setup["commitment"].commitment_id))
    assert (core.agreement_state, core.commitment_version, core.terms) == (
        "OFFERED", 3, setup["commitment"].terms.model_dump(mode="json"),
    )


def test_counteroffer_creates_fresh_p2_evaluated_v2_after_legitimate_2_to_3_offer(session, monkeypatch):
    setup, evaluate_calls, result = _run_counteroffer_replan(session, monkeypatch)
    _assert_counteroffer_success(session, setup, evaluate_calls, result)


@pytest.mark.parametrize("tamper", ["unrelated_version", "proposal_identity", "offer_audit"])
def test_counteroffer_rejects_unproven_or_unrelated_core_advances(session, tamper):
    setup = _counteroffer_fixture(session)
    plan_count_before = session.query(RecoveryPlanRecord).filter_by(
        tenant_id=setup["plan"].tenant_id, plan_id=setup["plan"].plan_id,
    ).count()
    assert plan_count_before == 1
    event = setup["response_event"]
    if tamper == "unrelated_version":
        core = session.get(CommitmentRecord, (setup["commitment"].tenant_id, setup["commitment"].commitment_id))
        core.commitment_version = 4
        event.commitment_version = 4
    elif tamper == "proposal_identity":
        setup["proposal"].proposal_id = "wrong_proposal"
    else:
        offer = session.scalar(select(OutboxEventRecord).where(
            OutboxEventRecord.event_type == CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
        ))
        offer.payload = {**offer.payload, "proposal_version": 99}
    with pytest.raises(DomainError) as error:
        DurablePlanService().require_authorized_offer_transition(
            session,
            tenant_id=setup["commitment"].tenant_id,
            commitment=session.get(CommitmentRecord, (setup["commitment"].tenant_id, setup["commitment"].commitment_id)),
            case_record=setup["case_record"],
            prior_plan_record=setup["plan_record"],
            prior_plan=setup["plan"],
            proposal=setup["proposal"],
            approval=setup["approval"],
            response_event=event,
        )
    assert error.value.code == "CORE_OFFER_PROVENANCE_INVALID"
    assert session.query(RecoveryPlanRecord).filter_by(
        tenant_id=setup["plan"].tenant_id, plan_id=setup["plan"].plan_id,
    ).count() == plan_count_before
    assert session.get(RecoveryPlanRecord, (
        setup["plan"].tenant_id, setup["plan"].plan_id, 2,
    )) is None


@pytest.mark.parametrize(
    ("evidence", "field", "wrong_value"),
    [
        ("outbox", "proposal_version", True),
        ("outbox", "proposal_version", 1.0),
        ("approval_audit", "plan_version", True),
        ("approval_audit", "commitment_version", 2.0),
        ("offer_audit_before", "commitment_version", 2.0),
        ("offer_audit_after", "commitment_version", 3.0),
    ],
)
def test_core_offer_evidence_rejects_type_coercing_json(
    session, evidence, field, wrong_value,
):
    setup = _counteroffer_fixture(session)
    offer = session.scalar(select(OutboxEventRecord).where(
        OutboxEventRecord.event_type == CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
    ))
    assert offer is not None
    proof = DurablePlanService().require_authorized_offer_transition
    arguments = {
        "tenant_id": setup["commitment"].tenant_id,
        "commitment": session.get(CommitmentRecord, (
            setup["commitment"].tenant_id, setup["commitment"].commitment_id,
        )),
        "case_record": setup["case_record"],
        "prior_plan_record": setup["plan_record"],
        "prior_plan": setup["plan"],
        "proposal": setup["proposal"],
        "approval": setup["approval"],
        "response_event": setup["response_event"],
    }
    proof(session, **arguments)

    if evidence == "outbox":
        offer.payload = {**offer.payload, field: wrong_value}
    else:
        audit_id = (setup["approval"].audit_id if evidence == "approval_audit"
                    else offer.payload["audit_id"])
        audit = session.get(AuditEventRecord, audit_id)
        assert audit is not None
        state_field = "previous_state" if evidence == "offer_audit_before" else "new_state"
        state = getattr(audit, state_field)
        setattr(audit, state_field, {**state, field: wrong_value})

    with pytest.raises(DomainError) as error:
        proof(session, **arguments)
    assert error.value.code == "CORE_OFFER_PROVENANCE_INVALID"
    assert session.get(RecoveryPlanRecord, (
        setup["plan"].tenant_id, setup["plan"].plan_id, 2,
    )) is None


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
@pytest.mark.parametrize("evidence", ["outbox", "offer_audit"])
def test_postgresql_core_offer_json_version_types_fail_closed(migrated, evidence):
    engine, _ = migrated
    assert engine.dialect.name == "postgresql"
    with Session(engine) as session:
        setup = _counteroffer_fixture(session)
        offer = session.scalar(select(OutboxEventRecord).where(
            OutboxEventRecord.event_type == CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
        ))
        assert offer is not None
        if evidence == "outbox":
            session.execute(update(OutboxEventRecord).where(
                OutboxEventRecord.event_id == offer.event_id,
            ).values(payload={**offer.payload, "proposal_version": 1.0}))
        else:
            audit = session.get(AuditEventRecord, offer.payload["audit_id"])
            assert audit is not None
            session.execute(update(AuditEventRecord).where(
                AuditEventRecord.audit_id == audit.audit_id,
            ).values(new_state={**audit.new_state, "commitment_version": True}))
        session.expire_all()

        with pytest.raises(DomainError) as error:
            DurablePlanService().require_authorized_offer_transition(
                session,
                tenant_id=setup["commitment"].tenant_id,
                commitment=session.get(CommitmentRecord, (
                    setup["commitment"].tenant_id, setup["commitment"].commitment_id,
                )),
                case_record=setup["case_record"],
                prior_plan_record=setup["plan_record"],
                prior_plan=setup["plan"],
                proposal=setup["proposal"],
                approval=setup["approval"],
                response_event=setup["response_event"],
            )
        assert error.value.code == "CORE_OFFER_PROVENANCE_INVALID"
        assert session.get(RecoveryPlanRecord, (
            setup["plan"].tenant_id, setup["plan"].plan_id, 2,
        )) is None


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
@pytest.mark.parametrize(
    ("intent", "response_state"),
    [("REJECT", "REJECTED"), ("COUNTEROFFER", "COUNTEROFFER_RECEIVED")],
)
def test_postgresql_p4_audit_payload_validation_avoids_json_equality(
    migrated, monkeypatch, intent, response_state,
):
    engine, _ = migrated
    assert engine.dialect.name == "postgresql"
    with Session(engine) as session:
        event = _p4_response_event(session, monkeypatch, intent=intent)
        assert P3ConfirmationResponseConsumer._validate_p4_evidence(session, event) == (
            intent, response_state,
        )
        audit = session.scalar(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == event.tenant_id,
            AuditEventRecord.commitment_id == event.commitment_id,
            AuditEventRecord.event_type == event.event_type,
            AuditEventRecord.correlation_id == event.correlation_id,
            AuditEventRecord.causation_id == event.causation_id,
        ))
        assert audit is not None
        original_payload = dict(audit.new_state)
        audit.new_state = {**original_payload, "proposal_version": original_payload["proposal_version"] + 1}
        with pytest.raises(DomainError) as missing:
            P3ConfirmationResponseConsumer._validate_p4_evidence(session, event)
        assert missing.value.code == "P4_RESPONSE_AUDIT_MISSING"
        audit.new_state = {**original_payload, "proposal_version": float(original_payload["proposal_version"])}
        with pytest.raises(DomainError) as wrong_type:
            P3ConfirmationResponseConsumer._validate_p4_evidence(session, event)
        assert wrong_type.value.code == "P4_RESPONSE_AUDIT_MISSING"
        audit.new_state = original_payload
        duplicate = {column.name: getattr(audit, column.name) for column in AuditEventRecord.__table__.columns}
        duplicate["audit_id"] = f"audit_duplicate_{intent.lower()}_response"
        session.add(AuditEventRecord(**duplicate))
        session.flush()
        with pytest.raises(DomainError) as ambiguous:
            P3ConfirmationResponseConsumer._validate_p4_evidence(session, event)
        assert ambiguous.value.code == "P4_RESPONSE_AUDIT_AMBIGUOUS"


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
def test_postgresql_migration_rejects_equal_recovery_plan_versions(migrated):
    engine, _ = migrated
    assert engine.dialect.name == "postgresql"
    with Session(engine) as session:
        case, plan = _persist_exact_p3_plan_for_p4_request(session)
        session.add(RecoveryPlanRecord(
            tenant_id=case.tenant_id,
            plan_id="invalid_equal_version_plan",
            plan_version=1,
            case_id=case.case_id,
            commitment_id=case.commitment_id,
            assessment_id=plan.based_on_assessment_id,
            snapshot_id=plan.snapshot_id or "snapshot_context_test_equal",
            snapshot_version=plan.snapshot_version,
            core_commitment_version=9,
            evaluated_commitment_version=9,
            payload=plan.model_dump(mode="json"),
            status="PENDING_APPROVAL",
            created_at=case.created_at,
        ))
        with pytest.raises(IntegrityError) as error:
            session.flush()
        assert error.value.orig.diag.constraint_name == "ck_recovery_plan_core_after_evaluation"


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
def test_postgresql_rejection_invalidates_exact_plan_and_duplicate_is_idempotent(migrated, monkeypatch):
    engine, _ = migrated
    assert engine.dialect.name == "postgresql"
    with Session(engine) as session:
        event = _p4_response_event(session, monkeypatch, intent="REJECT", plan_version=2)
        case, plan = _persist_exact_p3_plan_for_p4_request(session, plan_version=2)
        proposal = session.get(CommitmentProposalRecord, (event.tenant_id, event.payload["proposal_id"]))
        assert proposal is not None
        case, plan, case_record, plan_record, proposal, _approval = _persist_authorized_offer_transition(
            session,
            case=case,
            plan=plan,
            commitment=case.commitment,
            previous_version=10,
            offered_version=11,
            proposal_terms=proposal.revised_terms,
            offered_at=event.occurred_at - timedelta(minutes=10),
        )
        core_before = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
        original_core = (core_before.agreement_state, core_before.commitment_version, dict(core_before.terms))

        publisher = _TestOnlyReplanPublisher()
        consumer = P3ConfirmationResponseConsumer(publisher)
        consumer(session, event)
        session.flush()
        session.refresh(case_record)
        session.refresh(plan_record)
        assert plan_record.status == "NEEDS_REPLAN"
        assert case_record.status == RecoveryCaseStatus.NEEDS_REPLAN.value
        assert case_record.case_payload["customer_response_events"][-1]["outcome"] == "REPLAN_REQUIRED"
        assert (core_before.agreement_state, core_before.commitment_version, core_before.terms) == original_core
        assert len(publisher.events) == 1
        assert publisher.events[0].event_type == RecoveryEventType.REPLAN_REQUIRED
        assert session.query(RecoveryPlanRecord).filter_by(
            tenant_id=event.tenant_id, plan_id=plan.plan_id,
        ).count() == 1
        assert len(publisher.events) == 1

        consumer(session, event)
        session.flush()
        session.refresh(case_record)
        assert len(case_record.case_payload["customer_response_events"]) == 1
        assert session.query(RecoveryPlanRecord).filter_by(
            tenant_id=event.tenant_id, plan_id=plan.plan_id,
        ).count() == 1


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
def test_postgresql_counteroffer_persists_p2_checked_v2_with_fresh_approval_pending(migrated, monkeypatch):
    engine, _ = migrated
    assert engine.dialect.name == "postgresql"
    with Session(engine) as session:
        setup, evaluate_calls, result = _run_counteroffer_replan(session, monkeypatch)
        _assert_counteroffer_success(session, setup, evaluate_calls, result)


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
def test_postgresql_counteroffer_duplicate_delivery_does_not_add_plan_rows(migrated, monkeypatch):
    engine, _ = migrated
    assert engine.dialect.name == "postgresql"
    with Session(engine) as session:
        setup = _counteroffer_fixture(session)
        monkeypatch.setattr(
            "app.feasibility.persisted_sources.read_snapshot",
            lambda _db, _tenant: setup["snapshot"],
        )
        response_context = SimpleNamespace(
            tenant_id=setup["commitment"].tenant_id,
            commitment_id=setup["commitment"].commitment_id,
            recovery_case_id=setup["case"].case_id,
            plan_id=setup["plan"].plan_id,
            plan_version=setup["plan"].plan_version,
            proposal_id=setup["proposal"].proposal_id,
            proposal_version=setup["proposal"].proposal_version,
            intent="COUNTEROFFER",
        )
        resolver = SimpleNamespace(resolve=lambda _db, _event: response_context)
        monkeypatch.setattr(
            P3ConfirmationResponseConsumer,
            "_counteroffer_terms",
            staticmethod(lambda _db, _event: {"quantity": "70"}),
        )
        event = DomainEvent(
            event_id="evt_counteroffer_duplicate_delivery",
            schema_version=1,
            event_type="confirmation.counteroffer_received",
            tenant_id=setup["commitment"].tenant_id,
            commitment_id=setup["commitment"].commitment_id,
            commitment_version=setup["response_event"].commitment_version,
            correlation_id="corr_counteroffer_duplicate_delivery",
            causation_id="decision_counteroffer_duplicate_delivery",
            occurred_at=setup["response_event"].occurred_at,
            payload={
                "confirmation_id": "confirmation_counteroffer_duplicate_delivery",
                "communication_id": "communication_counteroffer_duplicate_delivery",
                "outbound_id": "outbound_counteroffer_duplicate_delivery",
                "proposal_id": response_context.proposal_id,
                "proposal_version": response_context.proposal_version,
                "terms_digest": "sha256:counteroffer-terms",
                "response_state": "COUNTEROFFER_RECEIVED",
                "evidence_refs": ["p4:counteroffer-evidence"],
                "evidence_scope": "P4_EVIDENCE_ONLY",
                "integration_mode": "SYNTHETIC_ONLY",
                "decision_id": "decision_counteroffer_duplicate_delivery",
                "attempt_id": "attempt_counteroffer_duplicate_delivery",
                "intent": "COUNTEROFFER",
                "proposed_changes": {"quantity": "70"},
            },
        )
        consumer = P3ConfirmationResponseConsumer(_TestOnlyReplanPublisher(), resolver=resolver)

        assert OutboxDispatcher.execute_consumer(session, event, CONSUMER_NAME, consumer) is True
        plan_versions = session.scalars(select(RecoveryPlanRecord.plan_version).where(
            RecoveryPlanRecord.tenant_id == event.tenant_id,
            RecoveryPlanRecord.plan_id == setup["plan"].plan_id,
        ).order_by(RecoveryPlanRecord.plan_version)).all()
        assert plan_versions == [1, 2]
        assert session.get(ProcessedEventRecord, (event.tenant_id, event.event_id, CONSUMER_NAME)) is not None

        assert OutboxDispatcher.execute_consumer(session, event, CONSUMER_NAME, consumer) is False
        consumer(session, event)
        assert session.scalars(select(RecoveryPlanRecord.plan_version).where(
            RecoveryPlanRecord.tenant_id == event.tenant_id,
            RecoveryPlanRecord.plan_id == setup["plan"].plan_id,
        ).order_by(RecoveryPlanRecord.plan_version)).all() == [1, 2]


def test_invalidated_plan_version_cannot_start_a_durable_action(monkeypatch):
    monkeypatch.setattr(
        "app.recovery.durable_actions.trusted_isolated_manager",
        lambda _context, _key: "manager_test",
    )
    invalidated = SimpleNamespace(
        status="NEEDS_REPLAN",
        core_commitment_version=11,
        snapshot_version=7,
    )

    class FakeSession:
        def scalar(self, _statement):
            return None

        def get(self, _model, _key):
            return invalidated

    context = RequestContext(
        tenant_id="tenant_test",
        actor_id="manager_test",
        actor_role="MANAGER",
        correlation_id="corr_test",
    )
    with pytest.raises(DomainError) as error:
        DurableActionService().execute(
            FakeSession(),
            context,
            "isolated-key",
            "plan_test",
            expected_plan_version=1,
            expected_commitment_version=11,
            expected_snapshot_version=7,
            idempotency_key="idem_invalidated",
        )
    assert error.value.code == "PLAN_VERSION_NOT_ACTIVE"
