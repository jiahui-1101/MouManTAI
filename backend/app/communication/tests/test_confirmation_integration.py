"""Real migrations/PostgreSQL/HTTP. Upstream authenticated principal evidence is a fixture."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import json

from alembic import command as alembic_command
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, inspect, insert, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.communication.confirmation_authority import ExistingP4ConfirmationAuthority, P1SyntheticInboundAdapter, RuntimeConfirmationAccess
from app.communication.confirmation_router import get_confirmation_access, get_verified_inbound_authority
from app.communication.confirmation_schemas import CreateConfirmation, ProcessConfirmationResponse
from app.communication.confirmations import ConfirmationService
from app.communication.demo_policy import SyntheticScope
from app.communication.models import ConfirmationSessionRecord, ConfirmationAttemptRecord, ConfirmationDecisionRecord
from app.communication.outbound import OutboundService
from app.communication.providers import LocalMockProvider
from app.communication.review import DraftReviewService
from app.communication.router import get_draft_authority, get_review_authority
from app.communication.schemas import ApproveDraftRequest, SendMessageRequest
from app.communication.tests.test_confirmations import FixtureAccess, FixtureInbound, text
from app.communication.tests.test_outbound import FixtureSendAuthority
from app.communication.tests.test_review import MANAGER, FixtureReviewAuthority
from app.communication.tests.test_migration_persistence import migrated, prepare_graph
from app.communication.tests.test_requests import NOW, OWNER, expect_error
from app.core.dependencies import RequestContext, get_db
from app.core.errors import DomainError
from app.core.models import CommitmentRecord, CommitmentProposalRecord, AuditEventRecord, OutboxEventRecord
from app.main import app


def fixture_sent(db):
    request, draft, draft_authority = prepare_graph(db)
    review = FixtureReviewAuthority()
    DraftReviewService(db, draft_authority, review).approve(MANAGER, request.communication_id, draft.draft_id,
        ApproveDraftRequest(request_key="confirmation_review", expected_content_hash=draft.content_hash), now=NOW)
    sent = OutboundService(db, draft_authority, review, FixtureSendAuthority(), LocalMockProvider()).send(
        MANAGER, request.communication_id, draft.draft_id,
        SendMessageRequest(request_key="confirmation_mock_send", expected_content_hash=draft.content_hash), now=NOW)
    return sent, draft_authority, review


def confirmation_service(db, drafts, reviews, source):
    return ConfirmationService(db, FixtureAccess(), ExistingP4ConfirmationAuthority(drafts, reviews), source)


@pytest.mark.parametrize("migrated", ["sqlite", "postgresql"], indirect=True)
@pytest.mark.parametrize("intent", ["ACCEPT", "REJECT", "COUNTEROFFER", "UNKNOWN"])
def test_real_http_persistence_reload_and_events(migrated, intent, monkeypatch):
    engine, _ = migrated
    with Session(engine) as db:
        sent, drafts, reviews = fixture_sent(db)
        before = db.get(CommitmentRecord, ("tenant_a", "com_001"))
        core_before = (before.agreement_state, before.fulfilment_state, before.commitment_version, before.terms)
    source = FixtureInbound()
    def database():
        with Session(engine) as db: yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_confirmation_access] = lambda: FixtureAccess()
    app.dependency_overrides[get_verified_inbound_authority] = lambda: source
    app.dependency_overrides[get_draft_authority] = lambda: drafts
    app.dependency_overrides[get_review_authority] = lambda: reviews
    import app.communication.confirmations as module
    monkeypatch.setattr(module, "utc", lambda value=None: value or NOW)
    headers = {"X-Tenant-ID": "tenant_a", "X-Actor-ID": MANAGER.actor_id}
    try:
        with TestClient(app) as client:
            issued = client.post("/v1/confirmations", headers=headers, json={"outbound_id": sent.outbound_id})
            assert issued.status_code == 200, issued.text
            assert issued.headers["cache-control"] == "no-store"
            value, token = issued.json()["confirmation"], issued.json()["confirmation_token"]
            url = f"/v1/confirmations/{value['confirmation_id']}"
            binding = SimpleNamespace(confirmation=SimpleNamespace(
                reference=SimpleNamespace(**value["reference"]), terms_digest=value["terms_digest"]))
            reply = text(binding, intent)
            if intent == "COUNTEROFFER": reply += ' changes:{"quantity":"80"}'
            if intent == "UNKNOWN": reply = "OK"
            source.add(reply)
            responded = client.post(url + "/respond", headers={**headers, "X-Confirmation-Token": token},
                json={"inbound_message_id": "inbound_test_001"})
            assert responded.status_code == 200, responded.text
            assert responded.json()["intent"] == intent
            assert client.get(url, headers=headers).json()["core_transition_applied"] is False
            history = client.get(url + "/attempts", headers=headers)
            assert history.status_code == 200 and len(history.json()) == 1
            listed = client.get("/v1/confirmations", headers=headers)
            assert len(listed.json()) == 1 and token not in listed.text and "token_digest" not in listed.text
            for response in (history, listed):
                assert token not in response.text and "provider_message_id" not in response.text
            foreign = {**headers, "X-Tenant-ID": "tenant_b"}
            assert client.get(url, headers=foreign).status_code == 404
            staff = {**headers, "X-Actor-ID": "user_staff_01", "X-Confirmation-Token": token}
            assert client.post(url + "/respond", headers=staff, json={"inbound_message_id": "inbound_test_001"}).status_code == 403
        with Session(engine) as db:
            restarted = confirmation_service(db, drafts, reviews, source)
            assert len(restarted.history(MANAGER, value["confirmation_id"])) == 1
            core = db.get(CommitmentRecord, ("tenant_a", "com_001"))
            assert (core.agreement_state, core.fulfilment_state, core.commitment_version, core.terms) == core_before
            assert db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001")).status == "ACTIVE"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
@pytest.mark.parametrize("same_message", [False, True])
def test_postgresql_competing_terminal_responses_only_one_commits(migrated, same_message):
    engine, _ = migrated
    source = FixtureInbound()
    with Session(engine) as db:
        sent, drafts, reviews = fixture_sent(db)
        issued = confirmation_service(db, drafts, reviews, source).issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
    source.add(text(issued), "accept_message")
    source.add(text(issued, "REJECT"), "reject_message")
    barrier = Barrier(2)
    def submit(message):
        with Session(engine) as db:
            service = confirmation_service(db, drafts, reviews, source)
            barrier.wait(timeout=10)
            try:
                return service.respond(MANAGER, issued.confirmation.confirmation_id,
                    ProcessConfirmationResponse(inbound_message_id=message), issued.confirmation_token, now=NOW).intent
            except DomainError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(submit, ["accept_message", "accept_message" if same_message else "reject_message"]))
    assert sum(value in {"ACCEPT", "REJECT"} for value in result) == 1
    assert "CONFIRMATION_CONSUMED" in result
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ConfirmationDecisionRecord)) == 1
        assert db.scalar(select(func.count()).select_from(ConfirmationAttemptRecord)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxEventRecord).where(
            OutboxEventRecord.event_type.in_(["confirmation.accepted", "confirmation.rejected"]))) == 1
        assert db.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.event_type.in_(["confirmation.accepted", "confirmation.rejected"]))) == 1


@pytest.mark.parametrize("migrated", ["sqlite", "postgresql"], indirect=True)
def test_database_exact_scope_terminal_uniqueness_and_delta_downgrade(migrated):
    engine, config = migrated
    source = FixtureInbound()
    with Session(engine) as db:
        sent, drafts, reviews = fixture_sent(db)
        service = confirmation_service(db, drafts, reviews, source)
        issued = service.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
        service.respond(MANAGER, issued.confirmation.confirmation_id, source.add(text(issued)), issued.confirmation_token, now=NOW)
        session = db.get(ConfirmationSessionRecord, ("tenant_a", issued.confirmation.confirmation_id))
        session_values = {c.name: getattr(session, c.name) for c in session.__table__.columns}
        decision = db.scalar(select(ConfirmationDecisionRecord))
        decision_values = {c.name: getattr(decision, c.name) for c in decision.__table__.columns}
        attempt = db.scalar(select(ConfirmationAttemptRecord))
        attempt_values = {c.name: getattr(attempt, c.name) for c in attempt.__table__.columns}
    for updates in ({"tenant_id": "other_tenant", "confirmation_id": "wrong_tenant"},
                    {"communication_id": "wrong_request", "confirmation_id": "wrong_request"},
                    {"confirmation_id": "duplicate_outbound", "token_digest": "a" * 64}):
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(insert(ConfirmationSessionRecord).values(**{**session_values, **updates}))
    for updates in ({"tenant_id": "other_tenant", "attempt_id": "wrong_tenant_attempt"},
                    {"attempt_id": "duplicate_provider", "inbound_message_id": "another_inbound"}):
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(insert(ConfirmationAttemptRecord).values(**{**attempt_values, **updates}))
    # A DISTINCT valid attempt cannot acquire a second terminal decision, even
    # if service locking were absent. This specifically tests terminal uniqueness.
    with engine.begin() as conn:
        conn.execute(insert(ConfirmationAttemptRecord).values(**{**attempt_values,
            "attempt_id": "competing_attempt", "inbound_message_id": "competing_inbound", "provider_message_id": "competing_provider"}))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert(ConfirmationDecisionRecord).values(**{**decision_values, "decision_id": "competing_decision",
                "attempt_id": "competing_attempt", "intent": "REJECT"}))
    alembic_command.downgrade(config, "0010_p4_recipient_preferences")
    assert not any(name.startswith("communication_confirmation_") for name in inspect(engine).get_table_names())
    with Session(engine) as db:
        assert db.get(CommitmentRecord, ("tenant_a", "com_001")).agreement_state == "OFFERED"
        assert len(OutboundService(db, drafts, reviews, FixtureSendAuthority(), LocalMockProvider()).history(
            MANAGER, sent.communication_id)) == 1
    alembic_command.upgrade(config, "head")
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ConfirmationSessionRecord)) == 0


@pytest.mark.parametrize("changed,code", [
    ("unverified", "CONFIRMATION_IDENTITY_UNVERIFIED"), ("conflict", "CONFIRMATION_IDENTITY_UNVERIFIED"),
    ("tenant", "CONFIRMATION_INBOUND_NOT_FOUND"), ("customer_tenant", "CONFIRMATION_IDENTITY_MISMATCH"),
    ("sender", "CONFIRMATION_IDENTITY_MISMATCH"), ("channel", "CONTACT_UNVERIFIED"),
    ("missing", "CONFIRMATION_INBOUND_NOT_FOUND"), ("unavailable", "VERIFIED_INBOUND_AUTHORITY_UNAVAILABLE"),
])
def test_p1_adapter_scopes_and_verifies_existing_evidence(changed, code):
    # Port fixture shaped as the actual P1 MessageRepository + typed Directory;
    # no runtime producer/default fixture, no alternate identity model stored.
    contact = SimpleNamespace(channel="MOCK_WHATSAPP", sender_identity_id="synthetic_contact")
    customer = SimpleNamespace(tenant_id="synthetic_tenant_a", customer_id="cust_bk", active=True, verified_contacts=[contact])
    raw = SimpleNamespace(tenant_id="synthetic_tenant_a", channel="WHATSAPP", provider_message_id="provider_fixture",
        sender_identity_id="synthetic_contact", text="OK")
    message = SimpleNamespace(message_id="message_fixture", raw=raw, synthetic_provider="SYNTHETIC_WHATSAPP", content_sha256="b" * 64)
    association = SimpleNamespace(tenant_id="synthetic_tenant_a", message_id="message_fixture", status="LINK_VERIFIED",
        conflicts=[], verified_customer=customer, association_id="assoc_fixture", version=2)
    repository = SimpleNamespace(get=lambda *args: message, get_association=lambda *args: association)
    directory = SimpleNamespace(get_customer=lambda *args: customer, get_contact_for_channel=lambda *args: contact)
    context = RequestContext("synthetic_tenant_a", MANAGER.actor_id, "MANAGER", "corr-p1")
    adapter = P1SyntheticInboundAdapter(repository, directory, SyntheticScope(True, frozenset({context.tenant_id})))
    assert adapter.resolve(None, context, "message_fixture", now=NOW).evidence_refs[-1] == "p1:association:assoc_fixture:v2"
    if changed == "unverified": association.status = "UNVERIFIED"
    if changed == "conflict": association.conflicts = ["identity mismatch"]
    if changed == "tenant": raw.tenant_id = "other"
    if changed == "customer_tenant": customer.tenant_id = "other"
    if changed == "sender": raw.sender_identity_id = "unknown_sender"
    if changed == "channel": raw.channel = "TELEGRAM"; message.synthetic_provider = "SYNTHETIC_TELEGRAM"
    if changed == "missing": repository.get = lambda *args: None
    if changed == "unavailable": repository.get = lambda *args: (_ for _ in ()).throw(RuntimeError("source offline"))
    expect_error(code, lambda: adapter.resolve(None, context, "message_fixture", now=NOW))


def test_runtime_headers_cannot_impersonate_verified_response_processor(monkeypatch):
    monkeypatch.setenv("APP_ENV", "synthetic")
    monkeypatch.setenv("P4_RUNTIME_MODE", "SYNTHETIC")
    monkeypatch.setenv("P4_SYNTHETIC_TENANTS", "synthetic_tenant_a")
    headers = {"X-Tenant-ID": "synthetic_tenant_a", "X-Actor-ID": MANAGER.actor_id, "X-Confirmation-Token": "a" * 43}
    with TestClient(app) as client:
        result = client.post("/v1/confirmations/nonexistent/respond", headers=headers, json={"inbound_message_id": "known"})
        assert result.status_code == 503 and result.json()["code"] == "CONFIRMATION_PROCESSOR_AUTH_UNAVAILABLE"
        assert "a" * 43 not in result.text
        denied = client.post("/v1/confirmations/nonexistent/respond", headers={**headers, "X-Actor-ID": "user_staff_01"},
            json={"inbound_message_id": "known"})
        assert denied.status_code == 403


def test_actual_p1_typed_records_are_reused_without_ocr_runtime_import(monkeypatch):
    import importlib
    import sys
    from pathlib import Path
    from types import ModuleType
    name = "_p4_confirmation_p1_contract_test"
    module = ModuleType(name)
    module.__path__ = [str(Path(__file__).resolve().parents[2] / "context")]
    monkeypatch.setitem(sys.modules, name, module)
    try:
        models = importlib.import_module(name + ".association_schemas")
        directory = importlib.import_module(name + ".customer_directory").SyntheticCustomerDirectory()
        ingestion = importlib.import_module(name + ".ingestion_schemas")
        customer = directory.get_customer("synthetic_tenant_a", "cust_bk")
        contact = directory.get_contact_for_channel("synthetic_tenant_a", "cust_bk", "MOCK_WHATSAPP")
        message = ingestion.StoredMessage(message_id="actual_p1_fixture", raw={
            "tenant_id": "synthetic_tenant_a", "channel": "WHATSAPP", "provider_message_id": "actual_contract_fixture",
            "sender_identity_id": contact.sender_identity_id, "sender_alias": "Synthetic customer",
            "received_at": NOW, "text": "OK"}, synthetic_provider="SYNTHETIC_WHATSAPP", content_sha256="b" * 64,
            processing_status="RECEIVED", ingested_at=NOW, updated_at=NOW)
        association = models.MessageAssociationRecord(association_id="actual_p1_assoc_fixture", tenant_id="synthetic_tenant_a",
            message_id=message.message_id, status="LINK_VERIFIED", verified_customer=customer, version=1, updated_at=NOW)
        repository = SimpleNamespace(get=lambda *args: message, get_association=lambda *args: association)
        context = RequestContext("synthetic_tenant_a", MANAGER.actor_id, "MANAGER", "corr-real-contract")
        adapter = P1SyntheticInboundAdapter(repository, directory, SyntheticScope(True, frozenset({context.tenant_id})))
        reply = adapter.resolve(None, context, message.message_id, now=NOW)
        assert reply.customer_id == "cust_bk" and reply.recipient_identity_id == contact.sender_identity_id
        assert reply.channel == "MOCK_WHATSAPP"
        # It remains an ambiguous response despite verified synthetic identity.
        from app.communication.response_rules import classify_response
        assert classify_response(reply.text).intent == "UNKNOWN"
    finally:
        for key in list(sys.modules):
            if key.startswith(name + "."): del sys.modules[key]


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
def test_postgresql_failed_response_commit_rolls_back_decision_and_events(migrated, monkeypatch):
    engine, _ = migrated
    source = FixtureInbound()
    with Session(engine) as db:
        sent, drafts, reviews = fixture_sent(db)
        service = confirmation_service(db, drafts, reviews, source)
        issued = service.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
        def fail(): raise OperationalError("test commit", {}, RuntimeError("test-only DB failure"))
        monkeypatch.setattr(db, "commit", fail)
        expect_error("CONFIRMATION_STORAGE_UNAVAILABLE", lambda: service.respond(MANAGER,
            issued.confirmation.confirmation_id, source.add(text(issued)), issued.confirmation_token, now=NOW), 503)
    with Session(engine) as db:
        assert db.get(ConfirmationSessionRecord, ("tenant_a", issued.confirmation.confirmation_id)).consumed_at is None
        for model in (ConfirmationAttemptRecord, ConfirmationDecisionRecord):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        for model in (OutboxEventRecord, AuditEventRecord):
            assert db.scalar(select(func.count()).select_from(model).where(model.event_type == "confirmation.accepted")) == 0


@pytest.mark.parametrize("url,allowed", [
    ("postgresql+psycopg://unused@localhost/p4_migration_test", True),
    ("postgresql+psycopg://unused@localhost/p4_test_confirmation", True),
    ("postgresql+psycopg://unused@localhost/moumantai", False),
    ("postgresql+psycopg://unused@localhost/production", False),
    ("sqlite:///:memory:", False),
])
def test_synthetic_access_uses_actual_disposable_bind_not_environment(url, allowed, monkeypatch):
    from sqlalchemy.engine import make_url
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused@localhost/p4_test_claim")
    db = SimpleNamespace(get_bind=lambda: SimpleNamespace(engine=SimpleNamespace(url=make_url(url))))
    access = RuntimeConfirmationAccess()
    if allowed:
        access.validate_storage(db)
    else:
        expect_error("CONFIRMATION_DISPOSABLE_SCOPE_REQUIRED", lambda: access.validate_storage(db), 503)
