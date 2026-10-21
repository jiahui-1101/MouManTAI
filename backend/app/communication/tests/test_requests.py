"""SQLite service/API tests. FixtureAuthority is test-only, not a shipped P5 adapter."""

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.communication.models import CommunicationRequestRecord, CommunicationSourceEventRecord
from app.communication.router import get_request_authority, get_service, router
from app.communication.schemas import CreateCommunicationRequest, RequestAuthorization, RequestStatus
from app.communication.service import CommunicationRequestService
from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentProposalRecord, CommitmentRecord, OutboxEventRecord
from app.db.base import Base
from app.main import domain_error_handler, validation_exception_handler


NOW = datetime(2026, 10, 21, 10, tzinfo=timezone.utc)
TERMS = {"sku": "BURGER", "quantity": "100.125", "unit": "pcs",
         "deadline": (NOW + timedelta(days=5)).isoformat()}
COMMAND = CreateCommunicationRequest(source_event_id="evt_001")
OWNER = RequestContext("tenant_a", "user_owner_01", "OWNER", "corr_http_001")


class FixtureAuthority:
    """Synthetic policy/approval/identity fixture explicitly limited to tests."""

    def __init__(self):
        self.overrides = {}
        self.no_approval = False

    def authorize_request(self, db, context, reference, terms):
        if context.actor_role not in {"OWNER", "MANAGER"}:
            raise DomainError("FORBIDDEN", "Fixture creation policy denies actor", status_code=403)
        if self.no_approval:
            return None
        return RequestAuthorization(**{
            "reference": reference, "approved_terms": terms,
            "approval_evidence_refs": ["ev_approval_001"],
            "approval_expires_at": NOW + timedelta(days=2),
            "proposal_expires_at": NOW + timedelta(days=1),
            "recipient_identity_id": "identity_001", "recipient_customer_id": "customer_001",
            "recipient_evidence_refs": ["ev_identity_001"], "channel": "MOCK_EMAIL",
            "channel_evidence_refs": ["ev_channel_consent_001"], **self.overrides,
        })


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'requests.sqlite'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)  # Test-only; production never calls create_all.
    with Session(engine, expire_on_commit=False) as session:
        session.add(CommitmentRecord(
            tenant_id="tenant_a", commitment_id="com_001", order_id="order_001",
            customer_id="customer_001", terms=TERMS, agreement_state="OFFERED",
            feasibility_state="INFEASIBLE", risk_state="AT_RISK", recovery_state="EXECUTING",
            fulfilment_state="NOT_STARTED", commitment_version=11,
            evidence_refs=["ev_original"], updated_at=NOW,
        ))
        session.add(CommitmentProposalRecord(
            tenant_id="tenant_a", commitment_id="com_001", proposal_id="proposal_001",
            proposal_version=3, revised_terms=TERMS, status="ACTIVE", reason="Recovery offer",
            evidence_refs=["ev_proposal_001"], created_at=NOW, updated_at=NOW,
        ))
        session.add(source())
        session.commit()
        yield session
    engine.dispose()


def source(event_id="evt_001", tenant="tenant_a", **payload_changes):
    return OutboxEventRecord(
        event_id=event_id, tenant_id=tenant, event_type="recovery.communication_requested",
        commitment_id="com_001", commitment_version=11, correlation_id="corr_recovery_001",
        causation_id="evt_plan_001", occurred_at=NOW, attempts=0, status="PENDING",
        payload={"commitment_id": "com_001", "plan_id": "plan_001", "plan_version": 2,
                 "proposal_id": "proposal_001", "proposal_version": 3, **payload_changes},
    )


@pytest.fixture
def authority():
    return FixtureAuthority()


@pytest.fixture
def service(db, authority):
    return CommunicationRequestService(db, authority)


def create(service, command=COMMAND):
    return service.create(OWNER, command, now=NOW)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def expect_error(code, operation, status=None):
    with pytest.raises(DomainError) as caught:
        operation()
    assert caught.value.code == code
    if status is not None:
        assert caught.value.status_code == status


