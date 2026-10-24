"""Explicit test-only policy grants; production dependencies are never enabled."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Lock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import OperationalError, IntegrityError
from sqlalchemy.orm import Session

from app.communication.models import OutboundMessageRecord, SendAttemptRecord, DraftReviewRecord, MessageDraftRecord
from app.communication.outbound import OutboundService, RuntimeSendAuthority
from app.communication.providers import LocalMockProvider, SendEnvelope
from app.communication.review import DraftReviewService
from app.communication.schemas import SendAuthorization, SendMessageRequest, ApproveDraftRequest
from app.communication.router import get_send_authority
from app.communication.tests.test_requests import db, authority, service, OWNER, NOW, HEADERS, TERMS, expect_error
from app.communication.tests.test_drafting import draft_authority, drafts, request_id, prepare
from app.communication.tests.test_review import MANAGER, FixtureReviewAuthority
from app.communication.tests.test_migration_persistence import migrated, prepare_graph
from app.core.dependencies import RequestContext, get_db
from app.core.models import CommitmentRecord, CommitmentProposalRecord, AuditEventRecord, OutboxEventRecord
from app.main import app


class FixtureSendAuthority:
    def __init__(self):
        self.overrides = {}
        self.denied = False

    def authorize_send(self, db, context, *, draft, review):
        if self.denied or context.actor_id != MANAGER.actor_id:
            return None
        return SendAuthorization(**{
            "tenant_id": context.tenant_id, "actor_id": context.actor_id, "actor_role": context.actor_role,
            "communication_id": draft.communication_id, "draft_id": draft.draft_id,
            "review_id": review.review_id, "content_hash": draft.content_hash, "validation_hash": draft.validation_hash,
            "action": "SEND_MESSAGE", "evidence_refs": ["ev_test_explicit_send_policy"],
            "expires_at": NOW + timedelta(hours=8), **self.overrides})


class CountingProvider(LocalMockProvider):
    def __init__(self, outcome="SENT"):
        super().__init__(outcome)
        self.calls = 0
        self.lock = Lock()

    def submit(self, envelope):
        with self.lock:
            self.calls += 1
        return super().submit(envelope)


@pytest.fixture
def approved(db, drafts, request_id, draft_authority):
    saved = prepare(drafts, request_id)
    policy = FixtureReviewAuthority()
    DraftReviewService(db, draft_authority, policy).approve(MANAGER, request_id, saved.draft_id,
        ApproveDraftRequest(request_key="outbound_review_key", expected_content_hash=saved.content_hash), now=NOW)
    return saved, policy


@pytest.fixture
def sending(db, draft_authority, approved):
    provider, policy = CountingProvider(), FixtureSendAuthority()
    return OutboundService(db, draft_authority, approved[1], policy, provider)


def command(draft, key="outbound_request_key"):
    return SendMessageRequest(request_key=key, expected_content_hash=draft.content_hash)


def send(sending, approved, key="outbound_request_key", **kwargs):
    draft = approved[0]
    return sending.send(MANAGER, draft.communication_id, draft.draft_id, command(draft, key), now=NOW, **kwargs)


@pytest.mark.parametrize("channel", ["MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"])
def test_local_provider_contract_channels_are_deterministic_and_network_free(approved, channel, monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError("Mock provider must not use network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    value = approved[0].model_copy(update={"channel": channel})
    envelope = SendEnvelope("mock_outbound", value)
    assert LocalMockProvider().submit(envelope) == LocalMockProvider().submit(envelope)
    assert LocalMockProvider().submit(envelope).status == "SENT"


def test_authorized_send_persists_history_without_core_changes(sending, approved, db, monkeypatch):
    core = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    before = (core.commitment_version, core.agreement_state, core.fulfilment_state, core.terms)
    result = send(sending, approved)
    assert result.status == "SENT" and result.provider_confirmed and result.provider_reference.startswith("mock_")
    assert result.sent_at and not result.retry_allowed and not result.reconciliation_required
    assert result.attempts[0].status == "SENT" and result.attempts[0].attempt_number == 1
    assert sending.history(MANAGER, result.communication_id)[0] == result
    db.refresh(core)
    assert (core.commitment_version, core.agreement_state, core.fulfilment_state, core.terms) == before
    assert sending.provider.calls == 1
    key = "synthetic-p4-projection-" + "s" * 32
    monkeypatch.setenv("MOUMANTAI_SYNTHETIC_MODE", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", key)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", MANAGER.actor_id)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID", "tenant_a")
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            path = "/v1/backend-v2/commitments/com_001/operational-evidence"
            headers = {"X-Tenant-ID": "tenant_a", "X-Actor-ID": MANAGER.actor_id,
                       "X-Isolated-E2E-Key": key}
            projection = client.get(path, headers=headers)
            assert client.get(path, headers=headers | {"X-Tenant-ID": "tenant_b"}).status_code == 403
            assert client.get(path, headers=headers | {"X-Actor-ID": "user_staff_01"}).status_code == 403
            audit = db.scalar(select(AuditEventRecord).where(
                AuditEventRecord.tenant_id == "tenant_a",
                AuditEventRecord.event_type == "communication.mock_sent",
            ))
            assert audit is not None
            audit.new_state = {**audit.new_state, "provider_reference": "forged"}
            db.commit()
            unverified = client.get(path, headers=headers)
            assert unverified.status_code == 200
            assert unverified.json()["communications"][0]["outbound_status"] == "UNVERIFIED"
            assert unverified.json()["communications"][0]["provider_receipt_ref"] is None
        assert projection.status_code == 200, projection.text
        outbound = projection.json()["communications"][0]
        assert outbound["outbound_status"] == "MOCK_PROVIDER_SENT"
        assert outbound["provider_receipt_ref"] == result.provider_reference
        assert outbound["customer_delivery"] == "NOT_AVAILABLE"
        assert outbound["customer_agreement"] == "NOT_AVAILABLE"
        assert projection.json()["core"]["customer_status"] == "CHANGE_PROPOSED"
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("outcome,status,code", [
    ("FAILED", "FAILED", "MOCK_PROVIDER_REJECTED"),
    ("DELIVERY_UNKNOWN", "DELIVERY_UNKNOWN", "PROVIDER_TIMEOUT"),
])
def test_failure_timeout_persist_and_never_auto_retry(sending, approved, outcome, status, code):
    sending.provider = CountingProvider(outcome)
    first = send(sending, approved)
    again = send(sending, approved)
    assert first == again and first.status == status and not first.provider_confirmed and first.sent_at is None
    assert first.last_error_code == code and first.retry_allowed is False
    assert sending.provider.calls == 1
    assert first.reconciliation_required == (status == "DELIVERY_UNKNOWN")


def test_same_key_replays_without_duplicate_provider_or_audit(sending, approved, db):
    first = send(sending, approved)
    count = db.scalar(select(func.count()).select_from(AuditEventRecord))
    event_count = db.scalar(select(func.count()).select_from(OutboxEventRecord))
    assert send(sending, approved) == first
    assert sending.provider.calls == 1
    assert db.scalar(select(func.count()).select_from(AuditEventRecord)) == count
    assert db.scalar(select(func.count()).select_from(OutboxEventRecord)) == event_count
    expect_error("SEND_ALREADY_ATTEMPTED", lambda: send(sending, approved, key="different_send_key"), 409)
    assert sending.provider.calls == 1


def test_approval_is_not_send_permission(sending, approved):
    draft = approved[0]
    assert sending.eligibility(MANAGER, draft.communication_id, draft.draft_id, now=NOW).can_send
    sending.authority.denied = True
    expect_error("SEND_FORBIDDEN", lambda: send(sending, approved), 403)
    assert sending.provider.calls == 0


@pytest.mark.parametrize("case,code,status", [
    ("hash", "SEND_CONTENT_CHANGED", 409), ("expired", "APPROVAL_EXPIRED", 409),
    ("superseded", "PROPOSAL_NOT_ELIGIBLE", 409), ("revoked", "APPROVAL_EVIDENCE_REQUIRED", 403),
    ("contact", "VERIFIED_RECIPIENT_REQUIRED", 409), ("channel", "AUTHORIZED_CHANNEL_REQUIRED", 409),
    ("reviewer_revoked", "REVIEW_AUTHORIZATION_REVOKED", 409),
    ("grant_expired", "SEND_FORBIDDEN", 403), ("grant_scope", "SEND_FORBIDDEN", 403),
    ("no_review", "SEND_REVIEW_REQUIRED", 409), ("rejected", "SEND_REVIEW_REQUIRED", 409),
    ("expired_draft", "DRAFT_EXPIRED", 409), ("changed_terms", "APPROVED_TERMS_MISMATCH", 409),
    ("recipient_changed", "DRAFT_REVALIDATION_REQUIRED", 409),
])
def test_send_revalidates_every_authority_and_binding(sending, approved, db, case, code, status):
    draft = approved[0]
    if case == "expired":
        sending.reviews.drafts.authority.overrides = {"approval_expires_at": NOW - timedelta(seconds=1)}
    elif case == "superseded":
        db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001")).status = "SUPERSEDED"
        db.commit()
    elif case == "revoked":
        sending.reviews.drafts.authority.no_approval = True
    elif case == "contact":
        sending.reviews.drafts.authority.overrides = {"recipient_identity_id": None}
    elif case == "recipient_changed":
        sending.reviews.drafts.authority.overrides = {"recipient_identity_id": "changed_identity"}
    elif case == "changed_terms":
        db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001")).revised_terms = {**TERMS, "quantity": "999"}
        db.commit()
    elif case == "expired_draft":
        row = db.get(MessageDraftRecord, ("tenant_a", draft.draft_id))
        row.snapshot = {**row.snapshot, "expires_at": (NOW - timedelta(seconds=1)).isoformat()}
        db.commit()
    elif case == "channel":
        sending.reviews.drafts.authority.overrides = {"channel_evidence_refs": []}
    elif case == "reviewer_revoked":
        sending.reviews.authority.overrides = {"existing_review_status": "REVOKED"}
    elif case == "grant_expired":
        sending.authority.overrides = {"expires_at": NOW - timedelta(seconds=1)}
    elif case == "grant_scope":
        sending.authority.overrides = {"draft_id": "unrelated"}
    elif case in {"no_review", "rejected"}:
        review = sending.reviews.repository.get("tenant_a", draft.communication_id, draft.draft_id)
        if case == "no_review":
            db.delete(review)
        else:
            review.snapshot = {**review.snapshot, "action": "REJECT_DRAFT"}
        db.commit()
    if case == "hash":
        call = lambda: sending.send(MANAGER, draft.communication_id, draft.draft_id,
            SendMessageRequest(request_key="wrong_hash_key", expected_content_hash="f" * 64), now=NOW)
    else:
        call = lambda: send(sending, approved)
    expect_error(code, call, status)
    assert sending.provider.calls == 0


def test_cross_tenant_cannot_send_or_read_history(sending, approved):
    other = RequestContext("tenant_b", MANAGER.actor_id, MANAGER.actor_role, "corr_other")
    draft = approved[0]
    expect_error("DRAFT_NOT_FOUND", lambda: sending.send(other, draft.communication_id, draft.draft_id, command(draft), now=NOW), 404)
    expect_error("COMMUNICATION_NOT_FOUND", lambda: sending.history(other, draft.communication_id), 404)


def test_result_write_failure_preserves_unknown_intent_and_prevents_resubmission(sending, approved, db, monkeypatch):
    original = db.commit
    calls = 0
    def commit():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OperationalError("test result persistence outage", {}, Exception("test"))
        original()
    monkeypatch.setattr(db, "commit", commit)
    result = send(sending, approved)
    assert result.status == "DELIVERY_UNKNOWN" and not result.provider_confirmed
    assert sending.provider.calls == 1
    with Session(db.get_bind()) as other:
        row = other.get(OutboundMessageRecord, ("tenant_a", result.outbound_id))
        assert row.status == "DELIVERY_UNKNOWN" and row.sent_at is None
        assert other.scalar(select(func.count()).select_from(OutboxEventRecord).where(
            OutboxEventRecord.event_type == "communication.mock_sent")) == 0
    assert send(sending, approved).status == "DELIVERY_UNKNOWN"
    assert sending.provider.calls == 1


def test_eligibility_is_server_validated_and_consumed_after_send(sending, approved):
    draft = approved[0]
    assert sending.eligibility(MANAGER, draft.communication_id, draft.draft_id, now=NOW).can_send
    send(sending, approved)
    assert not sending.eligibility(MANAGER, draft.communication_id, draft.draft_id, now=NOW).can_send
    assert isinstance(get_send_authority(), RuntimeSendAuthority)
    sending.authority = get_send_authority()
    assert not sending.eligibility(MANAGER, draft.communication_id, draft.draft_id, now=NOW).can_send
    expect_error("SEND_AUTHORITY_UNAVAILABLE", lambda: send(sending, approved), 503)


def test_sent_and_failed_summary_use_distinct_database_requests(sending, approved, db):
    draft = approved[0]
    result = send(sending, approved)
    summary = sending.reviews.drafts.summary(MANAGER, now=NOW)
    assert summary.sent == 1 and summary.drafted == 0 and summary.needs_attention == 0
    # A second language is a separate exact draft, still the same request metric.
    second = prepare(sending.reviews.drafts, draft.communication_id, "zh")
    sending.reviews.approve(MANAGER, draft.communication_id, second.draft_id,
        ApproveDraftRequest(request_key="review_second_draft", expected_content_hash=second.content_hash), now=NOW)
    sending.provider = CountingProvider("FAILED")
    sending.send(MANAGER, draft.communication_id, second.draft_id, command(second, "second_send_key"), now=NOW)
    summary = sending.reviews.drafts.summary(MANAGER, now=NOW)
    assert summary.total == 1 and summary.sent == 1 and summary.needs_attention == 1
    request_row = sending.reviews.drafts.requests.repository.get("tenant_a", draft.communication_id)
    request_row.request_status = "BLOCKED"
    db.commit()
    summary = sending.reviews.drafts.summary(MANAGER, now=NOW)
    assert summary.needs_attention == 1 and summary.drafted == 0  # blocked + failed deduplicate
    assert result.status == "SENT"


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
@pytest.mark.parametrize("same_key", [True, False])
def test_postgresql_concurrent_submissions_call_provider_at_most_once(migrated, same_key):
    engine, _ = migrated
    provider = CountingProvider()
    with Session(engine) as db:
        request, draft, draft_policy = prepare_graph(db)
        review_policy = FixtureReviewAuthority()
        DraftReviewService(db, draft_policy, review_policy).approve(MANAGER, request.communication_id, draft.draft_id,
            ApproveDraftRequest(request_key="pg_approve_key", expected_content_hash=draft.content_hash), now=NOW)
    barrier = Barrier(2, timeout=15)
    def run(index):
        with Session(engine) as db:
            db.connection()
            barrier.wait()
            outbound = OutboundService(db, draft_policy, review_policy, FixtureSendAuthority(), provider)
            try:
                return outbound.send(MANAGER, request.communication_id, draft.draft_id,
                    command(draft, "same_pg_send_key" if same_key else f"pg_send_key_{index}"), now=NOW).outbound_id
            except Exception as error:
                from app.core.errors import DomainError
                assert isinstance(error, DomainError) and error.code == "SEND_ALREADY_ATTEMPTED"
                return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [1, 2]))
    assert provider.calls == 1
    assert (results[0] == results[1]) if same_key else results.count("conflict") == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(OutboundMessageRecord)) == 1
        assert db.scalar(select(func.count()).select_from(SendAttemptRecord)) == 1


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
def test_actual_http_runtime_cannot_enable_send_with_demo_headers(migrated):
    engine, _ = migrated
    with Session(engine) as db:
        request, draft, _ = prepare_graph(db)
    previous = app.dependency_overrides.copy()
    def database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        with TestClient(app) as client:
            path = f"/v1/communications/{request.communication_id}/drafts/{draft.draft_id}"
            eligibility = client.get(path + "/send-eligibility", headers=HEADERS)
            assert eligibility.status_code == 200 and not eligibility.json()["can_send"]
            response = client.post(path + "/send", headers=HEADERS, json=command(draft).model_dump())
            assert response.status_code == 503 and response.json()["code"] == "SEND_AUTHORITY_UNAVAILABLE"
            assert client.post(path + "/send", headers=HEADERS, json={**command(draft).model_dump(), "approved": True}).status_code == 422
            assert client.get(f"/v1/communications/{request.communication_id}/outbound", headers=HEADERS).json() == []
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("field", ["tenant_id", "approved", "role", "provider_sent", "body", "recipient_identity_id", "channel", "customer_accepted", "fulfilled"])
def test_send_http_command_rejects_all_client_authority_and_content_claims(field):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SendMessageRequest.model_validate({"request_key": "safe_test_key", "expected_content_hash": "a" * 64, field: True})


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
@pytest.mark.parametrize("case", ["same_draft", "request_key", "cross_tenant", "exact_review", "provider_reference", "unconfirmed_sent", "attempt_number", "attempt_tenant"])
def test_postgresql_outbound_constraints_reject_invalid_rows(migrated, case):
    engine, _ = migrated
    with Session(engine) as db:
        request, draft, draft_policy = prepare_graph(db)
        review_policy = FixtureReviewAuthority()
        reviews = DraftReviewService(db, draft_policy, review_policy)
        reviews.approve(MANAGER, request.communication_id, draft.draft_id,
            ApproveDraftRequest(request_key="constraint_review_1", expected_content_hash=draft.content_hash), now=NOW)
        outbound = OutboundService(db, draft_policy, review_policy, FixtureSendAuthority(), CountingProvider())
        result = outbound.send(MANAGER, request.communication_id, draft.draft_id, command(draft), now=NOW)
        if case.startswith("attempt_"):
            candidate = SendAttemptRecord(tenant_id="tenant_b" if case == "attempt_tenant" else "tenant_a",
                outbound_id=result.outbound_id, attempt_number=1 if case == "attempt_tenant" else 2,
                status="QUEUED", started_at=NOW)
        else:
            original = db.get(OutboundMessageRecord, ("tenant_a", result.outbound_id))
            data = {c.name: getattr(original, c.name) for c in OutboundMessageRecord.__table__.columns}
            data.update(outbound_id="outbound_invalid", request_key="invalid_request_key", provider_reference=None,
                        status="DELIVERY_UNKNOWN", provider_confirmed=False, sent_at=None)
            if case in {"request_key", "exact_review", "provider_reference", "unconfirmed_sent"}:
                second = prepare(reviews.drafts, request.communication_id, "zh")
                review = reviews.approve(MANAGER, request.communication_id, second.draft_id,
                    ApproveDraftRequest(request_key="constraint_review_2", expected_content_hash=second.content_hash), now=NOW)
                data.update(draft_id=second.draft_id, approved_review_id=review.decision.review_id,
                            content_hash=second.content_hash, validation_hash=second.validation_hash)
            if case == "request_key":
                data["request_key"] = original.request_key
            elif case == "cross_tenant":
                data["tenant_id"] = "tenant_b"
            elif case == "exact_review":
                data["approved_review_id"] = original.approved_review_id
            elif case == "provider_reference":
                data.update(status="SENT", provider_reference=original.provider_reference, provider_confirmed=True, sent_at=NOW)
            elif case == "unconfirmed_sent":
                data["status"] = "SENT"
            candidate = OutboundMessageRecord(**data)
        db.add(candidate)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(OutboundMessageRecord)) == 1


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
def test_postgresql_result_failure_and_delta_downgrade_preserve_prior_p4_data(migrated, monkeypatch):
    from alembic import command as alembic_command
    engine, cfg = migrated
    with Session(engine) as db:
        request, draft, draft_policy = prepare_graph(db)
        review_policy = FixtureReviewAuthority()
        review = DraftReviewService(db, draft_policy, review_policy).approve(MANAGER, request.communication_id, draft.draft_id,
            ApproveDraftRequest(request_key="pg_failure_review", expected_content_hash=draft.content_hash), now=NOW)
        outbound = OutboundService(db, draft_policy, review_policy, FixtureSendAuthority(), CountingProvider())
        original = db.commit
        count = 0
        def fail_final_commit():
            nonlocal count
            count += 1
            if count == 3:
                raise OperationalError("test after provider success", {}, Exception("test"))
            original()
        monkeypatch.setattr(db, "commit", fail_final_commit)
        result = outbound.send(MANAGER, request.communication_id, draft.draft_id, command(draft), now=NOW)
        assert result.status == "DELIVERY_UNKNOWN" and outbound.provider.calls == 1
        assert outbound.send(MANAGER, request.communication_id, draft.draft_id, command(draft), now=NOW).status == "DELIVERY_UNKNOWN"
        assert outbound.provider.calls == 1
    with Session(engine) as db:
        assert db.get(OutboundMessageRecord, ("tenant_a", result.outbound_id)).status == "DELIVERY_UNKNOWN"
        assert OutboundService(db, draft_policy, review_policy, FixtureSendAuthority(), CountingProvider()).reviews.drafts.summary(MANAGER, now=NOW).sent == 0
    alembic_command.downgrade(cfg, "0008_p4_communication")
    tables = set(inspect(engine).get_table_names())
    assert "communication_outbound_messages" not in tables and "communication_send_attempts" not in tables
    assert {"communication_requests", "communication_drafts", "communication_draft_reviews", "commitments", "recovery_cases"} <= tables
    with Session(engine) as db:
        assert db.get(MessageDraftRecord, ("tenant_a", draft.draft_id)) is not None
        assert db.get(DraftReviewRecord, ("tenant_a", review.decision.review_id)) is not None
    alembic_command.upgrade(cfg, "head")
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(OutboundMessageRecord)) == 0


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
def test_postgresql_mock_sending_http_path_with_explicit_test_only_authorities(migrated):
    from app.communication.router import get_draft_authority, get_review_authority, get_outbound_provider
    engine, _ = migrated
    review_policy, send_policy, provider = FixtureReviewAuthority(), FixtureSendAuthority(), CountingProvider()
    with Session(engine) as db:
        request, draft, draft_policy = prepare_graph(db)
        DraftReviewService(db, draft_policy, review_policy).approve(MANAGER, request.communication_id, draft.draft_id,
            ApproveDraftRequest(request_key="pg_http_review", expected_content_hash=draft.content_hash), now=NOW)
    previous = app.dependency_overrides.copy()
    def database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides.update({get_db: database, get_draft_authority: lambda: draft_policy,
        get_review_authority: lambda: review_policy, get_send_authority: lambda: send_policy,
        get_outbound_provider: lambda: provider})
    # These fixture expiries are fixed; pin only the service clock inside this test.
    from app.communication.drafting import MessageDraftService
    clock = MessageDraftService._time
    MessageDraftService._time = staticmethod(lambda now: NOW)
    headers = {**HEADERS, "X-Actor-ID": MANAGER.actor_id}
    try:
        with TestClient(app) as client:
            base = f"/v1/communications/{request.communication_id}"
            path = base + f"/drafts/{draft.draft_id}"
            assert client.get(path + "/send-eligibility", headers=headers).json()["can_send"]
            response = client.post(path + "/send", headers=headers, json=command(draft).model_dump())
            assert response.status_code == 200 and response.json()["status"] == "SENT"
            assert client.post(path + "/send", headers=headers, json=command(draft).model_dump()).json()["outbound_id"] == response.json()["outbound_id"]
            assert provider.calls == 1
            assert client.get(base + "/outbound", headers=headers).json()[0]["provider_confirmed"]
            assert client.get(base, headers=headers).json()["outbound_status"] == "SENT"
            summary = client.get("/v1/communications/summary", headers=headers).json()
            assert summary["sent"] == 1 and summary["drafted"] == 0
    finally:
        MessageDraftService._time = staticmethod(clock)
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_missing_outbound_storage_keeps_sent_unavailable_not_zero(db, drafts):
    SendAttemptRecord.__table__.drop(db.get_bind())
    OutboundMessageRecord.__table__.drop(db.get_bind())
    summary = drafts.summary(MANAGER, now=NOW)
    assert summary.sent is None and summary.unavailable_reasons["sent"] == "SENDING_RECORDS_UNAVAILABLE"
    assert summary.unavailable_reasons["needs_attention"] == "SENDING_RECORDS_UNAVAILABLE"


def test_failed_claim_transaction_never_calls_provider(sending, approved, db, monkeypatch):
    def fail():
        raise OperationalError("test claim commit failure", {}, Exception("test"))
    monkeypatch.setattr(db, "commit", fail)
    expect_error("SEND_STORAGE_UNAVAILABLE", lambda: send(sending, approved), 503)
    assert sending.provider.calls == 0
    assert db.scalar(select(func.count()).select_from(OutboundMessageRecord)) == 0


def test_abandoned_queued_intent_never_resumes_automatically(sending, approved, monkeypatch):
    original = sending.authority.authorize_send
    count = 0
    def revoked_once(*args, **kwargs):
        nonlocal count
        count += 1
        return None if count == 2 else original(*args, **kwargs)
    monkeypatch.setattr(sending.authority, "authorize_send", revoked_once)
    expect_error("SEND_FORBIDDEN", lambda: send(sending, approved), 403)
    replay = send(sending, approved)
    assert replay.status == "QUEUED" and replay.reconciliation_required
    assert sending.provider.calls == 0


def test_request_key_cannot_be_rebound_to_a_different_draft(sending, approved):
    original = send(sending, approved)
    second = prepare(sending.reviews.drafts, original.communication_id, "zh")
    sending.reviews.approve(MANAGER, original.communication_id, second.draft_id,
        ApproveDraftRequest(request_key="another_review_key", expected_content_hash=second.content_hash), now=NOW)
    expect_error("SEND_IDEMPOTENCY_CONFLICT", lambda: sending.send(MANAGER, original.communication_id, second.draft_id,
        command(second), now=NOW), 409)
    assert sending.provider.calls == 1


@pytest.mark.parametrize("kind", ["exception", "invalid_success"])
def test_untrusted_provider_result_is_unknown_not_sent(sending, approved, monkeypatch, kind):
    from app.communication.providers import ProviderResult
    def submit(envelope):
        if kind == "exception":
            raise RuntimeError("secret provider credentials must not be exposed")
        return ProviderResult("SENT", provider_reference=None)
    monkeypatch.setattr(sending.provider, "submit", submit)
    result = send(sending, approved)
    assert result.status == "DELIVERY_UNKNOWN" and not result.provider_confirmed
    assert result.last_error_code == "PROVIDER_RESULT_UNCERTAIN" and result.sent_at is None


@pytest.mark.parametrize("channel", ["MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"])
def test_authorized_workflow_supports_every_contract_mock_channel(db, drafts, request_id, draft_authority, channel):
    draft_authority.overrides = {"channel": channel, "channel_evidence_refs": [f"ev_test_consent_{channel}"]}
    draft = prepare(drafts, request_id)
    review_policy = FixtureReviewAuthority()
    DraftReviewService(db, draft_authority, review_policy).approve(MANAGER, request_id, draft.draft_id,
        ApproveDraftRequest(request_key="channel_review_key", expected_content_hash=draft.content_hash), now=NOW)
    result = OutboundService(db, draft_authority, review_policy, FixtureSendAuthority(), LocalMockProvider()).send(
        MANAGER, request_id, draft.draft_id, command(draft), now=NOW)
    assert result.status == "SENT" and result.channel == channel and result.provider_confirmed
