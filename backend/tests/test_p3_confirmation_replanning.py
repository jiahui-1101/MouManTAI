"""P3 response adapter regressions against P4's persisted synthetic producer."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.communication.confirmation_schemas import CreateConfirmation
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
from app.core.manager_approval import ManagerApprovalService
from app.core.models import (
    AuditEventRecord,
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
)
from app.core.outbox import OutboxDispatcher
from app.core.schemas import DomainEvent
from app.recovery.confirmation_responses import (
    CONSUMER_NAME,
    P3ConfirmationContextResolver,
    P3ConfirmationResponseConsumer,
)
from app.recovery.durable_actions import DurableActionService
from app.recovery.durable_communication import (
    DurableCommunicationHandoff,
    RequestCommunicationInput,
)
from app.recovery.durable_plans import DurablePlanService, RecoveryPlanRecord
from app.recovery.eventing import PendingRecoveryEventPublisher
from app.recovery.fixtures import load_demo_recovery_inputs
from app.recovery.models import RecoveryCaseStatus, RecoveryStrategy
from app.recovery.persistence import RecoveryCaseRecord
from app.recovery.proposal_identity import proposal_id_for_plan, require_proposal_binding
from app.recovery.service import RecoveryPlanner
from tests.test_p2_persisted_sources import _prepared_review


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


def _persist_exact_p3_plan_for_p4_request(session, plan_version=2):
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
            "commitment_version": commitment.commitment_version,
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
        "evaluation": source_plan.evaluation.model_copy(update={
            "plan_id": "plan_001",
            "plan_version": plan_version,
            "commitment_version": 10,
        }),
    })
    case = case.model_copy(update={
        "commitment": commitment,
        "commitment_version": commitment.commitment_version,
        "status": RecoveryCaseStatus.OPTIONS_READY,
        "plans": [plan],
        "storage_mode": "DURABLE_DATABASE",
    })
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
        evaluated_commitment_version=10,
        payload=plan.model_dump(mode="json"),
        status="PENDING_APPROVAL",
        created_at=case.created_at,
    ))
    session.flush()
    return case, plan


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
        evaluated_commitment_version=10,
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
        evaluated_commitment_version=10,
        payload=newer.model_dump(mode="json"),
        status="PENDING_APPROVAL",
        created_at=case.created_at,
    ))
    session.flush()

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
    assert session.query(AuditEventRecord).filter_by(
        tenant_id=event.tenant_id,
        causation_id=event.event_id,
        event_type="recovery.customer_reject",
    ).count() == audit_count == 1


def test_p4_confirmation_schema_version_is_enforced(session, monkeypatch):
    event = _p4_response_event(session, monkeypatch)
    unsupported = event.model_copy(update={"schema_version": 2})

    with pytest.raises(DomainError) as error:
        P3ConfirmationResponseConsumer._validate_p4_evidence(session, unsupported)

    assert error.value.code == "P4_RESPONSE_SCHEMA_UNSUPPORTED"


def test_counteroffer_creates_a_fresh_p2_evaluated_plan_version(monkeypatch):
    p2_fixtures = pytest.importorskip("app.feasibility.production_fixtures")
    p2_service = pytest.importorskip("app.feasibility.service")
    snapshot, commitment = p2_fixtures.build_production_example()
    offered_commitment = commitment.model_copy(update={
        "agreement_state": "OFFERED",
        "commitment_version": commitment.commitment_version + 1,
    })
    inputs = load_demo_recovery_inputs()
    planner = RecoveryPlanner(inputs=replace(
        inputs,
        commitment=commitment,
        assessment=inputs.assessment.model_copy(update={
            "tenant_id": commitment.tenant_id,
            "commitment_id": commitment.commitment_id,
            "commitment_version": commitment.commitment_version,
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
    previous = next(
        plan for plan in case.plans
        if plan.strategy == RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT
    ).model_copy(update={
        "snapshot_id": snapshot.operational.snapshot_id,
        "snapshot_version": snapshot.operational.snapshot_version,
        "core_commitment_version": offered_commitment.commitment_version,
    })
    case.plans = [previous if plan.plan_id == previous.plan_id else plan for plan in case.plans]
    revised_terms = commitment.terms.model_dump(mode="json")
    proposal = SimpleNamespace(proposal_id="proposal_source", revised_terms=revised_terms)
    plan_record = SimpleNamespace(status="PENDING_APPROVAL", assessment_id=previous.based_on_assessment_id)

    class FakeSession:
        def __init__(self):
            self.added = []

        def scalar(self, _statement):
            return previous.plan_version

        def add(self, row):
            self.added.append(row)

    db = FakeSession()
    monkeypatch.setattr(
        "app.feasibility.persisted_sources.read_snapshot",
        lambda _db, _tenant: snapshot,
    )
    evaluate_calls = []
    canonical_evaluate = p2_service.evaluate

    def evaluate_spy(*args):
        evaluate_calls.append(args)
        return canonical_evaluate(*args)

    monkeypatch.setattr(p2_service, "evaluate", evaluate_spy)
    _, updated_case, next_plan, outcome = DurablePlanService().apply_counteroffer(
        db,
        tenant_id=commitment.tenant_id,
        commitment=offered_commitment,
        case_record=SimpleNamespace(case_id=case.case_id),
        case=case,
        prior_plan_record=plan_record,
        prior_plan=previous,
        proposal=proposal,
        counteroffer={"quantity": "70"},
        response_event=SimpleNamespace(
            event_id="evt_counteroffer_test",
            occurred_at=datetime.now(UTC),
            payload={"evidence_refs": ["p1:synthetic-inbound"]},
        ),
    )

    assert len(evaluate_calls) == 1
    assert evaluate_calls[0][0] is snapshot
    assert str(evaluate_calls[0][1].quantity) == "70"
    assert evaluate_calls[0][2].agreement_state == "CONFIRMED"
    assert outcome in {"REPLANNED", "REPLAN_REQUIRED"}
    assert next_plan.plan_id == previous.plan_id
    assert next_plan.plan_version == previous.plan_version + 1
    assert next_plan.proposal_id == proposal_id_for_plan(previous.plan_id, next_plan.plan_version)
    assert next_plan.proposal_version == next_plan.plan_version
    assert next_plan.approval_state.value == "PENDING"
    assert next_plan.recommended is False
    assert next_plan.evaluation.feasibility_status == next_plan.feasibility_status
    assert updated_case.plans[-1].plan_version == next_plan.plan_version
    assert plan_record.status in {"SUPERSEDED", "NEEDS_REPLAN"}
    assert len(db.added) == 1
    assert offered_commitment.terms.quantity == commitment.terms.quantity
    assert offered_commitment.agreement_state == "OFFERED"


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