def test_create_persists_exact_snapshot_audit_outbox_and_leaves_core_unchanged(db, service):
    before = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    core_before = {column.name: getattr(before, column.name) for column in before.__table__.columns}
    db.rollback()
    view = create(service)
    assert view.request_status == "READY_FOR_DRAFTING"
    assert view.blocking_reasons == []
    assert view.message_status == "DRAFT"
    assert str(view.proposed_terms.quantity) == "100.125"
    assert (view.reference.plan_version, view.reference.proposal_version,
            view.reference.commitment_version) == (2, 3, 11)
    assert view.approval_evidence_refs == ["ev_approval_001"]
    assert view.recipient_evidence_refs == ["ev_identity_001"]
    assert view.channel_evidence_refs == ["ev_channel_consent_001"]
    assert service.get(OWNER, view.communication_id) == view
    assert count(db, CommunicationRequestRecord) == count(db, CommunicationSourceEventRecord) == 1
    audit = db.scalar(select(AuditEventRecord))
    assert audit.actor_id == OWNER.actor_id
    assert audit.causation_id == "evt_001"
    assert audit.correlation_id == "corr_recovery_001"
    emitted = db.scalar(select(OutboxEventRecord).where(
        OutboxEventRecord.event_type == "communication.requested",
    ))
    assert emitted.payload["request_status"] == "READY_FOR_DRAFTING"
    assert "proposed_terms" not in emitted.payload
    current = db.get(CommitmentRecord, ("tenant_a", "com_001"))
    assert core_before == {column.name: getattr(current, column.name) for column in current.__table__.columns}
    # A new session reads the same persisted request, without any Python dictionary cache.
    with Session(db.get_bind()) as other:
        assert CommunicationRequestService(other).get(OWNER, view.communication_id) == view


def test_duplicate_event_is_one_logical_request_and_one_audit(db, service):
    first = create(service)
    assert create(service) == first
    assert count(db, CommunicationRequestRecord) == 1
    assert count(db, CommunicationSourceEventRecord) == 1
    assert count(db, AuditEventRecord) == 1
    assert count(db, OutboxEventRecord) == 2


def test_distinct_events_for_same_proposal_deduplicate_and_preserve_both_sources(db, service):
    first = create(service)
    db.add(source("evt_002"))
    db.commit()
    assert create(service, CreateCommunicationRequest(source_event_id="evt_002")) == first
    assert count(db, CommunicationRequestRecord) == 1
    assert count(db, CommunicationSourceEventRecord) == 2
    assert count(db, AuditEventRecord) == 1


def test_rebinding_proposal_to_other_plan_is_conflict(db, service):
    create(service)
    db.add(source("evt_002", plan_version=4))
    db.commit()
    expect_error("IDEMPOTENCY_CONFLICT", lambda: create(
        service, CreateCommunicationRequest(source_event_id="evt_002"),
    ))
    assert count(db, CommunicationSourceEventRecord) == 1


@pytest.mark.parametrize("changes,code", [
    ({"status": "SUPERSEDED"}, "PROPOSAL_NOT_ELIGIBLE"),
    ({"status": "REJECTED"}, "PROPOSAL_NOT_ELIGIBLE"),
    ({"status": "ACCEPTED"}, "PROPOSAL_NOT_ELIGIBLE"),
    ({"proposal_version": 4}, "STALE_PROPOSAL_VERSION"),
    ({"commitment_id": "other"}, "COMMITMENT_ID_MISMATCH"),
    ({"revised_terms": None}, "APPROVED_TERMS_REQUIRED"),
    ({"revised_terms": {**TERMS, "quantity": "-1"}}, "INVALID_PROPOSAL_TERMS"),
    ({"revised_terms": {**TERMS, "deadline": NOW.isoformat()}}, "PROPOSED_DEADLINE_PASSED"),
])
def test_ineligible_proposal(db, service, changes, code):
    proposal = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    for key, value in changes.items():
        setattr(proposal, key, value)
    db.commit()
    expect_error(code, lambda: create(service))
    assert count(db, CommunicationRequestRecord) == 0


def test_missing_or_cross_tenant_proposal_is_not_found(db, service):
    proposal = db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001"))
    proposal.tenant_id = "tenant_b"
    db.commit()
    expect_error("PROPOSAL_NOT_FOUND", lambda: create(service), 404)


@pytest.mark.parametrize("version", [3, 4])
def test_same_or_newer_proposal_version_blocks_stale_or_ambiguous_source(db, service, version):
    db.add(CommitmentProposalRecord(
        tenant_id="tenant_a", commitment_id="com_001", proposal_id="proposal_other",
        proposal_version=version, revised_terms=TERMS, status="ACTIVE", reason="new offer",
        evidence_refs=["ev_new"], created_at=NOW, updated_at=NOW,
    ))
    db.commit()
    expect_error("AMBIGUOUS_PROPOSAL_VERSION" if version == 3 else "STALE_PROPOSAL_VERSION",
                 lambda: create(service))


