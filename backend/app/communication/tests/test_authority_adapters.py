"""Current Core facts != trusted approval. Runtime grants intentionally unavailable.

Real SQLAlchemy reads and real HTTP dependency wiring are exercised below.
Positive action-policy/identity examples use TEST-ONLY fixtures through existing
Protocols; they are not production manager authentication or verified contacts.
"""

from datetime import timedelta
import importlib
from pathlib import Path
import sys
from types import ModuleType

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.communication.authority_adapters import RuntimeDraftAuthority, RuntimeRequestAuthority, RuntimeReviewAuthority
from app.communication.drafting import MessageDraftService
from app.communication.models import CommunicationRequestRecord, DraftReviewRecord, MessageDraftRecord
from app.communication.review import DraftReviewService
from app.communication.router import get_draft_authority, get_request_authority, get_review_authority
from app.communication.schemas import ApproveDraftRequest, CreateCommunicationRequest, PrepareDraftRequest
from app.communication.service import CommunicationRequestService
from app.communication.tests.test_requests import (
    db, authority, service, COMMAND, HEADERS, NOW, OWNER, TERMS, FixtureAuthority, create, expect_error,
)
from app.communication.tests.test_drafting import draft_authority, drafts, request_id, prepare, FixtureDraftAuthority
from app.communication.tests.test_review import MANAGER, FixtureReviewAuthority
from app.communication.tests.test_migration_persistence import migrated, prepare_graph, seed_core
from app.core.dependencies import RequestContext, get_db
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentProposalRecord, CommitmentRecord, OutboxEventRecord
from app.core.schemas import CommitmentTerms
from app.main import app


def core_basis(db, context=OWNER):
    return CommunicationRequestService(db).read_current_basis(context, COMMAND, NOW)


def test_current_core_basis_is_usable_facts_but_never_an_approval(db):
    basis = core_basis(db)
    assert basis.reference.tenant_id == "tenant_a" and basis.reference.proposal_version == 3
    assert basis.terms == CommitmentTerms.model_validate(TERMS)
    assert basis.customer_id == "customer_001" and basis.order_id == "order_001"
    assert basis.proposal_evidence_refs == ("ev_proposal_001",)
    assert not hasattr(basis, "approval_evidence_refs") and not hasattr(basis, "approval_expires_at")
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize("case,code", [
    ("cross_tenant", "SOURCE_EVENT_NOT_FOUND"),
    ("commitment_version", "COMMITMENT_VERSION_CONFLICT"),
    ("proposal_version", "STALE_PROPOSAL_VERSION"),
    ("superseded", "PROPOSAL_NOT_ELIGIBLE"),
    ("newer_proposal", "STALE_PROPOSAL_VERSION"),
    ("missing_terms", "APPROVED_TERMS_REQUIRED"),
    ("expired_deadline", "PROPOSED_DEADLINE_PASSED"),
    ("source_binding", "COMMITMENT_ID_MISMATCH"),
])
def test_core_reader_validates_actual_current_tenant_versions_and_terms(db, case, code):
    context = OWNER
    commitment = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    proposal = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    event = db.get(OutboxEventRecord, "evt_001")
    if case == "cross_tenant":
        context = RequestContext("tenant_b", OWNER.actor_id, OWNER.actor_role, "corr_other")
    elif case == "commitment_version":
        commitment.commitment_version += 1
    elif case == "proposal_version":
        proposal.proposal_version += 1
    elif case == "superseded":
        proposal.status = "SUPERSEDED"
    elif case == "newer_proposal":
        db.add(CommitmentProposalRecord(tenant_id="tenant_a", commitment_id="com_001", proposal_id="proposal_002",
            proposal_version=4, revised_terms=TERMS, status="ACTIVE", reason="new version",
            evidence_refs=["ev_new"], created_at=NOW, updated_at=NOW))
    elif case == "missing_terms":
        proposal.revised_terms = None
    elif case == "expired_deadline":
        proposal.revised_terms = {**TERMS, "deadline": (NOW - timedelta(seconds=1)).isoformat()}
    elif case == "source_binding":
        event.payload = {**event.payload, "commitment_id": "unrelated"}
    db.commit()
    expect_error(code, lambda: core_basis(db, context), 404 if case == "cross_tenant" else (422 if case in {"missing_terms", "source_binding"} else 409))


