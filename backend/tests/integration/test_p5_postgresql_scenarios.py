"""P5 PostgreSQL-only recovery scenarios; CI must opt in with REQUIRE_POSTGRES=1."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import (
    AuditEventRecord,
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
)
from app.core.outbox import OutboxDispatcher, to_domain_event
from app.core.schemas import RecordFulfilmentRequest
from app.core.service import CommitmentService
from app.communication.tests.test_confirmation_integration import (
    confirmation_service,
    fixture_sent,
)
from app.communication.tests.test_confirmations import FixtureInbound, text
from app.communication.confirmation_schemas import CreateConfirmation
from app.communication.tests.test_requests import NOW
from app.communication.tests.test_review import MANAGER


pytestmark = pytest.mark.postgres


@pytest.fixture
def p4_isolated_session(postgresql_test_engine):
    """Isolate the P4 synthetic fixture's fixed tenant and commitment IDs."""
    connection = postgresql_test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _seed_core(session: Session, *, agreement: str = "CONFIRMED", version: int = 4):
    tenant_id = f"tenant_p5pg_{uuid4().hex[:14]}"
    commitment_id = f"com_p5pg_{uuid4().hex[:14]}"
    now = datetime.now(UTC)
    record = CommitmentRecord(
        tenant_id=tenant_id,
        commitment_id=commitment_id,
        order_id=f"ord_{uuid4().hex[:10]}",
        customer_id=f"cust_{uuid4().hex[:10]}",
        terms={"sku": "SKU_P5PG", "quantity": "5", "unit": "pcs", "deadline": now.isoformat()},
        agreement_state=agreement,
        feasibility_state="FEASIBLE",
        risk_state="NORMAL",
        recovery_state="NONE",
        fulfilment_state="NOT_STARTED",
        commitment_version=version,
        evidence_refs=[],
        updated_at=now,
    )
    session.add(record)
    session.commit()
    return tenant_id, commitment_id, record


def _context(tenant_id: str, *, actor_id: str = "user_manager_01", role: str = "MANAGER"):
    return RequestContext(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=role,
        correlation_id=f"corr_p5pg_{uuid4().hex[:8]}",
    )


@pytest.mark.parametrize(
    ("ref_kind", "valid"),
    [
        ("valid", True),
        ("substring", False),
        ("wrong_tenant", False),
        ("wrong_commitment", False),
        ("legacy_delivery_name", False),
    ],
)
def test_postgres_fulfilment_evidence_must_be_exact_and_tenant_scoped(
    postgresql_test_engine, ref_kind: str, valid: bool
) -> None:
    with Session(postgresql_test_engine) as session:
        tenant_id, commitment_id, _ = _seed_core(session)
        evidence_id = f"pod_{uuid4().hex[:8]}"
        refs = {
            "valid": f"ev_synthetic_delivery|{tenant_id}|{commitment_id}|{evidence_id}",
            "substring": f"prefix-ev_synthetic_delivery|{tenant_id}|{commitment_id}|{evidence_id}-suffix",
            "wrong_tenant": f"ev_synthetic_delivery|tenant_other|{commitment_id}|{evidence_id}",
            "wrong_commitment": f"ev_synthetic_delivery|{tenant_id}|com_other|{evidence_id}",
            "legacy_delivery_name": f"ev_ops_delivery_{evidence_id}",
        }
        request = RecordFulfilmentRequest(
            expected_commitment_version=4,
            fulfilment_state="FULFILLED",
            evidence_refs=[refs[ref_kind]],
            reason="P5 PostgreSQL synthetic evidence scenario",
        )
        if valid:
            result = CommitmentService().record_fulfilment(
                session, _context(tenant_id), commitment_id, request, commit=False
            )
            assert result.commitment.fulfilment_state.value == "FULFILLED"
            session.rollback()
        else:
            with pytest.raises(DomainError) as error:
                CommitmentService().record_fulfilment(
                    session, _context(tenant_id), commitment_id, request, commit=False
                )
            assert error.value.code == "INVALID_FULFILMENT_EVIDENCE"
            session.rollback()


def test_postgres_fulfilment_missing_evidence_and_stale_version_fail_closed(postgresql_test_engine) -> None:
    with pytest.raises(ValidationError):
        RecordFulfilmentRequest(
            expected_commitment_version=4,
            fulfilment_state="FULFILLED",
            evidence_refs=[],
            reason="Missing evidence",
        )

    with Session(postgresql_test_engine) as session:
        tenant_id, commitment_id, _ = _seed_core(session)
        request = RecordFulfilmentRequest(
            expected_commitment_version=3,
            fulfilment_state="FULFILLED",
            evidence_refs=[f"ev_synthetic_delivery|{tenant_id}|{commitment_id}|pod_001"],
            reason="Stale expected version",
        )
        with pytest.raises(DomainError) as error:
            CommitmentService().record_fulfilment(
                session, _context(tenant_id), commitment_id, request, commit=False
            )
        assert error.value.code == "COMMITMENT_VERSION_CONFLICT"
        session.rollback()


