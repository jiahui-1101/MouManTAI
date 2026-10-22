"""Database-backed summary tests; authority doubles remain inside test code."""

from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.communication.drafting import MessageDraftService
from app.communication.models import CommunicationRequestRecord, MessageDraftRecord
from app.communication.router import get_draft_service, router
from app.communication.schemas import RequestStatus
from app.communication.tests.test_drafting import (
    db, authority, service, request_id, draft_authority, drafts, prepare,
)
from app.communication.tests.test_requests import (
    NOW, TERMS, OWNER, HEADERS, create, count, expect_error,
)
from app.core.dependencies import RequestContext, get_db
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentProposalRecord, CommitmentRecord, OutboxEventRecord
from app.main import domain_error_handler


def summary(drafts, context=OWNER, **kwargs):
    return drafts.summary(context, now=NOW, **kwargs)


def test_empty_database_reports_real_zero_counts_but_no_sending_source(drafts):
    result = summary(drafts)
    assert (result.total, result.drafted, result.sent, result.needs_attention) == (0, 0, None, 0)
    assert result.unavailable_reasons == {"sent": "SENDING_RECORDS_UNAVAILABLE"}


def test_empty_database_without_authority_is_explicitly_unavailable(db):
    result = summary(MessageDraftService(db))
    assert result.total == result.needs_attention == 0
    assert result.drafted is None and result.sent is None
    assert result.unavailable_reasons["drafted"] == "DRAFT_REVALIDATION_UNAVAILABLE"


def test_ready_without_a_persisted_draft_is_not_drafted_or_an_exception(drafts, request_id):
    result = summary(drafts)
    assert result.total == 1 and result.drafted == 0 and result.needs_attention == 0


def test_summary_discovers_persisted_draft_from_another_session_without_frontend_cache(db, drafts, request_id, draft_authority):
    prepare(drafts, request_id)
    with Session(db.get_bind()) as other:
        result = summary(MessageDraftService(other, draft_authority))
    assert result.total == result.drafted == 1
    assert draft_authority.calls[-1] == (request_id, "READ_DRAFT")


def test_multiple_languages_and_variants_count_one_request(drafts, request_id):
    for language in ("en", "ms", "zh"):
        prepare(drafts, request_id, language)
    assert summary(drafts).drafted == 1


def test_missing_authority_never_returns_a_misleading_numeric_draft_count(db, drafts, request_id):
    prepare(drafts, request_id)
    result = summary(MessageDraftService(db))
    assert result.total == 1 and result.drafted is None
    assert result.unavailable_reasons["drafted"] == "DRAFT_REVALIDATION_UNAVAILABLE"


def test_expired_approval_does_not_count(drafts, request_id, draft_authority):
    prepare(drafts, request_id)
    draft_authority.overrides = {"approval_expires_at": NOW - timedelta(seconds=1)}
    assert summary(drafts).drafted == 0


def test_expired_proposal_does_not_count(drafts, request_id):
    prepare(drafts, request_id)
    result = drafts.summary(OWNER, now=NOW + timedelta(days=1, seconds=1))
    assert result.drafted == 0


def test_revoked_approval_does_not_count(drafts, request_id, draft_authority):
    prepare(drafts, request_id)
    draft_authority.no_approval = True
    assert summary(drafts).drafted == 0


def test_superseded_proposal_does_not_count(db, drafts, request_id):
    prepare(drafts, request_id)
    db.add(CommitmentProposalRecord(
        tenant_id="tenant_a", commitment_id="com_001", proposal_id="proposal_new",
        proposal_version=4, revised_terms=TERMS, status="ACTIVE", reason="New version",
        evidence_refs=["ev_new"], created_at=NOW, updated_at=NOW,
    ))
    db.commit()
    assert summary(drafts).drafted == 0


def test_commitment_version_changed_does_not_count(db, drafts, request_id):
    prepare(drafts, request_id)
    db.get(CommitmentRecord, ("tenant_a", "com_001")).commitment_version = 12
    db.commit()
    assert summary(drafts).drafted == 0


def test_same_version_material_change_does_not_count(db, drafts, request_id):
    prepare(drafts, request_id)
    db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001")).revised_terms = {**TERMS, "quantity": "999"}
    db.commit()
    assert summary(drafts).drafted == 0


def test_changed_authorization_does_not_count_old_drafts_but_new_valid_variant_does(drafts, draft_authority, request_id):
    prepare(drafts, request_id)
    draft_authority.overrides = {"channel": "MOCK_TELEGRAM"}
    assert summary(drafts).drafted == 0
    prepare(drafts, request_id)
    assert summary(drafts).drafted == 1


def test_tampered_preview_is_not_counted(db, drafts, request_id):
    value = prepare(drafts, request_id)
    row = db.get(MessageDraftRecord, ("tenant_a", value.draft_id))
    row.snapshot = {**row.snapshot, "body": "Unapproved free delivery"}
    db.commit()
    assert summary(drafts).drafted == 0


def test_read_policy_denial_makes_the_metric_unavailable_not_zero(drafts, draft_authority, request_id):
    prepare(drafts, request_id)
    draft_authority.denied_action = "READ_DRAFT"
    result = summary(drafts)
    assert result.total == 1 and result.drafted is None
    assert result.unavailable_reasons["drafted"] == "DRAFT_VALIDITY_UNAVAILABLE"