@pytest.mark.parametrize("migrated", ["sqlite", "postgresql"], indirect=True)
@pytest.mark.parametrize("changed", ["commitment_version", "proposal_status", "source_reference", "terms"])
def test_same_session_identity_map_never_substitutes_for_fresh_core_evidence(migrated, changed):
    engine, _ = migrated
    with Session(engine, expire_on_commit=False) as db:
        seed_core(db)
        assert_fresh_core_evidence(db, changed)


def assert_fresh_core_evidence(db, changed):
    # Keep strong references in an expire_on_commit=False session: a fresh SELECT
    # without populate_existing would retain these old ORM values after another writer.
    cached_commitment = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    cached_proposal = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    cached_source = db.get(OutboxEventRecord, "evt_001")
    assert core_basis(db).reference.commitment_version == 11
    db.commit()  # Release locks before the independent writer.
    with Session(db.get_bind()) as other:
        if changed == "commitment_version":
            other.get(CommitmentRecord, ("tenant_a", "com_001")).commitment_version = 12
        elif changed == "proposal_status":
            other.get(CommitmentProposalRecord, ("tenant_a", "proposal_001")).status = "SUPERSEDED"
        elif changed == "source_reference":
            row = other.get(OutboxEventRecord, "evt_001")
            row.payload = {**row.payload, "commitment_id": "another"}
        else:
            other.get(CommitmentProposalRecord, ("tenant_a", "proposal_001")).revised_terms = {**TERMS, "quantity": "101.125"}
        other.commit()
    assert cached_commitment.commitment_version == 11 and cached_proposal.status == "ACTIVE"
    assert cached_source.payload["commitment_id"] == "com_001"
    if changed == "terms":
        assert str(core_basis(db).terms.quantity) == "101.125"
    else:
        code = {"commitment_version": "COMMITMENT_VERSION_CONFLICT", "proposal_status": "PROPOSAL_NOT_ELIGIBLE",
                "source_reference": "COMMITMENT_ID_MISMATCH"}[changed]
        expect_error(code, lambda: core_basis(db), 422 if changed == "source_reference" else 409)


def test_runtime_dependencies_are_explicit_boundaries_not_fixtures():
    assert type(get_request_authority()) is RuntimeRequestAuthority
    assert type(get_draft_authority()) is RuntimeDraftAuthority
    assert type(get_review_authority()) is RuntimeReviewAuthority


@pytest.mark.parametrize("actor", ["user_owner_01", "user_manager_01", "user_staff_01"])
def test_demo_actor_roles_cannot_enable_production_permission(db, actor, monkeypatch):
    # Environment flags do not turn these missing capabilities into demo approval.
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "true")
    from app.core.dependencies import ACTOR_ROLES
    context = RequestContext("tenant_a", actor, ACTOR_ROLES[actor], "corr_demo")
    with pytest.raises(DomainError) as failure:
        DraftReviewService(db, get_draft_authority(), get_review_authority()).get(context, "absent", "absent", now=NOW)
    assert failure.value.status_code == 503 and failure.value.code == "REVIEW_AUTHORITY_UNAVAILABLE"
    assert "CORE_AUTHENTICATED_ACTOR_AND_TENANT_MEMBERSHIP" in failure.value.details["missing_capabilities"]