def test_stale_commitment_is_rejected(db, service):
    db.get(CommitmentRecord, ("tenant_a", "com_001")).commitment_version = 12
    db.commit()
    expect_error("COMMITMENT_VERSION_CONFLICT", lambda: create(service))


def test_non_offered_commitment_is_rejected(db, service):
    db.get(CommitmentRecord, ("tenant_a", "com_001")).agreement_state = "CONFIRMED"
    db.commit()
    expect_error("PROPOSAL_NOT_ELIGIBLE", lambda: create(service))


def test_unknown_source_event_fails(db, service):
    expect_error("SOURCE_EVENT_NOT_FOUND", lambda: create(
        service, CreateCommunicationRequest(source_event_id="missing"),
    ), 404)


def test_missing_commitment_is_not_inferred_from_proposal(db, service):
    db.delete(db.get(CommitmentRecord, ("tenant_a", "com_001")))
    db.commit()
    expect_error("COMMITMENT_NOT_FOUND", lambda: create(service), 404)


@pytest.mark.parametrize("kind", ["wrong_type", "invalid_reference"])
def test_invalid_persisted_source_does_not_create_a_request(db, service, kind):
    stored = db.get(OutboxEventRecord, "evt_001")
    if kind == "wrong_type":
        stored.event_type = "communication.requested"
    else:
        stored.payload = {**stored.payload, "plan_version": True}
    db.commit()
    expect_error("UNSUPPORTED_COMMUNICATION_EVENT" if kind == "wrong_type"
                 else "INVALID_COMMUNICATION_REFERENCE", lambda: create(service), 422)
    assert count(db, CommunicationRequestRecord) == 0


def test_wrong_event_target_is_rejected(db, service):
    db.get(OutboxEventRecord, "evt_001").payload = {**source().payload, "commitment_id": "other"}
    db.commit()
    expect_error("COMMITMENT_ID_MISMATCH", lambda: create(service))


def test_no_creation_policy_adapter_is_a_real_integration_error(db):
    expect_error("COMMUNICATION_AUTHORITY_UNAVAILABLE", lambda: create(
        CommunicationRequestService(db),
    ), 503)


def test_active_proposal_and_event_do_not_prove_approval(db, authority, service):
    authority.no_approval = True
    expect_error("APPROVAL_EVIDENCE_REQUIRED", lambda: create(service), 403)
    assert count(db, CommunicationRequestRecord) == 0


@pytest.mark.parametrize("overrides,code", [
    ({"approval_expires_at": NOW}, "APPROVAL_EXPIRED"),
    ({"proposal_expires_at": NOW}, "PROPOSAL_EXPIRED"),
    ({"approved_terms": {**TERMS, "quantity": "101"}}, "APPROVED_TERMS_MISMATCH"),
    ({"recipient_customer_id": "other_customer"}, "RECIPIENT_MISMATCH"),
])
def test_authority_evidence_checks(service, authority, overrides, code):
    authority.overrides = overrides
    expect_error(code, lambda: create(service))


def test_wrong_approval_scope(service, authority):
    original = authority.authorize_request

    def wrong_scope(*args):
        result = original(*args)
        result.reference.plan_version = 9
        return result

    authority.authorize_request = wrong_scope
    expect_error("AUTHORIZATION_SCOPE_MISMATCH", lambda: create(service), 403)


@pytest.mark.parametrize("overrides,reason", [
    ({"proposal_expires_at": None}, "PROPOSAL_EXPIRY_REQUIRED"),
    ({"recipient_identity_id": None}, "VERIFIED_RECIPIENT_REQUIRED"),
    ({"recipient_evidence_refs": []}, "VERIFIED_RECIPIENT_REQUIRED"),
    ({"channel": "UNKNOWN"}, "AUTHORIZED_CHANNEL_REQUIRED"),
    ({"channel_evidence_refs": []}, "AUTHORIZED_CHANNEL_REQUIRED"),
])
def test_missing_recipient_or_channel_data_is_persisted_blocked_not_ready(service, authority, overrides, reason):
    authority.overrides = overrides
    view = create(service)
    assert view.request_status == "BLOCKED"
    assert reason in view.blocking_reasons
    assert view.message_status == "DRAFT"


def test_policy_denies_staff_even_with_a_valid_event(service):
    context = RequestContext("tenant_a", "user_staff_01", "STAFF", "corr_staff")
    expect_error("FORBIDDEN", lambda: service.create(context, COMMAND, now=NOW), 403)


