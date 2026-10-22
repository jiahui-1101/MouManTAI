"""P4 confirmation evidence tests. Upstream authority fixtures NEVER ship in runtime."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import json
import re

from alembic import command as alembic_command
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, inspect, insert, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.communication.confirmation_authority import (
    ExistingP4ConfirmationAuthority, RuntimeConfirmationAccess, P1SyntheticInboundAdapter, UnavailableVerifiedInboundAuthority,
)
from app.communication.confirmation_schemas import CreateConfirmation, ProcessConfirmationResponse, VerifiedInboundResponse
from app.communication.confirmations import ConfirmationService, token_digest
from app.communication.demo_policy import SyntheticScope
from app.communication.models import (
    ConfirmationSessionRecord, ConfirmationAttemptRecord, ConfirmationDecisionRecord, OutboundMessageRecord,
)
from app.communication.response_rules import classify_response
from app.communication.tests.test_requests import db, authority, service, OWNER, NOW, TERMS, expect_error
from app.communication.tests.test_drafting import draft_authority, drafts, request_id
from app.communication.tests.test_review import MANAGER, FixtureReviewAuthority
from app.communication.tests.test_outbound import approved, sending, send, FixtureSendAuthority
from app.communication.tests.test_migration_persistence import migrated, prepare_graph
from app.core.dependencies import ACTOR_ROLES, RequestContext, get_db
from app.core.errors import DomainError
from app.core.models import CommitmentRecord, CommitmentProposalRecord, AuditEventRecord, OutboxEventRecord
from app.main import app


class FixtureAccess:
    """TEST ONLY trusted processor permission, unavailable in actual demo headers."""
    def authorize(self, context, action):
        if ACTOR_ROLES.get(context.actor_id) != context.actor_role or context.actor_role not in {"OWNER", "MANAGER"}:
            raise DomainError("TEST_PROCESSOR_FORBIDDEN", "Fixture denies processor", status_code=403)


class FixtureInbound:
    def __init__(self):
        self.values = {}

    def add(self, text, message="inbound_test_001", **changes):
        reply = VerifiedInboundResponse(**{
            "tenant_id": "tenant_a", "message_id": message, "provider_message_id": f"provider_{message}",
            "customer_id": "customer_001", "recipient_identity_id": "identity_001", "channel": "MOCK_EMAIL",
            "text": text, "source_digest": "b" * 64, "evidence_refs": [f"p1:fixture:{message}"], **changes})
        self.values[message] = reply
        return ProcessConfirmationResponse(inbound_message_id=message)

    def resolve(self, db, context, message_id, *, now):
        return self.values.get(message_id)


@pytest.fixture
def sent(sending, approved):
    return send(sending, approved)


@pytest.fixture
def inbound():
    return FixtureInbound()


@pytest.fixture
def confirmations(db, draft_authority, approved, inbound):
    return ConfirmationService(db, FixtureAccess(), ExistingP4ConfirmationAuthority(draft_authority, approved[1]), inbound)


@pytest.fixture
def challenge(confirmations, sent):
    return confirmations.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)


def text(challenge, intent="ACCEPT"):
    value = challenge.confirmation
    base = f"{intent} {value.reference.proposal_id} v{value.reference.proposal_version}"
    return base + (f" terms:{value.terms_digest}" if intent == "ACCEPT" else '')


def respond(service, challenge, inbound, value=None, *, now=NOW, message="inbound_test_001", **changes):
    command = inbound.add(value or text(challenge), message, **changes)
    return service.respond(MANAGER, challenge.confirmation.confirmation_id, command, challenge.confirmation_token, now=now)


@pytest.mark.parametrize("value", ["OK", "sure", "可以", "👍", "I accept but reject", "ACCEPT proposal_001 v3", "SAYA SETUJU", "我接受", "accept", "OK 😊"])
def test_ambiguous_or_unbound_replies_never_accept(value):
    assert classify_response(value).intent == "UNKNOWN"


@pytest.mark.parametrize("prefix", ["ACCEPT", "SAYA SETUJU", "我接受"])
def test_multilingual_accept_requires_full_bound_message(prefix):
    valid = f"{prefix} proposal_001 v3 terms:{'a' * 64}"
    assert classify_response(valid).intent == "ACCEPT"
    assert classify_response(valid + " but not the deadline").intent == "UNKNOWN"


@pytest.mark.parametrize("value", [
    'COUNTEROFFER p v1 changes:{"quantity":"0"}', 'COUNTEROFFER p v1 changes:{"quantity":"-1"}',
    'COUNTEROFFER p v1 changes:{"quantity":"1","quantity":"2"}',
    'COUNTEROFFER p v1 changes:{"tenant_id":"other"}', 'COUNTEROFFER p v1 changes:{}',
    'COUNTEROFFER p v1 changes:{"deadline":"tomorrow"}',
])
def test_malformed_or_contradictory_counteroffers_are_unresolved(value):
    assert classify_response(value).intent == "UNKNOWN"


def test_secure_token_only_returned_on_creation(challenge, confirmations, db, sent):
    plain = challenge.confirmation_token
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", plain)
    row = db.get(ConfirmationSessionRecord, ("tenant_a", challenge.confirmation.confirmation_id))
    assert row.token_digest == token_digest(plain) and row.token_digest != plain
    persisted = json.dumps({column.name: str(getattr(row, column.name)) for column in row.__table__.columns})
    assert plain not in persisted and plain not in repr(challenge)
    assert plain not in json.dumps([v.model_dump(mode="json") for v in confirmations.list(MANAGER)])
    expect_error("CONFIRMATION_ALREADY_ISSUED", lambda: confirmations.issue(MANAGER,
        CreateConfirmation(outbound_id=sent.outbound_id), now=NOW), 409)


@pytest.mark.parametrize("intent,state,event", [
    ("ACCEPT", "ACCEPTED", "confirmation.accepted"), ("REJECT", "REJECTED", "confirmation.rejected"),
    ("COUNTEROFFER", "COUNTEROFFER_RECEIVED", "confirmation.counteroffer_received"),
    ("CLARIFICATION", "CLARIFICATION_REQUIRED", "confirmation.unresolved"),
    ("UNKNOWN", "UNRESOLVED", "confirmation.unresolved"),
])
def test_response_evidence_and_outbox_never_advance_core(challenge, confirmations, inbound, db, intent, state, event):
    core = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    before = (core.commitment_version, core.agreement_state, core.fulfilment_state, core.terms)
    db.rollback()
    reply = text(challenge, intent)
    if intent == "COUNTEROFFER": reply += ' changes:{"quantity":"80"}'
    if intent == "CLARIFICATION": reply += ': Please explain the revised date'
    if intent == "UNKNOWN": reply = "OK"
    result = respond(confirmations, challenge, inbound, reply)
    assert result.intent == intent
    view = confirmations.get(MANAGER, challenge.confirmation.confirmation_id, now=NOW)
    assert view.state == state and view.core_transition_applied is False
    assert (view.consumed_at is not None) == (intent in {"ACCEPT", "REJECT", "COUNTEROFFER"})
    history = confirmations.history(MANAGER, view.confirmation_id)
    assert len(history) == 1 and history[0] == result
    assert history[0].proposed_changes == ({"quantity": "80"} if intent == "COUNTEROFFER" else None)
    core = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    assert (core.commitment_version, core.agreement_state, core.fulfilment_state, core.terms) == before
    proposal = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    assert proposal.status == "ACTIVE" and proposal.revised_terms == TERMS
    records = db.scalars(select(OutboxEventRecord).where(OutboxEventRecord.event_type == event)).all()
    assert len(records) == 1 and records[0].causation_id == "inbound_test_001"
    assert records[0].payload["proposal_version"] == 3 and records[0].payload["evidence_scope"] == "P4_EVIDENCE_ONLY"
    for model in (OutboxEventRecord, AuditEventRecord):
        for record in db.scalars(select(model).where(model.event_type.like("confirmation.%"))):
            payload = record.payload if isinstance(record, OutboxEventRecord) else record.new_state
            rendered = json.dumps(payload)
            assert challenge.confirmation_token not in rendered and reply not in rendered
            assert "token" not in rendered and "identity_001" not in rendered


def test_unresolved_dedupe_then_explicit_accept_is_once(challenge, confirmations, inbound, db):
    first = respond(confirmations, challenge, inbound, "OK")
    count = db.scalar(select(func.count()).select_from(OutboxEventRecord))
    db.rollback()
    assert respond(confirmations, challenge, inbound, "OK") == first
    assert db.scalar(select(func.count()).select_from(OutboxEventRecord)) == count
    db.rollback()
    expect_error("CONFIRMATION_DUPLICATE_CONFLICT", lambda: respond(confirmations, challenge, inbound, "sure"), 409)
    accepted = respond(confirmations, challenge, inbound, message="explicit_message_002")
    assert accepted.intent == "ACCEPT"
    expect_error("CONFIRMATION_CONSUMED", lambda: respond(confirmations, challenge, inbound, message="third_message_003"), 409)
    assert db.scalar(select(func.count()).select_from(ConfirmationDecisionRecord)) == 2


@pytest.mark.parametrize("case,code", [
    ("customer", "CONFIRMATION_IDENTITY_MISMATCH"), ("tenant", "CONFIRMATION_IDENTITY_MISMATCH"),
    ("channel", "CONFIRMATION_IDENTITY_MISMATCH"), ("sender", "CONFIRMATION_IDENTITY_MISMATCH"),
    ("identity_missing", "CONFIRMATION_IDENTITY_UNVERIFIED"), ("missing_reader", "CONFIRMATION_AUTHORITY_UNAVAILABLE"),
    ("wrong_proposal", "CONFIRMATION_RESPONSE_VERSION_MISMATCH"), ("wrong_version", "CONFIRMATION_RESPONSE_VERSION_MISMATCH"),
    ("wrong_terms", "CONFIRMATION_TERMS_MISMATCH"), ("expired", "CONFIRMATION_EXPIRED"),
    ("revoked", "CONFIRMATION_REVOKED"), ("invalid_token", "CONFIRMATION_TOKEN_INVALID"),
])
def test_response_rejects_invalid_evidence_without_records(challenge, confirmations, inbound, db, case, code):
    value = text(challenge)
    changes = {}
    token = challenge.confirmation_token
    now = NOW
    if case == "customer": changes["customer_id"] = "wrong_customer"
    if case == "tenant": changes["tenant_id"] = "other_tenant"
    if case == "channel": changes["channel"] = "MOCK_WHATSAPP"
    if case == "sender": changes["recipient_identity_id"] = "other_identity"
    if case == "missing_reader": confirmations.authority = None
    if case == "wrong_proposal": value = value.replace("proposal_001", "unrelated")
    if case == "wrong_version": value = value.replace("v3", "v4")
    if case == "wrong_terms": value = value[:-64] + "f" * 64
    if case == "expired": now += timedelta(hours=1)
    if case == "revoked": confirmations.revoke(MANAGER, challenge.confirmation.confirmation_id, now=NOW)
    if case == "invalid_token": token = "z" * 43
    command = inbound.add(value, **changes)
    if case == "identity_missing": inbound.values.clear()
    expect_error(code, lambda: confirmations.respond(MANAGER, challenge.confirmation.confirmation_id, command, token, now=now))
    assert db.scalar(select(func.count()).select_from(ConfirmationAttemptRecord)) == 0
    row = db.get(ConfirmationSessionRecord, ("tenant_a", challenge.confirmation.confirmation_id))
    assert row.consumed_at is None


@pytest.mark.parametrize("changed", ["commitment", "proposal", "terms", "superseded", "rejected", "approval"])
def test_current_proposal_and_approval_are_revalidated_after_issue(challenge, confirmations, inbound, db, approved, changed):
    core = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    proposal = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    if changed == "commitment": core.commitment_version += 1
    if changed == "proposal": proposal.proposal_version += 1
    if changed == "terms": proposal.revised_terms = {**TERMS, "quantity": "101"}
    if changed == "superseded": proposal.status = "SUPERSEDED"
    if changed == "rejected": core.agreement_state = "REJECTED"
    if changed == "approval": approved[1].overrides["existing_review_status"] = "REVOKED"
    db.commit()
    with pytest.raises(DomainError): respond(confirmations, challenge, inbound)
    assert db.scalar(select(func.count()).select_from(ConfirmationDecisionRecord)) == 0


@pytest.mark.parametrize("status", ["QUEUED", "DELIVERY_UNKNOWN", "FAILED"])
def test_ineligible_outbound_never_issues_token(confirmations, sent, db, status):
    row = db.get(OutboundMessageRecord, ("tenant_a", sent.outbound_id))
    row.status, row.provider_confirmed, row.sent_at = status, False, None
    db.commit()
    expect_error("CONFIRMATION_OUTBOUND_NOT_ELIGIBLE", lambda: confirmations.issue(MANAGER,
        CreateConfirmation(outbound_id=sent.outbound_id), now=NOW), 409)
    assert db.scalar(select(func.count()).select_from(ConfirmationSessionRecord)) == 0


@pytest.mark.parametrize("stage", ["issue", "respond"])
def test_transaction_failure_rolls_back_all_confirmation_evidence(confirmations, sent, inbound, db, monkeypatch, stage):
    challenge = confirmations.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW) if stage == "respond" else None
    before = {model: db.scalar(select(func.count()).select_from(model)) for model in
        (ConfirmationSessionRecord, ConfirmationAttemptRecord, ConfirmationDecisionRecord, OutboxEventRecord, AuditEventRecord)}
    db.rollback()
    def fail(): raise OperationalError("test commit", {}, RuntimeError("test-only failure"))
    monkeypatch.setattr(db, "commit", fail)
    operation = (lambda: respond(confirmations, challenge, inbound)) if challenge else (
        lambda: confirmations.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW))
    expect_error("CONFIRMATION_STORAGE_UNAVAILABLE", operation, 503)
    for model, count in before.items():
        assert db.scalar(select(func.count()).select_from(model)) == count
    if challenge:
        assert db.get(ConfirmationSessionRecord, ("tenant_a", challenge.confirmation.confirmation_id)).consumed_at is None


def test_tenant_isolation_and_missing_runtime_authority(challenge, confirmations, db, inbound):
    foreign = RequestContext("tenant_b", MANAGER.actor_id, MANAGER.actor_role, "corr-foreign")
    expect_error("CONFIRMATION_NOT_FOUND", lambda: confirmations.get(foreign, challenge.confirmation.confirmation_id, now=NOW), 404)
    assert confirmations.list(foreign) == []
    with pytest.raises(DomainError): RuntimeConfirmationAccess().authorize(MANAGER, "PROCESS_CONFIRMATION_RESPONSE")
    expect_error("VERIFIED_INBOUND_AUTHORITY_UNAVAILABLE", lambda: UnavailableVerifiedInboundAuthority().resolve(db, MANAGER, "id", now=NOW), 503)


@pytest.mark.parametrize("claims", [{"verified": True}, {"actor_role": "MANAGER"}, {"tenant_id": "tenant_b"},
    {"decision": "ACCEPT"}, {"channel": "MOCK_EMAIL"}, {"customer_id": "customer_001"}])
def test_response_command_cannot_claim_identity_or_decision(claims):
    with pytest.raises(ValueError): ProcessConfirmationResponse(inbound_message_id="known_message", **claims)


@pytest.mark.parametrize("value", [None, "", "short", "!" * 43, "a" * 129])
def test_invalid_token_error_does_not_echo_secret(value):
    with pytest.raises(DomainError) as error: token_digest(value)
    assert error.value.code == "CONFIRMATION_TOKEN_INVALID"
    if value: assert value not in str(error.value)


def test_recipient_consent_revocation_blocks_confirmation_with_actual_p4_gate(db, inbound, monkeypatch):
    from app.communication.preferences import PreferenceCommand, PreferenceService
    from app.communication import preferences as preference_module
    from app.communication.synthetic_authorities import ConsentBoundDraftAuthority
    from app.communication.tests.test_drafting import FixtureDraftAuthority
    from app.communication.tests.test_requests import FixtureAuthority, COMMAND
    from app.communication.service import CommunicationRequestService
    from app.communication.drafting import MessageDraftService
    from app.communication.schemas import PrepareDraftRequest, ApproveDraftRequest, SendMessageRequest
    from app.communication.review import DraftReviewService
    from app.communication.outbound import OutboundService
    from app.communication.providers import LocalMockProvider
    monkeypatch.setattr(preference_module, "utc", lambda value=None: value or NOW)
    contact = SimpleNamespace(channel="MOCK_EMAIL", sender_identity_id="identity_001")
    customer = SimpleNamespace(tenant_id="tenant_a", customer_id="customer_001", active=True, verified_contacts=[contact])
    directory = SimpleNamespace(get_customer=lambda *args: customer, get_contact_for_channel=lambda *args: contact)
    scope = SyntheticScope(True, frozenset({"tenant_a"}))  # Test-only injected scope.
    preferences = PreferenceService(db, scope, directory)
    permission = PreferenceCommand(request_key="confirmation_consent", customer_id="customer_001", channel="MOCK_EMAIL",
        consent_status="OPTED_IN", consent_evidence_ref="synthetic:consent:confirmation_fixture", source="SYNTHETIC_FIXTURE",
        consent_expires_at=NOW + timedelta(days=1), expected_version=0)
    preferences.save(MANAGER, permission, now=NOW)
    request = CommunicationRequestService(db, FixtureAuthority()).create(OWNER, COMMAND, now=NOW)
    draft_policy = ConsentBoundDraftAuthority(FixtureDraftAuthority(), scope, directory)
    draft = MessageDraftService(db, draft_policy).prepare(MANAGER, request.communication_id, PrepareDraftRequest(), now=NOW)
    review = FixtureReviewAuthority()
    DraftReviewService(db, draft_policy, review).approve(MANAGER, request.communication_id, draft.draft_id,
        ApproveDraftRequest(request_key="consent_review_key", expected_content_hash=draft.content_hash), now=NOW)
    sent = OutboundService(db, draft_policy, review, FixtureSendAuthority(), LocalMockProvider()).send(MANAGER,
        request.communication_id, draft.draft_id, SendMessageRequest(request_key="consent_send_key", expected_content_hash=draft.content_hash), now=NOW)
    service = ConfirmationService(db, FixtureAccess(), ExistingP4ConfirmationAuthority(draft_policy, review), inbound)
    challenge = service.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
    preferences.save(MANAGER, permission.model_copy(update={"request_key": "confirmation_revoke", "consent_status": "OPTED_OUT",
        "expected_version": 1, "consent_evidence_ref": "synthetic:consent:confirmation_revocation"}), now=NOW)
    expect_error("CONSENT_REVOKED", lambda: respond(service, challenge, inbound), 403)
    assert db.scalar(select(func.count()).select_from(ConfirmationDecisionRecord)) == 0