@pytest.mark.parametrize("operation,code", [
    ("request", "COMMUNICATION_AUTHORITY_UNAVAILABLE"),
    ("prepare", "DRAFT_REVALIDATION_UNAVAILABLE"),
    ("read_draft", "DRAFT_REVALIDATION_UNAVAILABLE"),
    ("read_review", "REVIEW_AUTHORITY_UNAVAILABLE"),
    ("approve", "REVIEW_AUTHORITY_UNAVAILABLE"),
])
def test_missing_authority_is_not_masked_as_missing_record_or_database_error(db, monkeypatch, operation, code):
    def no_database_lookup(*args, **kwargs):
        raise AssertionError("Authority preflight must precede object lookup")
    monkeypatch.setattr(db, "scalar", no_database_lookup)
    monkeypatch.setattr(db, "get", no_database_lookup)
    if operation == "request":
        call = lambda: CommunicationRequestService(db, get_request_authority()).create(OWNER, COMMAND, now=NOW)
    elif operation == "prepare":
        call = lambda: MessageDraftService(db, get_draft_authority()).prepare(OWNER, "absent", PrepareDraftRequest(), now=NOW)
    elif operation == "read_draft":
        call = lambda: MessageDraftService(db, get_draft_authority()).get(OWNER, "absent", "absent", now=NOW)
    elif operation == "read_review":
        call = lambda: DraftReviewService(db, get_draft_authority(), get_review_authority()).get(MANAGER, "absent", "absent", now=NOW)
    else:
        call = lambda: DraftReviewService(db, get_draft_authority(), get_review_authority()).approve(MANAGER, "absent", "absent",
            ApproveDraftRequest(request_key="unavailable_approval", expected_content_hash="a" * 64), now=NOW)
    expect_error(code, call, 503)


@pytest.mark.parametrize("payload", [
    {"approved": True},
    {"approval_state": "APPROVED", "approval_expires_at": (NOW + timedelta(days=2)).isoformat()},
    {"reviewer_role": "MANAGER", "evidence_refs": ["ev_claimed_approval"]},
])
def test_generic_core_audit_and_source_payload_cannot_be_promoted_to_approval(db, payload):
    event = db.get(OutboxEventRecord, "evt_001")
    event.payload = {**event.payload, **payload}
    db.add(AuditEventRecord(audit_id="audit_claim", tenant_id="tenant_a", commitment_id="com_001",
        event_type="claimed.approval", actor_id="user_manager_01", actor_role="MANAGER", dimension="recovery",
        previous_state=None, new_state=payload, evidence_refs=["ev_claimed_approval"], reason="not authenticated proof",
        correlation_id="corr_claim", occurred_at=NOW))
    db.commit()
    basis = core_basis(db)
    expect_error("COMMUNICATION_AUTHORITY_UNAVAILABLE", lambda: get_request_authority().authorize_request(
        db, OWNER, basis.reference, basis.terms), 503)
    assert db.scalar(select(func.count()).select_from(CommunicationRequestRecord)) == 0


@pytest.mark.parametrize("action", ["READ_DRAFT", "PREPARE_DRAFT"])
def test_synthetic_directory_and_untyped_channels_cannot_authorize_production(db, action, monkeypatch):
    # Load the actual P1 directory/schema files in a private test namespace.
    # app.context.__init__ mounts its entire OCR router, requiring optional numpy;
    # no such import or synthetic fallback is introduced in production P4.
    prefix = "_p4_test_p1_directory"
    package = ModuleType(prefix)
    package.__path__ = [str(Path(__file__).resolve().parents[2] / "context")]
    monkeypatch.setitem(sys.modules, prefix, package)
    try:
        directory = importlib.import_module(f"{prefix}.customer_directory")
        synthetic = directory.SyntheticCustomerDirectory()
        # Merely having a customer and a 'verified_channels' list is insufficient.
        assert synthetic.get_customer("synthetic_tenant_a", "cust_bk").verified_channels
        basis = core_basis(db)
        with pytest.raises(DomainError) as failure:
            get_draft_authority().revalidate_draft(db, OWNER, basis.reference, basis.terms,
                                                  communication_id="existing", action=action)
        assert failure.value.status_code == 503
        assert "P1_TYPED_IDENTITY_CHANNEL_CUSTOMER_BINDING_AND_VERIFICATION_EVIDENCE" in failure.value.details["missing_capabilities"]
    finally:
        for name in list(sys.modules):
            if name.startswith(prefix + "."):
                del sys.modules[name]


