"""Commit 03 tests. All approval/identity doubles are test-only."""

from datetime import timedelta
import hashlib
import json

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.communication import templates
from app.communication.drafting import MessageDraftService
from app.communication.models import MessageDraftRecord
from app.communication.router import get_draft_service, router
from app.communication.schemas import PrepareDraftRequest
from app.communication.tests.test_requests import (
    db, authority, service, FixtureAuthority, OWNER, NOW, TERMS, HEADERS, create, count, expect_error,
)
from app.core.dependencies import RequestContext, get_db
from app.core.errors import DomainError
from app.core.schemas import CommitmentTerms, CommunicationChannel
from app.core.models import AuditEventRecord, CommitmentProposalRecord, CommitmentRecord, OutboxEventRecord
from app.main import domain_error_handler, validation_exception_handler


class FixtureDraftAuthority(FixtureAuthority):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.denied_action = None

    def revalidate_draft(self, db, context, reference, terms, *, communication_id, action):
        self.calls.append((communication_id, action))
        if action == self.denied_action:
            raise DomainError("FORBIDDEN", "Fixture action policy denies access", status_code=403)
        return self.authorize_request(db, context, reference, terms)


@pytest.fixture
def request_id(service):
    return create(service).communication_id


@pytest.fixture
def draft_authority():
    return FixtureDraftAuthority()


@pytest.fixture
def drafts(db, draft_authority):
    return MessageDraftService(db, draft_authority)


def prepare(drafts, request_id, language="en", **kwargs):
    return drafts.prepare(OWNER, request_id, PrepareDraftRequest(language=language, **kwargs), now=NOW)


