"""P3 response adapter regressions against P4's persisted synthetic producer."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.communication.confirmation_schemas import CreateConfirmation
from app.communication.tests.test_confirmation_integration import (
    confirmation_service,
    fixture_sent,
)
from app.communication.tests.test_confirmations import FixtureInbound, text
from app.communication.tests.test_requests import NOW
from app.communication.tests.test_review import MANAGER
from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import OutboxEventRecord
from app.core.schemas import DomainEvent
from app.recovery.confirmation_responses import P3ConfirmationResponseConsumer
from app.recovery.durable_actions import DurableActionService
from app.recovery.durable_plans import DurablePlanService
from app.recovery.fixtures import load_demo_recovery_inputs
from app.recovery.models import RecoveryStrategy
from app.recovery.service import RecoveryPlanner


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
    assert error.value.code == "P4_RESPONSE_SOURCE_MISSING"


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
    assert error.value.code == "P4_RESPONSE_SOURCE_MISSING"


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
    assert next_plan.plan_version == previous.plan_version + 1
    assert next_plan.proposal_id == f"proposal_source__counteroffer_v{next_plan.plan_version}"
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