@pytest.mark.parametrize("change,code", [
    ({"approval_expires_at": NOW - timedelta(seconds=1)}, "APPROVAL_EXPIRED"),
    ({"proposal_expires_at": NOW - timedelta(seconds=1)}, "PROPOSAL_EXPIRED"),
    ({"approved_terms": {**TERMS, "quantity": "99"}}, "APPROVED_TERMS_MISMATCH"),
])
def test_test_only_authority_contract_still_rejects_expiry_and_wrong_terms(db, change, code):
    # This verifies the established Protocol checks after Core-reader extraction,
    # not a production approval reader that the current Core schema cannot supply.
    fixture = FixtureAuthority()
    fixture.overrides = change
    expect_error(code, lambda: CommunicationRequestService(db, fixture).create(OWNER, COMMAND, now=NOW))


@pytest.mark.parametrize("action", ["READ_DRAFT", "PREPARE_DRAFT"])
def test_every_draft_operation_revalidates_test_only_approval(db, service, request_id, action):
    fixture = FixtureDraftAuthority()
    drafts = MessageDraftService(db, fixture)
    saved = prepare(drafts, request_id)
    fixture.no_approval = True
    call = (lambda: drafts.get(OWNER, request_id, saved.draft_id, now=NOW)) if action == "READ_DRAFT" else (
        lambda: drafts.prepare(OWNER, request_id, PrepareDraftRequest(), now=NOW))
    expect_error("APPROVAL_EVIDENCE_REQUIRED", call, 403)


@pytest.mark.parametrize("overrides,code", [
    ({"recipient_identity_id": None}, "VERIFIED_RECIPIENT_REQUIRED"),
    ({"recipient_customer_id": "unrelated"}, "RECIPIENT_MISMATCH"),
    ({"channel_evidence_refs": []}, "AUTHORIZED_CHANNEL_REQUIRED"),
])
def test_test_only_identity_contract_does_not_weaken_current_validation(drafts, request_id, draft_authority, overrides, code):
    draft_authority.overrides = overrides
    expect_error(code, lambda: prepare(drafts, request_id), 403 if code == "RECIPIENT_MISMATCH" else 409)


def test_approved_history_is_not_reviewer_authorization(db, drafts, request_id, draft_authority):
    saved = prepare(drafts, request_id)
    fixture = FixtureReviewAuthority()
    service = DraftReviewService(db, draft_authority, fixture)
    first = service.approve(MANAGER, request_id, saved.draft_id,
        ApproveDraftRequest(request_key="test_only_review_key", expected_content_hash=saved.content_hash), now=NOW)
    assert first.effective_approval and not first.send_authorized
    expect_error("REVIEW_AUTHORITY_UNAVAILABLE", lambda: DraftReviewService(
        db, get_draft_authority(), get_review_authority()).get(MANAGER, request_id, saved.draft_id, now=NOW), 503)
    # Unknown original-reviewer status must not be falsely called VALID/REVOKED.
    row = db.get(DraftReviewRecord, ("tenant_a", first.decision.review_id))
    assert row.invalidated_at is None
    fixture.overrides = {"existing_review_status": "REVOKED"}
    invalidated = service.get(MANAGER, request_id, saved.draft_id, now=NOW)
    assert invalidated.review_state == "INVALIDATED" and not invalidated.effective_approval