def test_unknown_actor_is_not_promoted_by_spoofed_role(service):
    context = RequestContext("tenant_a", "attacker", "OWNER", "corr_spoofed")
    expect_error("FORBIDDEN", lambda: service.create(context, COMMAND, now=NOW), 403)


def test_cross_tenant_get_list_and_event_access(service):
    view = create(service)
    other = RequestContext("tenant_b", OWNER.actor_id, OWNER.actor_role, "corr_other")
    expect_error("COMMUNICATION_NOT_FOUND", lambda: service.get(other, view.communication_id), 404)
    assert service.list(other) == []
    expect_error("SOURCE_EVENT_NOT_FOUND", lambda: service.create(other, COMMAND, now=NOW), 404)
    assert service.list(OWNER, commitment_id="com_001", request_status=RequestStatus.READY_FOR_DRAFTING) == [view]
    assert service.list(OWNER, commitment_id="other") == []
    assert service.list(OWNER, request_status=RequestStatus.BLOCKED) == []


def test_storage_failure_rolls_back_request_sources_audit_and_outbox(db, service, monkeypatch):
    def fail_write(*_):
        raise OperationalError("test storage failure", {}, RuntimeError())

    monkeypatch.setattr(service.repository, "add_source", fail_write)
    expect_error("COMMUNICATION_PERSISTENCE_UNAVAILABLE", lambda: create(service), 503)
    assert count(db, CommunicationRequestRecord) == count(db, CommunicationSourceEventRecord) == 0
    assert count(db, AuditEventRecord) == 0
    assert count(db, OutboxEventRecord) == 1