@pytest.mark.parametrize("status", [409, 503])
def test_unknown_adapter_failure_does_not_return_partial_or_zero_counts(drafts, request_id, draft_authority, status):
    prepare(drafts, request_id)
    def unavailable(*args, **kwargs):
        raise DomainError("ADAPTER_NOT_READY", "not usable", status_code=status)
    draft_authority.revalidate_draft = unavailable
    assert summary(drafts).drafted is None


def test_blocked_is_counted_once_without_turning_undrafted_into_attention(service, authority, drafts):
    authority.overrides = {"recipient_identity_id": None, "recipient_customer_id": None, "recipient_evidence_refs": []}
    blocked = create(service)
    assert blocked.request_status == "BLOCKED"
    result = summary(drafts)
    assert result.total == result.needs_attention == 1
    assert result.drafted == 0


@pytest.mark.parametrize("state", ["QUEUED", "SUBMITTED", "DELIVERY_UNKNOWN", "FAILED", "SENT", "DELIVERED"])
def test_snapshot_status_is_not_a_provider_confirmed_sending_source(db, service, drafts, state):
    request = create(service)
    row = db.get(CommunicationRequestRecord, ("tenant_a", request.communication_id))
    # A forged/future snapshot field is not a sending/delivery record. Existing
    # schema stays DRAFT-only; summary does not derive send proof from this JSON.
    row.snapshot = {**row.snapshot, "message_status": state}
    db.commit()
    result = summary(drafts)
    assert result.sent is None
    assert result.needs_attention == 0  # No real persisted delivery exception exists.
    assert result.unavailable_reasons["sent"] == "SENDING_RECORDS_UNAVAILABLE"


def test_tenant_isolation_for_requests_and_persisted_drafts(db, service, drafts, request_id):
    value = prepare(drafts, request_id)
    request = service.get(OWNER, request_id)
    other_ref = request.reference.model_copy(update={"tenant_id": "tenant_b"})
    other_request = request.model_copy(update={"reference": other_ref, "request_status": RequestStatus.BLOCKED})
    service.repository.add(other_request)
    other_draft = value.model_copy(update={"tenant_id": "tenant_b", "reference": other_ref})
    drafts.repository.add(other_draft)
    db.commit()
    first = summary(drafts)
    assert (first.total, first.drafted, first.needs_attention) == (1, 1, 0)
    other_context = RequestContext("tenant_b", OWNER.actor_id, OWNER.actor_role, "corr_other")
    second = summary(drafts, other_context)
    assert (second.total, second.drafted, second.needs_attention) == (1, 0, 1)


def test_summary_never_creates_draft_audit_outbox_or_core_transitions(db, drafts, request_id):
    prepare(drafts, request_id)
    before = [count(db, model) for model in (MessageDraftRecord, AuditEventRecord, OutboxEventRecord)]
    core = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    version, state = core.commitment_version, core.agreement_state
    summary(drafts)
    assert before == [count(db, model) for model in (MessageDraftRecord, AuditEventRecord, OutboxEventRecord)]
    assert (core.commitment_version, core.agreement_state) == (version, state)


def test_missing_draft_migration_preserves_total_and_marks_drafted_unavailable(db, drafts, request_id):
    MessageDraftRecord.__table__.drop(db.get_bind())
    result = summary(drafts)
    assert result.total == 1 and result.drafted is None
    assert result.unavailable_reasons["drafted"] == "DRAFT_STORAGE_UNAVAILABLE"


def test_missing_request_migration_returns_clear_503(db, drafts):
    CommunicationRequestRecord.__table__.drop(db.get_bind())
    expect_error("COMMUNICATION_SUMMARY_UNAVAILABLE", lambda: summary(drafts), 503)


def test_malformed_saved_draft_is_unavailable_instead_of_a_guessed_zero(db, drafts, request_id):
    value = prepare(drafts, request_id)
    row = db.get(MessageDraftRecord, ("tenant_a", value.draft_id))
    row.snapshot = {**row.snapshot, "language": "unsupported"}
    db.commit()
    assert summary(drafts).drafted is None


def test_unknown_actor_is_not_allowed_to_read_summary(db):
    actor = RequestContext("tenant_a", "unknown", "OWNER", "corr")
    expect_error("FORBIDDEN", lambda: summary(MessageDraftService(db), actor), 403)


def test_api_static_summary_route_precedes_dynamic_detail_and_uses_current_tenant(db, request_id):
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.get("/v1/communications/summary", headers=HEADERS)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["tenant_id"] == "tenant_a"
        assert result["total"] == 1 and result["drafted"] is None and result["sent"] is None
        assert "body" not in result and "approval_evidence_refs" not in result
        other = client.get("/v1/communications/summary", headers={**HEADERS, "X-Tenant-ID": "tenant_b"})
        assert other.status_code == 200 and other.json()["total"] == 0


def test_api_with_trusted_test_adapter_reports_persisted_draft(db, drafts, request_id):
    prepare(drafts, request_id)
    app = FastAPI()
    app.include_router(router)
    original = drafts.summary
    drafts.summary = lambda context: original(context, now=NOW)
    app.dependency_overrides[get_draft_service] = lambda: drafts
    with TestClient(app) as client:
        result = client.get("/v1/communications/summary", headers=HEADERS)
        assert result.status_code == 200 and result.json()["drafted"] == 1