def test_postgres_wrong_tenant_unauthorized_role_and_unconfirmed_fulfilment_are_rejected(
    postgresql_test_engine,
) -> None:
    with Session(postgresql_test_engine) as session:
        tenant_id, commitment_id, _ = _seed_core(session)
        evidence = [f"ev_synthetic_delivery|{tenant_id}|{commitment_id}|pod_001"]
        request = RecordFulfilmentRequest(
            expected_commitment_version=4,
            fulfilment_state="FULFILLED",
            evidence_refs=evidence,
            reason="Guard scenario",
        )
        service = CommitmentService()

        with pytest.raises(DomainError) as wrong_tenant:
            service.record_fulfilment(session, _context("tenant_other"), commitment_id, request, commit=False)
        assert wrong_tenant.value.code == "COMMITMENT_NOT_FOUND"
        session.rollback()

        with pytest.raises(DomainError) as unauthorized:
            service.record_fulfilment(
                session,
                _context(tenant_id, actor_id="user_staff_01", role="STAFF"),
                commitment_id,
                request,
                commit=False,
            )
        assert unauthorized.value.code == "APPROVAL_REQUIRED"
        session.rollback()

        record = session.get(CommitmentRecord, (tenant_id, commitment_id))
        assert record is not None
        record.agreement_state = "REQUESTED"
        session.commit()
        with pytest.raises(DomainError) as unconfirmed:
            service.record_fulfilment(session, _context(tenant_id), commitment_id, request, commit=False)
        assert unconfirmed.value.code == "INVALID_STATE_TRANSITION"
        session.rollback()


def test_postgres_successful_recovery_outcome_does_not_mark_fulfilment(postgresql_test_engine) -> None:
    with Session(postgresql_test_engine) as session:
        tenant_id, commitment_id, record = _seed_core(session)
        result = CommitmentService().record_action_outcome(
            session,
            _context(tenant_id),
            commitment_id,
            expected_commitment_version=record.commitment_version,
            dimension="recovery",
            target_state="PLANNING",
            reason="Recovery task reports success; delivery still needs proof",
            evidence_refs=["ev_action_succeeded_only"],
            commit=False,
        )
        assert result.commitment.recovery_state.value == "PLANNING"
        assert result.commitment.fulfilment_state.value == "NOT_STARTED"
        session.rollback()


def test_postgres_p4_accept_commits_core_transition_audit_and_processed_event_atomically(
    p4_isolated_session,
) -> None:
    from app.communication.core_confirmation_bridge import build_core_confirmation_consumer
    from app.core.confirmation import P5VerifiedCoreConfirmationPort

    with p4_isolated_session as session:
        sent, drafts, reviews = fixture_sent(session)
        inbound = FixtureInbound()
        p4 = confirmation_service(session, drafts, reviews, inbound)
        challenge = p4.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
        command = inbound.add(text(challenge, "ACCEPT"))
        p4.respond(
            MANAGER,
            challenge.confirmation.confirmation_id,
            command,
            challenge.confirmation_token,
            now=NOW,
        )
        row = session.scalar(select(OutboxEventRecord).where(
            OutboxEventRecord.event_type == "confirmation.accepted",
            OutboxEventRecord.tenant_id == "tenant_a",
        ))
        assert row is not None
        # Run this exact durable P4 event first in the shared disposable test DB.
        row.occurred_at = datetime(2000, 1, 1, tzinfo=UTC)
        event = to_domain_event(row)
        dispatcher = OutboxDispatcher()
        dispatcher.register_subscriber(
            "confirmation.accepted",
            "p5.confirmation.required",
            build_core_confirmation_consumer(P5VerifiedCoreConfirmationPort()),
        )

        result = dispatcher.process_outbox_batch(session, batch_size=1)
        session.refresh(row)
        commitment = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
        assert result.published_count == 1
        assert row.status == "PUBLISHED"
        assert commitment is not None and commitment.agreement_state == "CONFIRMED"
        assert commitment.fulfilment_state == "NOT_STARTED"
        assert session.get(ProcessedEventRecord, (event.tenant_id, event.event_id, "p5.confirmation.required"))
        audit = session.scalar(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == event.tenant_id,
            AuditEventRecord.causation_id == event.event_id,
            AuditEventRecord.event_type == "commitment.confirmed",
        ))
        core_outbox = session.scalar(select(OutboxEventRecord).where(
            OutboxEventRecord.tenant_id == event.tenant_id,
            OutboxEventRecord.causation_id == event.event_id,
            OutboxEventRecord.event_type == "commitment.confirmed",
        ))
        assert audit is not None and core_outbox is not None
        assert event.payload["integration_mode"] == "SYNTHETIC_ONLY"

        confirmed_version = commitment.commitment_version
        audit_rows = session.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == event.tenant_id,
            AuditEventRecord.causation_id == event.event_id,
            AuditEventRecord.event_type == "commitment.confirmed",
        )).all()
        assert len(audit_rows) == 1
        row.status = "PENDING"  # Simulate a durable redelivery after worker restart.
        row.published_at = None
        row.next_retry_at = None
        session.flush()
        replay = dispatcher.process_outbox_batch(session, batch_size=1)
        session.refresh(row)
        session.refresh(commitment)
        assert replay.published_count == 1
        assert row.status == "PUBLISHED"
        assert commitment.commitment_version == confirmed_version
        assert session.get(ProcessedEventRecord, (event.tenant_id, event.event_id, "p5.confirmation.required"))
        assert len(session.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == event.tenant_id,
            AuditEventRecord.causation_id == event.event_id,
            AuditEventRecord.event_type == "commitment.confirmed",
        )).all()) == 1