def test_unique_constraints_reject_duplicate_logical_request_and_event(db, service):
    view = create(service)
    existing = db.get(CommunicationRequestRecord, ("tenant_a", view.communication_id))
    db.add(CommunicationRequestRecord(
        tenant_id="tenant_a", communication_id="different", commitment_id="com_001",
        proposal_id="proposal_001", proposal_version=3, request_status=existing.request_status,
        snapshot=existing.snapshot, created_at=NOW,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(CommunicationSourceEventRecord(
        tenant_id="tenant_a", source_event_id="evt_001", communication_id=view.communication_id,
        correlation_id="corr_001", reference=view.reference.model_dump(mode="json"),
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert count(db, CommunicationRequestRecord) == count(db, CommunicationSourceEventRecord) == 1


def test_integrity_conflict_retries_validation_once(service, monkeypatch):
    real_add = service.repository.add
    attempts = []

    def conflict_once(view):
        attempts.append(1)
        if len(attempts) == 1:
            raise IntegrityError("simulated concurrent insert", {}, RuntimeError())
        return real_add(view)

    monkeypatch.setattr(service.repository, "add", conflict_once)
    assert create(service).request_status == "READY_FOR_DRAFTING"
    assert len(attempts) == 2


def test_missing_table_returns_storage_error_not_empty_or_success(db, service):
    CommunicationSourceEventRecord.__table__.drop(db.get_bind())
    CommunicationRequestRecord.__table__.drop(db.get_bind())
    expect_error("COMMUNICATION_PERSISTENCE_UNAVAILABLE", lambda: create(service), 503)
    expect_error("COMMUNICATION_PERSISTENCE_UNAVAILABLE", lambda: service.list(OWNER), 503)
    expect_error("COMMUNICATION_PERSISTENCE_UNAVAILABLE", lambda: service.get(OWNER, "missing"), 503)


def test_commit_failure_rolls_back_even_after_audit_and_outbox_flush(db, service, monkeypatch):
    def unavailable_commit():
        raise OperationalError("commit unavailable", {}, RuntimeError())

    monkeypatch.setattr(db, "commit", unavailable_commit)
    expect_error("COMMUNICATION_PERSISTENCE_UNAVAILABLE", lambda: create(service), 503)
    assert count(db, CommunicationRequestRecord) == count(db, CommunicationSourceEventRecord) == 0
    assert count(db, AuditEventRecord) == 0
    assert count(db, OutboxEventRecord) == 1


def test_two_sqlite_sessions_cannot_create_two_requests(db):
    # SQLite constraint/concurrency evidence only; NOT a PostgreSQL row-lock smoke test.
    barrier, thread_state = Barrier(2), local()

    class ConcurrentFixtureAuthority(FixtureAuthority):
        def authorize_request(self, *args):
            if not getattr(thread_state, "started", False):
                thread_state.started = True
                barrier.wait(timeout=10)
            return super().authorize_request(*args)

    def submit():
        with Session(db.get_bind()) as session:
            try:
                return create(CommunicationRequestService(session, ConcurrentFixtureAuthority()))
            except DomainError as exc:
                # SQLite may reject a write lock instead of waiting like PostgreSQL.
                assert exc.code == "COMMUNICATION_PERSISTENCE_UNAVAILABLE"
                return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    successes = [result for result in results if result is not None]
    assert successes
    assert len({result.communication_id for result in successes}) == 1
    assert count(db, CommunicationRequestRecord) == 1
    assert count(db, CommunicationSourceEventRecord) == 1
    assert count(db, AuditEventRecord) == 1


@pytest.fixture
def api(service):
    app = FastAPI()
    app.include_router(router)  # Test-only registration, no production main.py mutation.
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    original_create = service.create
    service.create = lambda context, command: original_create(context, command, now=NOW)
    app.dependency_overrides[get_service] = lambda: service
    with TestClient(app) as client:
        yield client


HEADERS = {"X-Tenant-ID": "tenant_a", "X-Actor-ID": "user_owner_01"}


def test_three_api_routes_and_tenant_filters(api):
    response = api.post("/v1/communications/requests", headers=HEADERS, json={"source_event_id": "evt_001"})
    assert response.status_code == 200, response.text
    view = response.json()
    path = "/v1/communications/" + view["communication_id"]
    assert api.get(path, headers=HEADERS).json() == view
    assert api.get("/v1/communications?commitment_id=com_001&request_status=READY_FOR_DRAFTING",
                   headers=HEADERS).json() == [view]
    other = {**HEADERS, "X-Tenant-ID": "tenant_b"}
    assert api.get(path, headers=other).status_code == 404
    assert api.get("/v1/communications", headers=other).json() == []
    assert api.post("/v1/communications/requests", headers=HEADERS,
                    json={"source_event_id": "evt_001"}).json() == view
    assert api.get("/v1/communications?request_status=SENT", headers=HEADERS).status_code == 422


@pytest.mark.parametrize("extra", [{"approved": True}, {"tenant_id": "tenant_b"},
                                  {"recipient_identity_id": "invented"}, {"proposal_id": "invented"}])
def test_post_rejects_client_authority_claims(api, extra):
    response = api.post("/v1/communications/requests", headers=HEADERS,
                        json={"source_event_id": "evt_001", **extra})
    assert response.status_code == 422


@pytest.mark.parametrize("value", ["", "   ", "x" * 129, 1, None])
def test_invalid_post_event_id_uses_existing_validation_error_shape(api, value):
    response = api.post("/v1/communications/requests", headers=HEADERS,
                        json={"source_event_id": value})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_api_reports_blocked_intake_and_denies_unauthorized_post(api, authority):
    authority.overrides = {"recipient_identity_id": None}
    response = api.post("/v1/communications/requests", headers=HEADERS,
                        json={"source_event_id": "evt_001"})
    assert response.status_code == 200
    assert response.json()["request_status"] == "BLOCKED"
    assert response.json()["message_status"] == "DRAFT"
    denied = api.post("/v1/communications/requests",
                      headers={**HEADERS, "X-Actor-ID": "user_staff_01"},
                      json={"source_event_id": "evt_001"})
    assert denied.status_code == 403


def test_api_missing_migration_is_503_not_an_empty_list(api, db):
    CommunicationSourceEventRecord.__table__.drop(db.get_bind())
    CommunicationRequestRecord.__table__.drop(db.get_bind())
    response = api.get("/v1/communications", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "COMMUNICATION_PERSISTENCE_UNAVAILABLE"


def test_p4_metadata_compiles_for_postgresql_without_creating_any_table():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable
    for model in (CommunicationRequestRecord, CommunicationSourceEventRecord):
        ddl = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert f"CREATE TABLE {model.__tablename__}" in ddl
        for index in model.__table__.indexes:
            assert "CREATE INDEX" in str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def test_default_router_has_no_guessed_creation_policy(db):
    assert get_request_authority() is None
    from app.core.dependencies import get_db
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.post("/v1/communications/requests", headers=HEADERS,
                               json={"source_event_id": "evt_001"})
        assert response.status_code == 503
        assert response.json()["code"] == "COMMUNICATION_AUTHORITY_UNAVAILABLE"
        assert client.get("/v1/communications", headers=HEADERS).json() == []


def test_missing_auth_and_unknown_actor(api):
    assert api.get("/v1/communications").status_code == 400
    assert api.get("/v1/communications", headers={**HEADERS, "X-Actor-ID": "unknown"}).status_code == 403