@pytest.mark.parametrize("language,greeting", [
    ("en", "Dear Customer,"), ("ms", "Pelanggan yang dihormati,"), ("zh", "尊敬的客户："),
])
def test_three_languages_keep_exact_terms_versions_hashes_and_persistence(
    db, drafts, request_id, language, greeting,
):
    draft = prepare(drafts, request_id, language)
    assert draft.body.startswith(greeting)
    assert "100.125 pcs" in draft.body
    assert "BURGER" in draft.body
    assert draft.approved_terms.deadline.isoformat() in draft.body
    assert "order_001" in draft.body and "com_001" in draft.body and "proposal_001" in draft.body
    assert request_id in draft.body
    assert draft.reference.proposal_version == 3
    assert draft.reference.plan_version == 2
    assert draft.reference.commitment_version == 11
    assert draft.status == "DRAFT" and draft.send_authorized is False
    expected = hashlib.sha256(json.dumps(
        {"body": draft.body, "subject": draft.subject}, sort_keys=True,
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    assert draft.content_hash == expected
    assert drafts.get(OWNER, request_id, draft.draft_id, now=NOW) == draft
    assert count(db, MessageDraftRecord) == 1


def test_english_template_has_no_invented_promises(drafts, request_id):
    body = prepare(drafts, request_id).body
    assert "proposed revised terms" in body
    assert "acceptance is pending" in body
    assert "Quantity: 100.125 pcs" in body
    assert "Proposal: proposal_001 (Version: 3)" in body
    assert "Please explicitly accept, reject, or request a change" in body
    assert not any(word in body.lower() for word in (
        "free delivery", "refund", "discount", "compensation", "fulfilled", "already delivered",
    ))


@pytest.mark.parametrize("language", ["en", "ms", "zh"])
def test_special_instructions_preserved_as_labelled_exact_data(db, service, drafts, language):
    instructions = "Keep separate: no peanuts.\n包装必须密封；不得替换产品。"
    row = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    row.revised_terms = {**TERMS, "special_instructions": instructions}
    db.commit()
    communication_id = create(service).communication_id
    draft = prepare(drafts, communication_id, language)
    assert draft.approved_terms.special_instructions == instructions
    assert json.dumps(instructions, ensure_ascii=False) in draft.body


def test_utc_offset_and_decimal_precision_are_not_lost(db, service, drafts):
    row = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    row.revised_terms = {**TERMS, "quantity": "100.123456789123456789",
                         "deadline": "2026-10-26T17:45:00+08:00"}
    db.commit()
    draft = prepare(drafts, create(service).communication_id)
    assert "100.123456789123456789 pcs" in draft.body
    assert "2026-10-26T17:45:00+08:00" in draft.body


@pytest.mark.parametrize("channel,has_subject", [
    ("MOCK_EMAIL", True), ("MOCK_TELEGRAM", False), ("MOCK_WHATSAPP", False),
])
def test_provider_independent_structure_and_email_subject(drafts, draft_authority, request_id, channel, has_subject):
    draft_authority.overrides = {"channel": channel}
    draft = prepare(drafts, request_id)
    assert (draft.subject is not None) == has_subject
    assert draft.channel == channel
    assert "100.125 pcs" in draft.body
    assert "api.telegram" not in draft.body and "graph.facebook" not in draft.body


def test_duplicate_prepare_revalidates_but_does_not_duplicate_audit_or_draft(db, drafts, draft_authority, request_id):
    first = prepare(drafts, request_id)
    audit_count, event_count = count(db, AuditEventRecord), count(db, OutboxEventRecord)
    assert prepare(drafts, request_id) == first
    assert draft_authority.calls == [(request_id, "PREPARE_DRAFT")] * 2
    assert count(db, MessageDraftRecord) == 1
    assert count(db, AuditEventRecord) == audit_count
    assert count(db, OutboxEventRecord) == event_count


def test_different_languages_and_channels_are_distinct_variants(db, drafts, draft_authority, request_id):
    en = prepare(drafts, request_id, "en")
    ms = prepare(drafts, request_id, "ms")
    draft_authority.overrides = {"channel": "MOCK_TELEGRAM"}
    telegram = prepare(drafts, request_id)
    assert len({en.draft_id, ms.draft_id, telegram.draft_id}) == 3
    assert count(db, MessageDraftRecord) == 3
    expect_error("DRAFT_REVALIDATION_REQUIRED", lambda: drafts.get(OWNER, request_id, en.draft_id, now=NOW))


def test_new_template_version_creates_new_variant_and_blocks_old_preview(
    drafts, request_id, monkeypatch,
):
    old = prepare(drafts, request_id)
    monkeypatch.setattr(templates, "TEMPLATE_VERSION", 2)
    fresh = prepare(drafts, request_id)
    assert fresh.template_version == 2 and fresh.draft_id != old.draft_id
    expect_error("DRAFT_REVALIDATION_REQUIRED", lambda: drafts.get(OWNER, request_id, old.draft_id, now=NOW))


def test_new_approval_evidence_is_not_overwritten_into_old_draft(drafts, draft_authority, request_id):
    old = prepare(drafts, request_id)
    draft_authority.overrides = {"approval_evidence_refs": ["ev_reapproved_002"]}
    fresh = prepare(drafts, request_id)
    assert fresh.draft_id != old.draft_id
    assert fresh.approval_evidence_refs == ["ev_reapproved_002"]
    expect_error("DRAFT_REVALIDATION_REQUIRED", lambda: drafts.get(OWNER, request_id, old.draft_id, now=NOW))


@pytest.mark.parametrize("method", ["prepare", "get"])
def test_revoked_approval_blocks_both_new_draft_and_stored_preview(
    drafts, draft_authority, request_id, method,
):
    old = prepare(drafts, request_id)
    draft_authority.no_approval = True
    operation = (lambda: prepare(drafts, request_id)) if method == "prepare" else (
        lambda: drafts.get(OWNER, request_id, old.draft_id, now=NOW)
    )
    expect_error("APPROVAL_EVIDENCE_REQUIRED", operation, 403)


@pytest.mark.parametrize("field,code", [
    ("approval_expires_at", "APPROVAL_EXPIRED"), ("proposal_expires_at", "PROPOSAL_EXPIRED"),
])
def test_expiration_blocks_prepare_and_retrieval(drafts, draft_authority, request_id, field, code):
    old = prepare(drafts, request_id)
    draft_authority.overrides = {field: NOW}
    expect_error(code, lambda: prepare(drafts, request_id))
    expect_error(code, lambda: drafts.get(OWNER, request_id, old.draft_id, now=NOW))


@pytest.mark.parametrize("field,value,code", [
    ("status", "SUPERSEDED", "PROPOSAL_NOT_ELIGIBLE"),
    ("status", "REJECTED", "PROPOSAL_NOT_ELIGIBLE"),
    ("proposal_version", 4, "STALE_PROPOSAL_VERSION"),
    ("commitment_id", "other", "COMMITMENT_ID_MISMATCH"),
    ("revised_terms", None, "APPROVED_TERMS_REQUIRED"),
    ("revised_terms", {**TERMS, "price": "999"}, "INVALID_PROPOSAL_TERMS"),
    ("revised_terms", {key: value for key, value in TERMS.items() if key != "quantity"}, "INVALID_PROPOSAL_TERMS"),
    ("revised_terms", {key: value for key, value in TERMS.items() if key != "deadline"}, "INVALID_PROPOSAL_TERMS"),
    ("revised_terms", {**TERMS, "deadline": None}, "INVALID_PROPOSAL_TERMS"),
])
def test_current_proposal_is_revalidated_not_trusted_from_snapshot(db, drafts, request_id, field, value, code):
    row = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    setattr(row, field, value)
    db.commit()
    expect_error(code, lambda: prepare(drafts, request_id))
    assert count(db, MessageDraftRecord) == 0


def test_newer_proposal_blocks_old_version_prepare(db, drafts, request_id):
    db.add(CommitmentProposalRecord(
        tenant_id="tenant_a", commitment_id="com_001", proposal_id="proposal_004",
        proposal_version=4, revised_terms=TERMS, status="ACTIVE", reason="new revision",
        evidence_refs=["ev_new"], created_at=NOW, updated_at=NOW,
    ))
    db.commit()
    expect_error("STALE_PROPOSAL_VERSION", lambda: prepare(drafts, request_id))


def test_changed_commitment_version_blocks_existing_draft_retrieval(db, drafts, request_id):
    old = prepare(drafts, request_id)
    db.get(CommitmentRecord, ("tenant_a", "com_001")).commitment_version = 12
    db.commit()
    expect_error("COMMITMENT_VERSION_CONFLICT", lambda: drafts.get(OWNER, request_id, old.draft_id, now=NOW))


def test_same_proposal_version_cannot_silently_change_terms(db, drafts, request_id):
    row = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    row.revised_terms = {**TERMS, "quantity": "999"}
    db.commit()
    expect_error("APPROVED_TERMS_MISMATCH", lambda: prepare(drafts, request_id))


@pytest.mark.parametrize("overrides,code", [
    ({"recipient_identity_id": None}, "VERIFIED_RECIPIENT_REQUIRED"),
    ({"channel": "UNKNOWN"}, "AUTHORIZED_CHANNEL_REQUIRED"),
    ({"proposal_expires_at": None}, "PROPOSAL_EXPIRY_REQUIRED"),
    ({"approved_terms": {**TERMS, "quantity": "999"}}, "APPROVED_TERMS_MISMATCH"),
])
def test_current_authority_must_be_complete(drafts, draft_authority, request_id, overrides, code):
    draft_authority.overrides = overrides
    expect_error(code, lambda: prepare(drafts, request_id))


def test_previously_blocked_request_requires_complete_fresh_authority(service, authority, drafts):
    authority.overrides = {"recipient_identity_id": None}
    blocked = create(service)
    assert blocked.request_status == "BLOCKED"
    assert prepare(drafts, blocked.communication_id).status == "DRAFT"
    assert service.get(OWNER, blocked.communication_id).request_status == "BLOCKED"


def test_no_trusted_revalidation_never_falls_back_to_old_approval(db, drafts, request_id):
    old = prepare(drafts, request_id)
    unwired = MessageDraftService(db)
    expect_error("DRAFT_REVALIDATION_UNAVAILABLE", lambda: prepare(unwired, request_id), 503)
    expect_error("DRAFT_REVALIDATION_UNAVAILABLE", lambda: unwired.get(OWNER, request_id, old.draft_id, now=NOW), 503)


def test_cross_tenant_and_wrong_request_cannot_read_draft(drafts, request_id):
    old = prepare(drafts, request_id)
    other = RequestContext("tenant_b", OWNER.actor_id, OWNER.actor_role, "corr_other")
    expect_error("COMMUNICATION_NOT_FOUND", lambda: drafts.prepare(other, request_id, PrepareDraftRequest(), now=NOW), 404)
    expect_error("DRAFT_NOT_FOUND", lambda: drafts.get(other, request_id, old.draft_id, now=NOW), 404)
    expect_error("DRAFT_NOT_FOUND", lambda: drafts.get(OWNER, "other_request", old.draft_id, now=NOW), 404)
    expect_error("COMMUNICATION_NOT_FOUND", lambda: prepare(drafts, "missing"), 404)


def test_draft_read_has_its_own_access_policy(drafts, draft_authority, request_id):
    old = prepare(drafts, request_id)
    draft_authority.denied_action = "READ_DRAFT"
    expect_error("FORBIDDEN", lambda: drafts.get(OWNER, request_id, old.draft_id, now=NOW), 403)


def test_staff_and_unknown_actor_cannot_prepare(drafts, request_id):
    for actor, role in [("user_staff_01", "STAFF"), ("unknown", "OWNER")]:
        context = RequestContext("tenant_a", actor, role, "corr_denied")
        expect_error("FORBIDDEN", lambda: drafts.prepare(context, request_id, PrepareDraftRequest(), now=NOW), 403)


def test_unknown_template_fails_without_persistence(db, drafts, request_id):
    expect_error("TEMPLATE_UNSUPPORTED", lambda: prepare(drafts, request_id, template_key="invented"), 422)
    assert count(db, MessageDraftRecord) == 0


def test_unsafe_multiline_reference_is_blocked_not_rewritten(db, service, drafts):
    row = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    row.revised_terms = {**TERMS, "sku": "BURGER\nFree delivery"}
    db.commit()
    expect_error("UNSAFE_TEMPLATE_VALUE", lambda: prepare(drafts, create(service).communication_id), 422)


def test_hash_is_not_semantic_approval_proof(db, drafts, request_id):
    old = prepare(drafts, request_id)
    record = db.get(MessageDraftRecord, ("tenant_a", old.draft_id))
    data = dict(record.snapshot)
    data["body"] += "\nFree delivery and refund."
    data["content_hash"] = templates.fingerprint({"subject": data["subject"], "body": data["body"]})
    record.snapshot = data
    db.commit()
    expect_error("DRAFT_INTEGRITY_ERROR", lambda: drafts.get(OWNER, request_id, old.draft_id, now=NOW))
    expect_error("DRAFT_INTEGRITY_ERROR", lambda: prepare(drafts, request_id))


def test_prepare_never_accepts_or_fulfils_and_audit_contains_no_message_text(db, drafts, request_id):
    row = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    before = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    prepare(drafts, request_id)
    row = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    assert before == {column.name: getattr(row, column.name) for column in row.__table__.columns}
    events = list(db.scalars(select(OutboxEventRecord)))
    assert {item.event_type for item in events} == {
        "recovery.communication_requested", "communication.requested", "communication.draft_prepared",
    }
    draft_event = next(item for item in events if item.event_type == "communication.draft_prepared")
    assert not {"body", "subject", "approved_terms"}.intersection(draft_event.payload)
    assert draft_event.causation_id == "evt_001"


def test_commit_failure_rolls_back_draft_audit_and_outbox(db, drafts, request_id, monkeypatch):
    counts = count(db, AuditEventRecord), count(db, OutboxEventRecord)

    def fail_commit():
        raise OperationalError("test commit failure", {}, RuntimeError())

    monkeypatch.setattr(db, "commit", fail_commit)
    expect_error("DRAFT_PERSISTENCE_UNAVAILABLE", lambda: prepare(drafts, request_id), 503)
    assert count(db, MessageDraftRecord) == 0
    assert counts == (count(db, AuditEventRecord), count(db, OutboxEventRecord))


def test_unique_constraint_and_conflict_retry(db, drafts, request_id, monkeypatch):
    original = drafts.repository.add
    calls = []

    def conflict_once(candidate):
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("test unique conflict", {}, RuntimeError())
        return original(candidate)

    monkeypatch.setattr(drafts.repository, "add", conflict_once)
    draft = prepare(drafts, request_id)
    assert len(calls) == 2
    db.add(MessageDraftRecord(
        tenant_id=draft.tenant_id, draft_id="other", communication_id=request_id,
        validation_hash=draft.validation_hash, snapshot=draft.model_dump(mode="json"), created_at=NOW,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert count(db, MessageDraftRecord) == 1


def test_missing_draft_table_is_not_reported_as_success(db, drafts, request_id):
    MessageDraftRecord.__table__.drop(db.get_bind())
    expect_error("DRAFT_PERSISTENCE_UNAVAILABLE", lambda: prepare(drafts, request_id), 503)
    expect_error("DRAFT_PERSISTENCE_UNAVAILABLE", lambda: drafts.get(OWNER, request_id, "missing", now=NOW), 503)


def test_postgresql_draft_metadata_compiles():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable
    ddl = str(CreateTable(MessageDraftRecord.__table__).compile(dialect=postgresql.dialect()))
    assert "uq_communication_draft_variant" in ddl and "fk_communication_draft_request" in ddl


def test_future_material_fields_cannot_be_silently_omitted_by_template():
    class FutureTerms(CommitmentTerms):
        price: str

    terms = FutureTerms(**TERMS, price="999.00")
    expect_error("UNSUPPORTED_MATERIAL_TERMS", lambda: templates.render_message(
        language="en", template_key="delivery_change", channel=CommunicationChannel.MOCK_TELEGRAM,
        order_id="order", commitment_id="commitment", proposal_id="proposal", proposal_version=3,
        communication_id="communication", terms=terms,
    ), 422)


def test_template_does_not_invent_missing_required_term():
    # Defensive renderer boundary; normal Core validation rejects this much earlier.
    validated = CommitmentTerms.model_validate(TERMS).model_dump()
    terms = CommitmentTerms.model_construct(**{**validated, "quantity": None})
    expect_error("REQUIRED_DRAFT_TERMS_MISSING", lambda: templates.render_message(
        language="en", template_key="delivery_change", channel=CommunicationChannel.MOCK_WHATSAPP,
        order_id="order", commitment_id="commitment", proposal_id="proposal", proposal_version=3,
        communication_id="communication", terms=terms,
    ), 422)


@pytest.fixture
def api(drafts):
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    original_prepare, original_get = drafts.prepare, drafts.get
    drafts.prepare = lambda context, request, command: original_prepare(context, request, command, now=NOW)
    drafts.get = lambda context, request, draft: original_get(context, request, draft, now=NOW)
    app.dependency_overrides[get_draft_service] = lambda: drafts
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("language", ["en", "ms", "zh"])
def test_api_prepare_retrieve_and_idempotency(api, request_id, language):
    path = f"/v1/communications/{request_id}/prepare"
    response = api.post(path, json={"language": language}, headers=HEADERS)
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["language"] == language and draft["send_authorized"] is False
    assert api.post(path, json={"language": language}, headers=HEADERS).json() == draft
    get_path = f"/v1/communications/{request_id}/drafts/{draft['draft_id']}"
    assert api.get(get_path, headers=HEADERS).json() == draft
    assert api.get(get_path, headers={**HEADERS, "X-Tenant-ID": "tenant_b"}).status_code == 404


@pytest.mark.parametrize("data", [
    {"language": "fr"}, {"approved": True}, {"approved_terms": TERMS},
    {"recipient_identity_id": "invented"}, {"proposal_version": 999}, {"body": "Free delivery"},
])
def test_api_blocks_unapproved_client_content(api, request_id, data):
    response = api.post(f"/v1/communications/{request_id}/prepare", json=data, headers=HEADERS)
    assert response.status_code == 422


def test_default_api_revalidation_is_fail_closed(db, request_id):
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.post(f"/v1/communications/{request_id}/prepare", json={}, headers=HEADERS)
        assert response.status_code == 503
        assert response.json()["code"] == "DRAFT_REVALIDATION_UNAVAILABLE"