def test_unavailable_runtime_authority_keeps_empty_summary_unavailable(db):
    result = MessageDraftService(db, get_draft_authority()).summary(OWNER, now=NOW)
    assert result.total == 0 and result.needs_attention == 0
    assert result.drafted is None and result.sent == 0
    assert result.unavailable_reasons["drafted"] == "DRAFT_REVALIDATION_UNAVAILABLE"


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
@pytest.mark.parametrize("populated", [False, True])
def test_postgresql_http_runtime_denies_missing_evidence_without_core_mutations(migrated, populated):
    engine, _ = migrated
    draft = None
    request = None
    with Session(engine) as db:
        if populated:
            request, draft, draft_authority = prepare_graph(db)
            DraftReviewService(db, draft_authority, FixtureReviewAuthority()).approve(
                MANAGER, request.communication_id, draft.draft_id,
                ApproveDraftRequest(request_key="fixture_existing_review", expected_content_hash=draft.content_hash), now=NOW)
        else:
            seed_core(db)
        tracked = (CommitmentRecord, CommitmentProposalRecord, AuditEventRecord, OutboxEventRecord,
                   CommunicationRequestRecord, MessageDraftRecord, DraftReviewRecord)
        before = {model.__tablename__: [tuple(row) for row in db.execute(select(model.__table__))] for model in tracked}
    def database():
        with Session(engine) as db:
            yield db
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    try:
        with TestClient(app) as client:
            assert client.post("/v1/communications/requests", json={"source_event_id": "evt_001"}).status_code == 400
            for actor in ("user_owner_01", "user_manager_01", "user_staff_01"):
                headers = {**HEADERS, "X-Actor-ID": actor, "X-Actor-Role": "MANAGER", "Authorization": "Bearer unverified"}
                for event_id in ("evt_001", "missing"):
                    response = client.post("/v1/communications/requests", headers=headers, json={"source_event_id": event_id})
                    assert response.status_code == 503 and response.json()["code"] == "COMMUNICATION_AUTHORITY_UNAVAILABLE"
                    assert response.json()["details"]["integration_status"] == "UNAVAILABLE"
            assert client.get("/v1/communications", headers=HEADERS).status_code == 200
            summary = client.get("/v1/communications/summary", headers=HEADERS)
            assert summary.status_code == 200
            result = summary.json()
            assert result["total"] == int(populated) and result["needs_attention"] == 0
            assert result["drafted"] is None and result["sent"] == 0
            assert result["unavailable_reasons"]["drafted"] == "DRAFT_REVALIDATION_UNAVAILABLE"
            if populated:
                assert client.get(f"/v1/communications/{request.communication_id}", headers=HEADERS).status_code == 200
                base = f"/v1/communications/{request.communication_id}"
                blocked = client.post(base + "/prepare", headers=HEADERS, json={})
                assert blocked.status_code == 503 and blocked.json()["code"] == "DRAFT_REVALIDATION_UNAVAILABLE"
                blocked = client.get(base + f"/drafts/{draft.draft_id}", headers=HEADERS)
                assert blocked.status_code == 503 and blocked.json()["code"] == "DRAFT_REVALIDATION_UNAVAILABLE"
                review = base + f"/drafts/{draft.draft_id}"
                command = {"request_key": "runtime_never_approved", "expected_content_hash": draft.content_hash}
                assert client.post(review + "/approve", json=command).status_code == 400
                assert client.post(review + "/approve", json=command,
                    headers={**HEADERS, "X-Actor-ID": "unknown_actor"}).status_code == 403
                # Client claims cannot be promoted to authenticated permissions.
                assert client.post(review + "/approve", headers=HEADERS,
                    json={**command, "approved": True, "actor_role": "MANAGER"}).status_code == 422
                for suffix in ("/approve", "/reject"):
                    response = client.post(review + suffix, headers=HEADERS,
                        json={"request_key": "runtime_never_approved", "expected_content_hash": draft.content_hash,
                              **({"reason": "Reject"} if suffix == "/reject" else {})})
                    assert response.status_code == 503 and response.json()["code"] == "REVIEW_AUTHORITY_UNAVAILABLE"
                response = client.get(review + "/review", headers=HEADERS)
                assert response.status_code == 503 and response.json()["code"] == "REVIEW_AUTHORITY_UNAVAILABLE"
                other = {**HEADERS, "X-Tenant-ID": "tenant_b"}
                assert client.get("/v1/communications", headers=other).json() == []
                assert client.get(base, headers=other).status_code == 404
            assert client.get("/health").status_code == 200
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
    with Session(engine) as db:
        after = {model.__tablename__: [tuple(row) for row in db.execute(select(model.__table__))] for model in tracked}
        assert after == before  # No new grant, audit, outbox/send or Core state mutation.
