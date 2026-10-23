"""P5 recovery regressions for scoped evidence, identity and confirmation wiring."""

from __future__ import annotations

from datetime import UTC, datetime

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
from app.core.confirmation import P5RecoveryOutboxBoundary, P5VerifiedCoreConfirmationPort
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
from app.core.schemas import AgreementState, FulfilmentState
from app.recovery.durable_plans import RecoveryPlanRecord
from app.recovery.eventing import (
    P5OutboxPublisherAdapter,
    RecoveryEventCoordinator,
    RecoveryEventType,
    ReplanRequiredPayload,
)
from app.recovery.persistence import RecoveryCaseRecord
from app.worker import configure_isolated_subscribers


def _headers(tenant: str, actor: str = "user_manager_01") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Actor-ID": actor, "X-Correlation-ID": "corr_p5_recovery"}


def _new_commitment(client, tenant: str = "tenant_p5_test") -> tuple[str, int]:
    created = client.post(
        "/v1/commitments",
        headers=_headers(tenant),
        json={
            "order_id": "ord_p5_test",
            "customer_id": "cust_p5_test",
            "terms": {
                "sku": "SKU_P5",
                "quantity": "5",
                "unit": "pcs",
                "deadline": "2026-10-24T18:00:00+08:00",
            },
            "evidence_refs": ["ev_request_p5"],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["commitment_id"], 1


def _confirmed_commitment(client, tenant: str = "tenant_p5_test") -> tuple[str, int]:
    commitment_id, _ = _new_commitment(client, tenant)
    offered = client.post(
        f"/v1/commitments/{commitment_id}/proposals",
        headers=_headers(tenant),
        json={
            "proposal_id": f"proposal_{commitment_id}",
            "proposal_version": 1,
            "expected_commitment_version": 1,
            "reason": "Offer current terms",
            "evidence_refs": ["ev_offer_p5"],
        },
    )
    assert offered.status_code == 200, offered.text
    confirmed = client.post(
        f"/v1/commitments/{commitment_id}/confirm-proposal",
        headers=_headers(tenant),
        json={
            "proposal_id": f"proposal_{commitment_id}",
            "proposal_version": 1,
            "expected_commitment_version": 2,
            "decision": "ACCEPT",
            "evidence_refs": ["ev_confirm_p5"],
            "reason": "Customer accepted",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return commitment_id, 3


def _p4_terminal_event(session, intent: str):
    sent, drafts, reviews = fixture_sent(session)
    inbound = FixtureInbound()
    p4 = confirmation_service(session, drafts, reviews, inbound)
    challenge = p4.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
    response = text(challenge, intent)
    if intent == "COUNTEROFFER":
        response += ' changes:{"quantity":"80"}'
    command = inbound.add(response)
    p4.respond(
        MANAGER,
        challenge.confirmation.confirmation_id,
        command,
        challenge.confirmation_token,
        now=NOW,
    )
    event_type = {
        "ACCEPT": "confirmation.accepted",
        "REJECT": "confirmation.rejected",
        "COUNTEROFFER": "confirmation.counteroffer_received",
    }[intent]
    row = session.scalar(select(OutboxEventRecord).where(OutboxEventRecord.event_type == event_type))
    assert row is not None
    return to_domain_event(row)


def _make_stale_p4_response(session, event) -> None:
    commitment = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    source = session.get(OutboxEventRecord, event.event_id)
    assert commitment is not None and source is not None
    commitment.commitment_version = event.commitment_version + 1
    for row in session.scalars(select(OutboxEventRecord)).all():
        if row.event_id != event.event_id:
            row.status = "PUBLISHED"
    source.status = "PENDING"
    session.flush()


def _persist_exact_plan_for_p4_response(session, event) -> None:
    now = datetime.now(UTC)
    case_id = f"case_{event.event_id}"
    session.add(RecoveryCaseRecord(
        tenant_id=event.tenant_id,
        case_id=case_id,
        commitment_id=event.commitment_id,
        risk_episode_id=f"episode_{event.event_id}",
        opening_event_id=f"opening_{event.event_id}",
        status="OPTIONS_READY",
        case_version=1,
        commitment_version=event.commitment_version,
        payload_schema_version=1,
        case_payload={},
        resolution_refs=[],
        created_at=now,
        updated_at=now,
    ))
    session.flush()
    version = event.payload["proposal_version"]
    session.add(RecoveryPlanRecord(
        tenant_id=event.tenant_id,
        plan_id=f"plan_{event.event_id}",
        plan_version=version,
        case_id=case_id,
        commitment_id=event.commitment_id,
        assessment_id=f"assessment_{event.event_id}",
        snapshot_id=f"snapshot_{event.event_id}",
        snapshot_version=1,
        core_commitment_version=event.commitment_version,
        evaluated_commitment_version=event.commitment_version,
        payload={
            "proposal_id": event.payload["proposal_id"],
            "proposal_version": version,
            "plan_version": version,
        },
        status="PENDING_APPROVAL",
        created_at=now,
    ))
    session.flush()


@pytest.mark.parametrize("mode", [None, "0"])
def test_header_identity_requires_explicit_synthetic_mode(client, monkeypatch, mode) -> None:
    if mode is None:
        monkeypatch.delenv("MOUMANTAI_SYNTHETIC_MODE", raising=False)
    else:
        monkeypatch.setenv("MOUMANTAI_SYNTHETIC_MODE", mode)
    response = client.get("/v1/overview", headers=_headers("tenant_p5_gate"))
    assert response.status_code == 403
    assert response.json()["code"] == "SYNTHETIC_IDENTITY_DISABLED"


def test_header_identity_is_available_in_synthetic_mode(client, monkeypatch) -> None:
    monkeypatch.setenv("MOUMANTAI_SYNTHETIC_MODE", "1")
    response = client.get("/v1/overview", headers=_headers("tenant_p5_gate_enabled"))
    assert response.status_code == 200, response.text


def test_p1_development_identity_fallback_is_also_gated(client, monkeypatch) -> None:
    monkeypatch.delenv("MOUMANTAI_SYNTHETIC_MODE", raising=False)
    response = client.get("/v1/messages", headers=_headers("tenant_p5_gate_p1"))
    assert response.status_code == 403
    assert response.json()["code"] == "SYNTHETIC_IDENTITY_DISABLED"


def test_worker_confirmation_and_replanning_consumers_stay_behind_keyed_gate(monkeypatch) -> None:
    dispatcher = OutboxDispatcher()
    monkeypatch.delenv("MOUMANTAI_ISOLATED_E2E", raising=False)
    monkeypatch.delenv("MOUMANTAI_ISOLATED_E2E_KEY", raising=False)
    configure_isolated_subscribers(dispatcher)
    assert dispatcher.get_subscribers("confirmation.accepted") == []
    assert dispatcher.get_subscribers("confirmation.rejected") == []

    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    with pytest.raises(RuntimeError, match="server-owned mutation key"):
        configure_isolated_subscribers(dispatcher)
    assert dispatcher.get_subscribers("confirmation.accepted") == []

    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", "server-owned-test-key-" + "x" * 32)
    configure_isolated_subscribers(dispatcher)
    assert {name for name, _ in dispatcher.get_subscribers("confirmation.accepted")} == {
        "p5.confirmation.required"
    }
    assert {name for name, _ in dispatcher.get_subscribers("confirmation.rejected")} == {
        "p5.confirmation.required",
        "p3.confirmation_response.v1",
    }
    assert dispatcher.required_subscribers("confirmation.counteroffer_received") == (
        "p5.confirmation.required",
        "p3.confirmation_response.v1",
    )


def test_terminal_response_stays_pending_until_all_named_subscribers_are_registered(session) -> None:
    event = _p4_terminal_event(session, "REJECT")
    source = session.get(OutboxEventRecord, event.event_id)
    assert source is not None
    for row in session.scalars(select(OutboxEventRecord)).all():
        if row.event_id != event.event_id:
            row.status = "PUBLISHED"
    session.flush()

    dispatcher = OutboxDispatcher()
    called: list[str] = []
    noop = lambda _session, _event: called.append("wildcard")
    dispatcher.register_subscriber("*", "wildcard", noop)
    dispatcher.register_subscriber("confirmation.rejected", "p5.confirmation.required", noop)

    dispatcher.process_outbox_batch(session)
    session.refresh(source)
    assert source.status == "PENDING"
    assert called == []

    dispatcher.register_subscriber("confirmation.rejected", "p3.confirmation_response.v1", noop)
    result = dispatcher.process_outbox_batch(session)
    session.refresh(source)
    assert result.published_count == 1
    assert source.status == "PUBLISHED"
    assert called == ["wildcard", "wildcard", "wildcard"]


def test_known_superseded_stale_p4_response_publishes_without_calling_p3(session) -> None:
    event = _p4_terminal_event(session, "REJECT")
    _persist_exact_plan_for_p4_response(session, event)
    _make_stale_p4_response(session, event)
    called: list[str] = []

    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber(
        "confirmation.rejected",
        "p3.confirmation_response.v1",
        lambda _session, _event: called.append("p3"),
    )
    result = dispatcher.process_outbox_batch(session)
    source = session.get(OutboxEventRecord, event.event_id)

    assert result.published_count == 1
    assert result.failed_count == 0
    assert source is not None and source.status == "PUBLISHED"
    assert called == []
    assert session.get(
        ProcessedEventRecord,
        (event.tenant_id, event.event_id, "p3.confirmation_response.v1"),
    ) is None
    assert session.scalar(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.causation_id == event.event_id,
        AuditEventRecord.event_type == "commitment.event_superseded",
    )) is not None


def test_ambiguous_stale_p4_response_fails_without_calling_p3(session) -> None:
    event = _p4_terminal_event(session, "REJECT")
    _make_stale_p4_response(session, event)
    called: list[str] = []

    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber(
        "confirmation.rejected",
        "p3.confirmation_response.v1",
        lambda _session, _event: called.append("p3"),
    )
    result = dispatcher.process_outbox_batch(session)
    source = session.get(OutboxEventRecord, event.event_id)

    assert result.failed_count == 1
    assert result.published_count == 0
    assert source is not None and source.status == "FAILED"
    assert source.last_error == "STALE_MANDATORY_SUBSCRIBER_INCOMPLETE"
    assert called == []
    assert session.get(
        ProcessedEventRecord,
        (event.tenant_id, event.event_id, "p3.confirmation_response.v1"),
    ) is None


def test_p4_accept_applies_current_proposal_and_commits_audit_outbox_with_idempotency(session) -> None:
    event = _p4_terminal_event(session, "ACCEPT")
    commitment = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    assert commitment is not None
    original_terms = dict(commitment.terms)
    for row in session.scalars(select(OutboxEventRecord)).all():
        if row.event_id != event.event_id:
            row.status = "PUBLISHED"
    session.flush()

    dispatcher = OutboxDispatcher()
    from app.communication.core_confirmation_bridge import build_core_confirmation_consumer

    dispatcher.register_subscriber(
        "confirmation.accepted",
        "p5.confirmation.required",
        build_core_confirmation_consumer(P5VerifiedCoreConfirmationPort()),
    )
    first = dispatcher.process_outbox_batch(session)
    session.refresh(commitment)
    assert first.published_count == 1
    assert commitment.agreement_state == AgreementState.CONFIRMED.value
    assert commitment.fulfilment_state == FulfilmentState.NOT_STARTED.value
    proposal = session.get(CommitmentProposalRecord, (event.tenant_id, event.payload["proposal_id"]))
    assert proposal is not None and proposal.status == "ACCEPTED"
    assert commitment.terms == (proposal.revised_terms or original_terms)
    assert session.get(ProcessedEventRecord, (event.tenant_id, event.event_id, "p5.confirmation.required"))
    audit = session.scalar(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.causation_id == event.event_id,
        AuditEventRecord.event_type == "commitment.confirmed",
    ))
    core_event = session.scalar(select(OutboxEventRecord).where(
        OutboxEventRecord.tenant_id == event.tenant_id,
        OutboxEventRecord.causation_id == event.event_id,
        OutboxEventRecord.event_type == "commitment.confirmed",
    ))
    assert audit is not None and audit.actor_id == "service_p4_confirmation"
    assert core_event is not None and core_event.status == "PENDING"
    confirmed_version = commitment.commitment_version

    replay = dispatcher.process_outbox_batch(session)
    # The P4 response itself is already published/idempotent. The new Core
    # confirmed event remains PENDING because D-017's P2 subscriber is gated.
    session.refresh(commitment)
    assert replay.processed_count == 1
    assert session.get(OutboxEventRecord, event.event_id).status == "PUBLISHED"
    assert session.get(OutboxEventRecord, core_event.event_id).status == "PENDING"
    assert commitment.commitment_version == confirmed_version
    assert session.scalar(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.causation_id == event.event_id,
        AuditEventRecord.event_type == "commitment.confirmed",
    )) == audit


def test_p4_stale_proposal_event_cannot_overwrite_newer_core_proposal(session) -> None:
    event = _p4_terminal_event(session, "ACCEPT")
    commitment = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    old_proposal = session.get(CommitmentProposalRecord, (event.tenant_id, event.payload["proposal_id"]))
    assert commitment is not None and old_proposal is not None
    before_terms = dict(commitment.terms)
    before_version = commitment.commitment_version
    old_proposal.status = "SUPERSEDED"
    session.add(CommitmentProposalRecord(
        tenant_id=event.tenant_id,
        proposal_id="proposal_newer_p5",
        commitment_id=event.commitment_id,
        proposal_version=event.payload["proposal_version"] + 1,
        revised_terms={**before_terms, "quantity": "999"},
        status="ACTIVE",
        reason="Newer Core proposal",
        evidence_refs=["ev_newer_proposal_p5"],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    ))
    for row in session.scalars(select(OutboxEventRecord)).all():
        if row.event_id != event.event_id:
            row.status = "PUBLISHED"
    session.flush()

    dispatcher = OutboxDispatcher()
    from app.communication.core_confirmation_bridge import build_core_confirmation_consumer

    dispatcher.register_subscriber(
        "confirmation.accepted",
        "p5.confirmation.required",
        build_core_confirmation_consumer(P5VerifiedCoreConfirmationPort()),
    )
    result = dispatcher.process_outbox_batch(session)
    session.refresh(commitment)
    source = session.get(OutboxEventRecord, event.event_id)
    assert result.failed_count == 1
    assert source is not None and source.status == "FAILED"
    assert commitment.agreement_state == AgreementState.OFFERED.value
    assert commitment.terms == before_terms
    assert commitment.commitment_version == before_version


@pytest.mark.parametrize("intent", ["REJECT", "COUNTEROFFER"])
def test_p4_reject_preserves_terms_and_counteroffer_is_left_to_p3(session, intent) -> None:
    event = _p4_terminal_event(session, intent)
    commitment = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    assert commitment is not None
    old_terms = dict(commitment.terms)
    old_version = commitment.commitment_version

    from app.communication.core_confirmation_bridge import read_confirmation_evidence

    evidence = read_confirmation_evidence(session, event)
    result = P5VerifiedCoreConfirmationPort().apply(session, event, evidence)
    session.refresh(commitment)
    if intent == "REJECT":
        assert result is not None
        assert commitment.agreement_state == AgreementState.REJECTED.value
        assert commitment.terms == old_terms
        assert commitment.commitment_version == old_version + 1
    else:
        assert result is None
        assert commitment.agreement_state == AgreementState.OFFERED.value
        assert commitment.terms == old_terms
        assert commitment.commitment_version == old_version
    assert commitment.fulfilment_state == FulfilmentState.NOT_STARTED.value


def test_core_confirmation_command_rejects_wrong_tenant_identity_or_evidence(session) -> None:
    event = _p4_terminal_event(session, "ACCEPT")
    wrong_tenant = event.model_copy(update={"tenant_id": "tenant_foreign"})
    with pytest.raises(DomainError) as error:
        P5VerifiedCoreConfirmationPort().apply(session, wrong_tenant, {})
    assert error.value.code in {"CONFIRMATION_EVENT_UNTRUSTED", "CONFIRMATION_EVIDENCE_MISMATCH"}


def test_p5_recovery_outbox_boundary_is_tenant_scoped_and_idempotent(session) -> None:
    p3_event = RecoveryEventCoordinator.prepare(
        event_type=RecoveryEventType.REPLAN_REQUIRED,
        tenant_id="tenant_p3_scope",
        commitment_id="com_p3_scope",
        commitment_version=5,
        recovery_case_id="case_p3_scope",
        plan_id="plan_p3_scope",
        plan_version=2,
        snapshot_version=9,
        correlation_id="corr_p3_scope",
        causation_id="evt_p4_source",
        evidence_refs=["evt_p4_source"],
        payload=ReplanRequiredPayload(reason_code="CUSTOMER_REJECTED_PROPOSAL"),
        occurred_at=datetime.now(UTC),
    )
    context = RequestContext(
        tenant_id=p3_event.tenant_id,
        actor_id="service_p3_confirmation",
        actor_role="SERVICE",
        correlation_id=p3_event.correlation_id,
        causation_id=p3_event.causation_id,
    )
    publisher = P5OutboxPublisherAdapter(P5RecoveryOutboxBoundary())
    first = publisher.publish(p3_event, db=session, context=context)
    second = publisher.publish(p3_event, db=session, context=context)
    assert first.status.value == second.status.value == "PUBLISHED"
    assert session.get(OutboxEventRecord, p3_event.event_id) is not None

    wrong_context = RequestContext(
        tenant_id="tenant_other",
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        correlation_id=context.correlation_id,
        causation_id=context.causation_id,
    )
    rejected = publisher.publish(p3_event, db=session, context=wrong_context)
    assert rejected.status.value == "INTEGRATION_PENDING"


def test_fulfilment_requires_exact_synthetic_tenant_and_commitment_reference(client) -> None:
    commitment_id, version = _confirmed_commitment(client)
    good_ref = f"ev_synthetic_delivery|tenant_p5_test|{commitment_id}|pod_001"

    fulfilled = client.post(
        f"/v1/commitments/{commitment_id}/record-fulfilment",
        headers=_headers("tenant_p5_test"),
        json={
            "expected_commitment_version": version,
            "fulfilment_state": "FULFILLED",
            "evidence_refs": [good_ref],
            "reason": "Synthetic demo POD recorded",
        },
    )
    assert fulfilled.status_code == 200, fulfilled.text
    assert fulfilled.json()["commitment"]["fulfilment_state"] == "FULFILLED"


@pytest.mark.parametrize(
    "evidence_ref",
    [
        "prefix-ev_synthetic_delivery|tenant_p5_test|com_fake|pod_001-suffix",
        "ev_synthetic_delivery|tenant_other|com_fake|pod_001",
        "ev_synthetic_delivery|tenant_p5_test|com_other|pod_001",
        "ev_ops_delivery_pod_001",
    ],
)
def test_fulfilment_rejects_forged_or_wrong_scope_evidence(client, evidence_ref) -> None:
    commitment_id, version = _confirmed_commitment(client)
    response = client.post(
        f"/v1/commitments/{commitment_id}/record-fulfilment",
        headers=_headers("tenant_p5_test"),
        json={
            "expected_commitment_version": version,
            "fulfilment_state": "FULFILLED",
            "evidence_refs": [evidence_ref],
            "reason": "Attempt invalid synthetic fulfilment",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_FULFILMENT_EVIDENCE"


def test_fulfilment_rejects_missing_evidence_stale_version_and_unauthorized_role(client) -> None:
    commitment_id, version = _confirmed_commitment(client)
    url = f"/v1/commitments/{commitment_id}/record-fulfilment"
    payload = {
        "expected_commitment_version": version,
        "fulfilment_state": "FULFILLED",
        "evidence_refs": [f"ev_synthetic_delivery|tenant_p5_test|{commitment_id}|pod_001"],
        "reason": "Synthetic demo POD recorded",
    }

    missing = client.post(url, headers=_headers("tenant_p5_test"), json={**payload, "evidence_refs": []})
    assert missing.status_code == 422

    stale = client.post(
        url,
        headers=_headers("tenant_p5_test"),
        json={**payload, "expected_commitment_version": version - 1},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "COMMITMENT_VERSION_CONFLICT"

    unauthorized = client.post(
        url,
        headers=_headers("tenant_p5_test", actor="user_staff_01"),
        json=payload,
    )
    assert unauthorized.status_code == 403
    assert unauthorized.json()["code"] == "APPROVAL_REQUIRED"


def test_fulfilment_before_confirmed_and_completed_recovery_do_not_imply_delivery(client) -> None:
    commitment_id, version = _new_commitment(client)
    premature = client.post(
        f"/v1/commitments/{commitment_id}/record-fulfilment",
        headers=_headers("tenant_p5_test"),
        json={
            "expected_commitment_version": version,
            "fulfilment_state": "FULFILLED",
            "evidence_refs": [f"ev_synthetic_delivery|tenant_p5_test|{commitment_id}|pod_001"],
            "reason": "Premature synthetic POD",
        },
    )
    assert premature.status_code == 409
    assert premature.json()["code"] == "INVALID_STATE_TRANSITION"

    for target, expected_version in (
        ("PLANNING", 1),
        ("PENDING_APPROVAL", 2),
        ("EXECUTING", 3),
        ("COMPLETED", 4),
    ):
        response = client.post(
            f"/v1/commitments/{commitment_id}/transitions",
            headers=_headers("tenant_p5_test"),
            json={
                "dimension": "recovery",
                "target_state": target,
                "expected_commitment_version": expected_version,
                "evidence_refs": ["ev_action_succeeded_p5"],
                "reason": "Synthetic recovery action outcome",
            },
        )
        assert response.status_code == 200, response.text
    final = client.get(f"/v1/commitments/{commitment_id}", headers=_headers("tenant_p5_test"))
    assert final.status_code == 200
    assert final.json()["recovery_state"] == "COMPLETED"
    assert final.json()["fulfilment_state"] == "NOT_STARTED"
