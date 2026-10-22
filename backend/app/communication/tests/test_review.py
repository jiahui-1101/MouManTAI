"""Review authority doubles and isolated SQLite are test-only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, local

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.communication.models import DraftReviewRecord, MessageDraftRecord
from app.communication.review import DraftReviewService
from app.communication.router import get_review_service, router
from app.communication.schemas import ApproveDraftRequest, RejectDraftRequest, ReviewAuthorization
from app.communication.tests.test_drafting import (
    db, authority, service, request_id, draft_authority, drafts, prepare, FixtureDraftAuthority,
)
from app.communication.tests.test_requests import NOW, OWNER, HEADERS, TERMS, count, expect_error
from app.core.dependencies import RequestContext, get_db
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentProposalRecord, CommitmentRecord, OutboxEventRecord
from app.main import domain_error_handler, validation_exception_handler

MANAGER = RequestContext("tenant_a", "user_manager_01", "MANAGER", "corr_review")


class FixtureReviewAuthority:
    def __init__(self):
        self.overrides = {}
        self.denied = False
        self.calls = []

    def authorize_review(self, db, context, *, communication_id, draft_id, action, existing_review):
        self.calls.append(action)
        # Explicit test membership/policy; no production actor gets this grant.
        if self.denied or context.tenant_id != "tenant_a" or context.actor_id not in {"user_manager_01", "manager_01"}:
            return None
        return ReviewAuthorization(**{
            "tenant_id": context.tenant_id, "actor_id": context.actor_id, "actor_role": context.actor_role,
            "communication_id": communication_id, "draft_id": draft_id, "action": action,
            "evidence_refs": ["ev_explicit_manager_membership_and_action"], "expires_at": NOW + timedelta(hours=8),
            "allowed_actions": ["APPROVE_DRAFT", "REJECT_DRAFT"], "existing_review_status": "VALID",
            "existing_review_evidence_refs": ["ev_current_original_reviewer_policy"], **self.overrides,
        })


@pytest.fixture
def review_authority():
    return FixtureReviewAuthority()


@pytest.fixture
def reviews(db, draft_authority, review_authority):
    return DraftReviewService(db, draft_authority, review_authority)


@pytest.fixture
def saved(drafts, request_id):
    return prepare(drafts, request_id)


def command(saved, key="request_approve_001"):
    return ApproveDraftRequest(request_key=key, expected_content_hash=saved.content_hash)


def approve(reviews, saved, **kwargs):
    return reviews.approve(MANAGER, saved.communication_id, saved.draft_id, command(saved), now=NOW, **kwargs)


def read(reviews, saved, **kwargs):
    return reviews.get(MANAGER, saved.communication_id, saved.draft_id, now=NOW, **kwargs)


def reject(reviews, saved, key="request_reject_001", reason="Please revise the greeting"):
    return reviews.reject(MANAGER, saved.communication_id, saved.draft_id,
                          RejectDraftRequest(request_key=key, expected_content_hash=saved.content_hash, reason=reason), now=NOW)


def test_pending_review_and_permissions_come_from_trusted_policy(reviews, saved):
    result = read(reviews, saved)
    assert result.review_state == "PENDING" and not result.effective_approval
    assert result.allowed_actions == ["APPROVE_DRAFT", "REJECT_DRAFT"]


def test_authorized_manager_approves_exact_persisted_content_without_send_or_core_changes(db, reviews, saved):
    before = count(db, OutboxEventRecord)
    core = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    original = (core.commitment_version, core.agreement_state, core.fulfilment_state)
    result = approve(reviews, saved)
    assert result.review_state == "APPROVED" and result.effective_approval and not result.send_authorized
    assert result.decision.content_hash == saved.content_hash
    assert result.decision.reference == saved.reference
    assert (result.decision.language, result.decision.recipient_identity_id, result.decision.channel) == (
        saved.language, saved.recipient_identity_id, saved.channel,
    )
    assert result.decision.reviewer_id == MANAGER.actor_id
    assert result.decision.core_approval_evidence_refs == saved.approval_evidence_refs
    assert result.allowed_actions == []
    assert count(db, OutboxEventRecord) == before
    assert (core.commitment_version, core.agreement_state, core.fulfilment_state) == original
    assert db.get(AuditEventRecord, result.decision.audit_id).event_type == "communication.draft_approved"


def test_review_survives_a_fresh_database_session(db, reviews, saved, draft_authority, review_authority):
    first = approve(reviews, saved)
    with Session(db.get_bind()) as other:
        again = read(DraftReviewService(other, draft_authority, review_authority), saved)
        assert again.decision == first.decision and again.effective_approval


@pytest.mark.parametrize("context", [OWNER, RequestContext("tenant_a", "user_staff_01", "STAFF", "corr")])
def test_simulated_owner_or_staff_is_not_implicitly_authorized(reviews, saved, context):
    expect_error("REVIEW_FORBIDDEN", lambda: reviews.approve(context, saved.communication_id, saved.draft_id, command(saved), now=NOW), 403)


def test_cross_tenant_or_wrong_request_never_reveals_or_approves_a_draft(reviews, saved):
    other = RequestContext("tenant_b", MANAGER.actor_id, MANAGER.actor_role, "corr")
    expect_error("DRAFT_NOT_FOUND", lambda: reviews.approve(other, saved.communication_id, saved.draft_id, command(saved), now=NOW), 404)
    expect_error("DRAFT_NOT_FOUND", lambda: reviews.approve(MANAGER, "other-request", saved.draft_id, command(saved), now=NOW), 404)


def test_missing_draft(reviews, saved):
    expect_error("DRAFT_NOT_FOUND", lambda: reviews.approve(MANAGER, saved.communication_id, "missing", command(saved), now=NOW), 404)


@pytest.mark.parametrize("change,code", [
    ({"approval_expires_at": NOW - timedelta(seconds=1)}, "APPROVAL_EXPIRED"),
    ({"channel": "MOCK_TELEGRAM"}, "DRAFT_REVALIDATION_REQUIRED"),
    ({"recipient_identity_id": "another"}, "DRAFT_REVALIDATION_REQUIRED"),
])
def test_fresh_validation_blocks_changed_approval_recipient_or_channel(db, reviews, saved, draft_authority, change, code):
    draft_authority.overrides = change
    expect_error(code, lambda: approve(reviews, saved))
    assert count(db, DraftReviewRecord) == 0


def test_revoked_core_approval_cannot_create_message_approval(reviews, saved, draft_authority):
    draft_authority.no_approval = True
    expect_error("APPROVAL_EVIDENCE_REQUIRED", lambda: approve(reviews, saved))


def test_superseded_proposal_cannot_be_approved(db, reviews, saved):
    db.add(CommitmentProposalRecord(tenant_id="tenant_a", commitment_id="com_001", proposal_id="proposal_004",
        proposal_version=4, revised_terms=TERMS, status="ACTIVE", reason="new", evidence_refs=["ev_new"], created_at=NOW, updated_at=NOW))
    db.commit()
    expect_error("STALE_PROPOSAL_VERSION", lambda: approve(reviews, saved))


def test_expired_proposal_cannot_be_reviewed(reviews, saved, review_authority):
    review_authority.overrides = {"expires_at": NOW + timedelta(days=3)}
    expect_error("PROPOSAL_EXPIRED", lambda: reviews.approve(MANAGER, saved.communication_id, saved.draft_id, command(saved), now=NOW + timedelta(days=1, seconds=1)))


@pytest.mark.parametrize("field,value", [("body", "Free delivery"), ("content_hash", "f" * 64)])
def test_tampered_draft_cannot_be_approved(db, reviews, saved, field, value):
    row = db.get(MessageDraftRecord, ("tenant_a", saved.draft_id))
    row.snapshot = {**row.snapshot, field: value}
    db.commit()
    expect_error("DRAFT_INTEGRITY_ERROR", lambda: approve(reviews, saved))


def test_optimistic_preview_hash_must_match_even_when_server_draft_is_valid(reviews, saved):
    bad = ApproveDraftRequest(request_key="request_wrong_hash", expected_content_hash="f" * 64)
    expect_error("REVIEW_CONTENT_CHANGED", lambda: reviews.approve(MANAGER, saved.communication_id, saved.draft_id, bad, now=NOW))


def test_blocked_request_cannot_be_reviewed(db, reviews, saved):
    row = reviews.drafts.requests.repository.get("tenant_a", saved.communication_id)
    row.request_status = "BLOCKED"
    db.commit()
    expect_error("REVIEW_REQUEST_BLOCKED", lambda: approve(reviews, saved))


def test_rejection_is_terminal_and_preserves_reason_and_original_proposal(db, reviews, saved):
    result = reject(reviews, saved)
    assert result.review_state == "REJECTED" and not result.effective_approval
    assert result.decision.reason == "Please revise the greeting"
    assert read(reviews, saved).decision == result.decision
    expect_error("REVIEW_ALREADY_DECIDED", lambda: approve(reviews, saved))
    assert db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001")).status == "ACTIVE"


@pytest.mark.parametrize("reason", ["", "  \n ", "x" * 1001])
def test_empty_or_excessive_rejection_reason_is_invalid(saved, reason):
    with pytest.raises(ValidationError):
        RejectDraftRequest(request_key="reject_reason_key", expected_content_hash=saved.content_hash, reason=reason)


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_duplicate_retry_returns_same_record_and_one_audit(db, reviews, saved, action):
    operation = approve if action == "approve" else reject
    before = count(db, AuditEventRecord)
    first, second = operation(reviews, saved), operation(reviews, saved)
    assert first.decision == second.decision
    assert count(db, DraftReviewRecord) == 1 and count(db, AuditEventRecord) == before + 1


def test_different_reviewer_cannot_silently_override_decision(reviews, saved):
    approve(reviews, saved)
    other = RequestContext("tenant_a", "manager_01", "MANAGER", "corr_other")
    expect_error("REVIEW_ALREADY_DECIDED", lambda: reviews.approve(other, saved.communication_id, saved.draft_id, command(saved), now=NOW))
    expect_error("REVIEW_ALREADY_DECIDED", lambda: reject(reviews, saved))


def test_idempotency_key_cannot_be_reused_for_another_draft(reviews, drafts, request_id, saved):
    approve(reviews, saved)
    other = prepare(drafts, request_id, "zh")
    expect_error("REVIEW_IDEMPOTENCY_CONFLICT", lambda: approve(reviews, other))


def test_invalidated_approval_is_latched_and_history_never_overwritten(db, reviews, saved, draft_authority):
    first = approve(reviews, saved)
    before = count(db, AuditEventRecord)
    draft_authority.no_approval = True
    invalid = read(reviews, saved)
    assert invalid.review_state == "INVALIDATED" and not invalid.effective_approval
    assert invalid.decision == first.decision and invalid.invalidation_audit_id
    assert count(db, AuditEventRecord) == before + 1
    draft_authority.no_approval = False
    assert read(reviews, saved).review_state == "INVALIDATED"
    expect_error("REVIEW_INVALIDATED", lambda: approve(reviews, saved))
    assert count(db, AuditEventRecord) == before + 1


def test_expired_review_grant_cannot_be_extended_by_retry(reviews, saved, review_authority):
    approve(reviews, saved)
    review_authority.overrides = {"expires_at": NOW + timedelta(days=3)}
    value = reviews.get(MANAGER, saved.communication_id, saved.draft_id, now=NOW + timedelta(hours=9))
    # Reissue reader authorization only: the original approved grant still expires.
    assert value.review_state == "INVALIDATED"


@pytest.mark.parametrize("state,expected", [("REVOKED", "INVALIDATED"), ("UNKNOWN", "unavailable")])
def test_original_reviewer_authorization_is_revalidated(reviews, saved, review_authority, state, expected):
    approve(reviews, saved)
    review_authority.overrides = {"existing_review_status": state}
    if expected == "unavailable":
        expect_error("REVIEW_VALIDATION_UNAVAILABLE", lambda: read(reviews, saved), 503)
    else:
        assert read(reviews, saved).review_state == expected


def test_review_audit_binding_detects_tampered_decision(db, reviews, saved):
    approve(reviews, saved)
    row = db.scalar(select(DraftReviewRecord))
    row.snapshot = {**row.snapshot, "reviewer_id": "forged"}
    db.commit()
    expect_error("REVIEW_INTEGRITY_ERROR", lambda: read(reviews, saved))


def test_missing_review_or_draft_authority_fails_closed(db, reviews, saved, review_authority, draft_authority):
    expect_error("REVIEW_AUTHORITY_UNAVAILABLE", lambda: approve(DraftReviewService(db, draft_authority), saved), 503)
    expect_error("DRAFT_REVALIDATION_UNAVAILABLE", lambda: approve(DraftReviewService(db, None, review_authority), saved), 503)


@pytest.mark.parametrize("override", [{"tenant_id": "tenant_b"}, {"actor_id": "another"}, {"action": "READ_REVIEW"}, {"expires_at": NOW}])
def test_policy_result_must_bind_actual_actor_tenant_action_and_time(reviews, saved, review_authority, override):
    review_authority.overrides = override
    expect_error("REVIEW_FORBIDDEN", lambda: approve(reviews, saved), 403)


def test_atomic_rollback_on_persistence_failure(db, reviews, saved, monkeypatch):
    before = count(db, AuditEventRecord)
    def fail(): raise OperationalError("commit", {}, Exception("fixture"))
    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail)
        expect_error("REVIEW_STORAGE_UNAVAILABLE", lambda: approve(reviews, saved), 503)
    assert count(db, DraftReviewRecord) == 0 and count(db, AuditEventRecord) == before


def test_missing_review_table_returns_explicit_migration_error(db, reviews, saved):
    DraftReviewRecord.__table__.drop(db.get_bind())
    expect_error("REVIEW_STORAGE_UNAVAILABLE", lambda: read(reviews, saved), 503)


def test_concurrent_approve_reject_preserves_one_terminal_record(db, drafts, saved):
    engine = db.get_bind()
    db.rollback()
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")  # test-only concurrency fixture
    barrier, seen = Barrier(2), local()
    class RacingAuthority(FixtureReviewAuthority):
        def authorize_review(self, *args, **kwargs):
            result = super().authorize_review(*args, **kwargs)
            if not getattr(seen, "waited", False):
                seen.waited = True
                barrier.wait(timeout=10)
            return result
    def operation(action):
        with Session(engine) as session:
            worker = DraftReviewService(session, FixtureDraftAuthority(), RacingAuthority())
            try:
                return (approve(worker, saved) if action == "approve" else reject(worker, saved)).review_state
            except DomainError as exc:
                return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(operation, ["approve", "reject"]))
    assert sum(value in {"APPROVED", "REJECTED"} for value in outcomes) == 1, outcomes
    assert "REVIEW_ALREADY_DECIDED" in outcomes, outcomes
    assert count(db, DraftReviewRecord) == 1


def test_postgres_ddl_has_exact_draft_fk_terminal_and_request_key_constraints():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable
    ddl = str(CreateTable(DraftReviewRecord.__table__).compile(dialect=postgresql.dialect()))
    assert all(name in ddl for name in ["fk_review_exact_draft", "uq_review_terminal_draft", "uq_review_request_key"])


@pytest.fixture
def api(reviews):
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    for method in ("get", "approve", "reject"):
        original = getattr(reviews, method)
        setattr(reviews, method, lambda *args, _original=original: _original(*args, now=NOW))
    app.dependency_overrides[get_review_service] = lambda: reviews
    with TestClient(app) as client:
        yield client


def test_api_get_approve_and_reject_are_separate_from_proposal_approval(api, saved):
    path = f"/v1/communications/{saved.communication_id}/drafts/{saved.draft_id}"
    headers = {**HEADERS, "X-Actor-ID": MANAGER.actor_id}
    assert api.get(path + "/review", headers=headers).json()["review_state"] == "PENDING"
    result = api.post(path + "/approve", headers=headers, json=command(saved).model_dump())
    assert result.status_code == 200 and result.json()["review_state"] == "APPROVED"
    assert api.post(path + "/approve", headers=headers, json=command(saved).model_dump()).json()["decision"] == result.json()["decision"]
    assert api.get(path + "/review", headers=headers).json()["effective_approval"] is True


@pytest.mark.parametrize("extra", [{"approved": True}, {"reviewer_role": "MANAGER"}, {"body": "invented"}])
def test_api_rejects_client_authority_and_message_claims(api, saved, extra):
    path = f"/v1/communications/{saved.communication_id}/drafts/{saved.draft_id}/approve"
    assert api.post(path, headers=HEADERS, json={**command(saved).model_dump(), **extra}).status_code == 422


def test_real_default_api_has_no_fake_review_authority(db, saved):
    from app.main import app
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            path = f"/v1/communications/{saved.communication_id}/drafts/{saved.draft_id}/approve"
            result = client.post(path, headers={**HEADERS, "X-Actor-ID": MANAGER.actor_id}, json=command(saved).model_dump())
            assert result.status_code == 503 and result.json()["code"] == "REVIEW_AUTHORITY_UNAVAILABLE"
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