def test_postgres_stale_p4_proposal_cannot_overwrite_newer_proposal(p4_isolated_session) -> None:
    from app.communication.core_confirmation_bridge import build_core_confirmation_consumer
    from app.core.confirmation import P5VerifiedCoreConfirmationPort

    with p4_isolated_session as session:
        sent, drafts, reviews = fixture_sent(session)
        inbound = FixtureInbound()
        p4 = confirmation_service(session, drafts, reviews, inbound)
        challenge = p4.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
        command = inbound.add(text(challenge, "ACCEPT"))
        p4.respond(
            MANAGER,
            challenge.confirmation.confirmation_id,
            command,
            challenge.confirmation_token,
            now=NOW,
        )
        event_row = session.scalar(select(OutboxEventRecord).where(
            OutboxEventRecord.event_type == "confirmation.accepted",
            OutboxEventRecord.tenant_id == "tenant_a",
        ))
        commitment = session.get(CommitmentRecord, ("tenant_a", "com_001"))
        assert event_row is not None and commitment is not None
        event_row.occurred_at = datetime(2000, 1, 1, tzinfo=UTC)
        before_terms = dict(commitment.terms)
        proposal = session.get(CommitmentProposalRecord, ("tenant_a", event_row.payload["proposal_id"]))
        assert proposal is not None
        proposal.status = "SUPERSEDED"
        session.add(CommitmentProposalRecord(
            tenant_id="tenant_a",
            commitment_id="com_001",
            proposal_id="proposal_004",
            proposal_version=4,
            revised_terms={**before_terms, "quantity": "999"},
            status="ACTIVE",
            reason="Newer Core proposal",
            evidence_refs=["ev_proposal_004"],
            created_at=NOW,
            updated_at=NOW,
        ))
        session.flush()

        dispatcher = OutboxDispatcher()
        dispatcher.register_subscriber(
            "confirmation.accepted",
            "p5.confirmation.required",
            build_core_confirmation_consumer(P5VerifiedCoreConfirmationPort()),
        )
        result = dispatcher.process_outbox_batch(session, batch_size=1)
        session.refresh(event_row)
        session.refresh(commitment)
        current_proposal = session.get(CommitmentProposalRecord, ("tenant_a", "proposal_004"))
        assert result.failed_count == 1
        assert event_row.status == "FAILED"
        assert event_row.last_error and "STALE_PROPOSAL_VERSION" in event_row.last_error
        assert commitment.agreement_state == "OFFERED"
        assert commitment.terms == before_terms
        assert current_proposal is not None and current_proposal.status == "ACTIVE"


def test_postgres_p4_confirmation_rejects_tampered_persisted_event(p4_isolated_session) -> None:
    from app.core.confirmation import P5VerifiedCoreConfirmationPort

    with p4_isolated_session as session:
        sent, drafts, reviews = fixture_sent(session)
        inbound = FixtureInbound()
        p4 = confirmation_service(session, drafts, reviews, inbound)
        challenge = p4.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
        command = inbound.add(text(challenge, "ACCEPT"))
        p4.respond(
            MANAGER,
            challenge.confirmation.confirmation_id,
            command,
            challenge.confirmation_token,
            now=NOW,
        )
        row = session.scalar(select(OutboxEventRecord).where(
            OutboxEventRecord.event_type == "confirmation.accepted",
            OutboxEventRecord.tenant_id == "tenant_a",
        ))
        assert row is not None
        event = to_domain_event(row)
        forged = event.model_copy(update={
            "payload": {**event.payload, "terms_digest": "forged-terms-digest"},
        })
        commitment = session.get(CommitmentRecord, ("tenant_a", event.commitment_id))
        assert commitment is not None
        before_terms = dict(commitment.terms)
        before_version = commitment.commitment_version

        with pytest.raises(DomainError) as rejected:
            P5VerifiedCoreConfirmationPort().apply(session, forged, {})
        assert rejected.value.code == "CONFIRMATION_EVENT_UNTRUSTED"
        session.refresh(commitment)
        assert commitment.agreement_state == "OFFERED"
        assert commitment.terms == before_terms
        assert commitment.commitment_version == before_version
