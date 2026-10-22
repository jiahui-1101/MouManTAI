"""Run actual Alembic migrations; PostgreSQL uses disposable, isolated schemas.

P4_TEST_DATABASE_URL must name p4_migration_test or start with p4_test_. Never
point this suite at the application's database. No create_all/stamp is used.
Authority fixtures imported below are test-only and never wired into production.
"""

from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import MetaData, Table, create_engine, event, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.communication.drafting import MessageDraftService
from app.communication.models import (
    CommunicationRequestRecord, CommunicationSourceEventRecord, DraftReviewRecord, MessageDraftRecord,
)
from app.communication.review import DraftReviewService
from app.communication.schemas import ApproveDraftRequest, PrepareDraftRequest, RejectDraftRequest
from app.communication.service import CommunicationRequestService
from app.communication.tests.test_requests import COMMAND, HEADERS, NOW, OWNER, TERMS, FixtureAuthority, source
from app.communication.tests.test_drafting import FixtureDraftAuthority
from app.communication.tests.test_review import MANAGER, FixtureReviewAuthority
from app.core.dependencies import get_db
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentProposalRecord, CommitmentRecord
from app.db.base import Base
from app.main import app

BACKEND = Path(__file__).resolve().parents[3]
HEAD = "0008_p4_communication"
PREVIOUS = "0007_recovery_case_constraints_alignment"
TABLES = {
    "communication_requests", "communication_request_sources",
    "communication_drafts", "communication_draft_reviews",
}


def config(url=None):
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(params=["sqlite", "postgresql"])
def migrated(request, tmp_path, monkeypatch):
    admin = None
    schema = None
    if request.param == "postgresql":
        configured = os.getenv("P4_TEST_DATABASE_URL")
        if not configured:
            pytest.skip("PostgreSQL migration NOT RUN: set a disposable P4_TEST_DATABASE_URL")
        url = make_url(configured)
        if not url.drivername.startswith("postgresql") or not (
            url.database == "p4_migration_test" or (url.database or "").startswith("p4_test_")
        ):
            pytest.fail("Refusing non-disposable database; use p4_migration_test or p4_test_* only")
        admin = create_engine(url)
        schema = f"p4_mig_test_{uuid4().hex}"
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    else:
        url = f"sqlite:///{(tmp_path / 'migrated.sqlite').as_posix()}"
    engine = create_engine(url)
    if request.param == "sqlite":
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        command.upgrade(config(url), "head")
        yield engine, config(url)
    finally:
        engine.dispose()
        if admin:
            # Only the UUID schema created above; never a supplied schema/database.
            assert schema.startswith("p4_mig_test_") and len(schema) == len("p4_mig_test_") + 32
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def test_single_head_and_real_parent():
    scripts = ScriptDirectory.from_config(config())
    assert scripts.get_heads() == [HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS
    assert len(HEAD) <= 32
    assert len(list(scripts.walk_revisions())) == 8


def test_postgresql_offline_ddl_and_fresh_metadata_registration(monkeypatch):
    # A fresh interpreter ensures importing App/tests has not registered P4 first.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused:unused@localhost/unused")
    code = (
        "from alembic import command; from alembic.config import Config; "
        "from app.db.base import Base; "
        "assert 'communication_requests' not in Base.metadata.tables; "
        "command.upgrade(Config('alembic.ini'), '0007_recovery_case_constraints_alignment:head', sql=True); "
        "assert {'communication_requests','communication_request_sources','communication_drafts',"
        "'communication_draft_reviews'} <= set(Base.metadata.tables)"
    )
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=BACKEND,
                            capture_output=True, text=True, check=True)
    for name in TABLES:
        assert f"CREATE TABLE {name}" in result.stdout
    for required in ("uq_draft_request_identity", "fk_review_exact_draft", "uq_review_terminal_draft",
                     "uq_review_request_key", "TIMESTAMP WITH TIME ZONE", "JSON"):
        assert required in result.stdout
    assert "CREATE TABLE commitments" not in result.stdout
    stream = StringIO()
    with redirect_stdout(stream):
        command.downgrade(config(), f"{HEAD}:{PREVIOUS}", sql=True)
    assert stream.getvalue().count("DROP TABLE communication_") == 4
    assert "DROP TABLE commitments" not in stream.getvalue()


def test_migrated_schema_matches_orm_exactly(migrated):
    engine, _ = migrated
    inspector = inspect(engine)
    assert TABLES <= set(inspector.get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        differences = compare_metadata(MigrationContext.configure(connection, opts={
            "include_object": lambda obj, name, kind, reflected, compare_to: (
                name in TABLES if kind == "table" else True
            ),
        }), Base.metadata)
        assert differences == []
    for name in TABLES:
        model = Base.metadata.tables[name]
        columns = inspector.get_columns(name)
        assert [(c["name"], c["nullable"]) for c in columns] == [(c.name, c.nullable) for c in model.columns]
        for column in columns:
            assert column["type"].compile(dialect=engine.dialect) == model.c[column["name"]].type.compile(dialect=engine.dialect)
        assert inspector.get_pk_constraint(name)["constrained_columns"] == [c.name for c in model.primary_key]
        assert {u["name"]: tuple(u["column_names"]) for u in inspector.get_unique_constraints(name)} == {
            c.name: tuple(col.name for col in c.columns) for c in model.constraints if c.__class__.__name__ == "UniqueConstraint"
        }
        assert {i["name"]: (tuple(i["column_names"]), bool(i["unique"])) for i in inspector.get_indexes(name)
                if not i.get("duplicates_constraint")} == {
            i.name: (tuple(c.name for c in i.columns), bool(i.unique)) for i in model.indexes
        }
        actual_fks = {f["name"]: (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
                      for f in inspector.get_foreign_keys(name)}
        expected_fks = {f.name: (tuple(c.name for c in f.columns), f.referred_table.name,
                                tuple(e.column.name for e in f.elements)) for f in model.foreign_key_constraints}
        assert actual_fks == expected_fks


def request_row(tenant="tenant_a", identifier="request_1", proposal="proposal_1"):
    return CommunicationRequestRecord(tenant_id=tenant, communication_id=identifier, commitment_id="com_1",
        proposal_id=proposal, proposal_version=1, request_status="READY_FOR_DRAFTING", snapshot={}, created_at=NOW)


def draft_row(tenant="tenant_a", identifier="draft_1", request_id="request_1", digest="a" * 64):
    return MessageDraftRecord(tenant_id=tenant, draft_id=identifier, communication_id=request_id,
                              validation_hash=digest, snapshot={}, created_at=NOW)


def review_row(tenant="tenant_a", identifier="review_1", request_id="request_1", draft_id="draft_1", key="review_key_1"):
    return DraftReviewRecord(tenant_id=tenant, review_id=identifier, communication_id=request_id,
                             draft_id=draft_id, request_key=key, snapshot={}, reviewed_at=NOW)


def raw_graph(db):
    db.add(request_row())
    db.flush()
    db.add(draft_row())
    db.flush()
    db.add(review_row())
    db.add(CommunicationSourceEventRecord(tenant_id="tenant_a", source_event_id="source_1",
                                         communication_id="request_1", correlation_id="correlation_1", reference={}))
    db.commit()


@pytest.mark.parametrize("case", [
    "request_primary", "request_proposal", "source_primary", "source_tenant", "draft_primary",
    "draft_variant", "draft_tenant", "review_primary", "review_terminal", "review_key",
    "review_tenant", "review_exact_request", "review_required_column",
])
def test_database_rejects_invalid_references_and_duplicates(migrated, case):
    engine, _ = migrated
    with Session(engine) as db:
        raw_graph(db)
        if case == "review_exact_request":
            db.add(request_row(identifier="request_2", proposal="proposal_2"))
            db.commit()
        if case == "review_key":
            db.add(draft_row(identifier="draft_2", digest="b" * 64))
            db.commit()
        candidates = {
            "request_primary": lambda: request_row(proposal="other_proposal"),
            "request_proposal": lambda: request_row(identifier="other_request"),
            "source_primary": lambda: CommunicationSourceEventRecord(tenant_id="tenant_a", source_event_id="source_1",
                communication_id="request_1", correlation_id="other", reference={}),
            "source_tenant": lambda: CommunicationSourceEventRecord(tenant_id="tenant_b", source_event_id="source_2",
                communication_id="request_1", correlation_id="other", reference={}),
            "draft_primary": lambda: draft_row(digest="c" * 64),
            "draft_variant": lambda: draft_row(identifier="other_draft"),
            "draft_tenant": lambda: draft_row(tenant="tenant_b"),
            "review_primary": lambda: review_row(key="other_key"),
            "review_terminal": lambda: review_row(identifier="other_review", key="other_key"),
            "review_key": lambda: review_row(identifier="other_review", draft_id="draft_2"),
            "review_tenant": lambda: review_row(tenant="tenant_b"),
            "review_exact_request": lambda: review_row(identifier="other_review", request_id="request_2", key="other_key"),
            "review_required_column": lambda: review_row(identifier="other_review", key=None),
        }
        db.add(candidates[case]())
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(DraftReviewRecord)) == 1


def test_same_identifiers_and_idempotency_keys_are_isolated_by_tenant(migrated):
    engine, _ = migrated
    with Session(engine) as db:
        for tenant in ("tenant_a", "tenant_b"):
            db.add(request_row(tenant=tenant))
            db.flush()
            db.add(draft_row(tenant=tenant))
            db.flush()
            db.add(review_row(tenant=tenant))
            db.add(CommunicationSourceEventRecord(tenant_id=tenant, source_event_id="source_1",
                communication_id="request_1", correlation_id="correlation_1", reference={}))
            db.commit()
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(DraftReviewRecord)) == 2
        service = CommunicationRequestService(db)
        assert len(service.repository.list("tenant_a", None, None)) == 1
        assert service.repository.list("tenant_c", None, None) == []


def seed_core(db):
    db.add(CommitmentRecord(tenant_id="tenant_a", commitment_id="com_001", order_id="order_001",
        customer_id="customer_001", terms=TERMS, agreement_state="OFFERED", feasibility_state="INFEASIBLE",
        risk_state="AT_RISK", recovery_state="EXECUTING", fulfilment_state="NOT_STARTED",
        commitment_version=11, evidence_refs=["ev_original"], updated_at=NOW))
    db.flush()
    db.add(CommitmentProposalRecord(tenant_id="tenant_a", commitment_id="com_001", proposal_id="proposal_001",
        proposal_version=3, revised_terms=TERMS, status="ACTIVE", reason="Recovery offer",
        evidence_refs=["ev_proposal_001"], created_at=NOW, updated_at=NOW))
    db.add(source())
    db.commit()


def prepare_graph(db):
    seed_core(db)
    requests = CommunicationRequestService(db, FixtureAuthority())
    request = requests.create(OWNER, COMMAND, now=NOW)
    assert requests.create(OWNER, COMMAND, now=NOW).communication_id == request.communication_id
    draft_authority = FixtureDraftAuthority()
    drafts = MessageDraftService(db, draft_authority)
    draft = drafts.prepare(OWNER, request.communication_id, PrepareDraftRequest(), now=NOW)
    assert drafts.prepare(OWNER, request.communication_id, PrepareDraftRequest(), now=NOW).draft_id == draft.draft_id
    return request, draft, draft_authority


def test_real_services_persist_replay_and_revalidate_reviews_across_sessions(migrated):
    engine, _ = migrated
    authority = FixtureReviewAuthority()
    with Session(engine) as db:
        request, draft, draft_authority = prepare_graph(db)
        service = DraftReviewService(db, draft_authority, authority)
        command_ = ApproveDraftRequest(request_key="persistent_approve_key", expected_content_hash=draft.content_hash)
        first = service.approve(MANAGER, request.communication_id, draft.draft_id, command_, now=NOW)
        again = service.approve(MANAGER, request.communication_id, draft.draft_id, command_, now=NOW)
        assert first.decision == again.decision
        assert first.effective_approval and not first.send_authorized
        rejected_draft = MessageDraftService(db, draft_authority).prepare(
            OWNER, request.communication_id, PrepareDraftRequest(language="zh"), now=NOW)
        rejected = service.reject(MANAGER, request.communication_id, rejected_draft.draft_id,
            RejectDraftRequest(request_key="persistent_reject_key", expected_content_hash=rejected_draft.content_hash,
                               reason="Revise the greeting"), now=NOW)
        assert rejected.review_state == "REJECTED"
    with Session(engine) as db:
        service = DraftReviewService(db, draft_authority, authority)
        loaded = service.get(MANAGER, request.communication_id, draft.draft_id, now=NOW)
        assert loaded.decision == first.decision
        assert db.scalar(select(func.count()).select_from(CommunicationSourceEventRecord)) == 1
        assert db.scalar(select(func.count()).select_from(MessageDraftRecord)) == 2
        assert db.scalar(select(func.count()).select_from(DraftReviewRecord)) == 2
        assert db.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.event_type == "communication.draft_approved")) == 1
        authority.overrides = {"existing_review_status": "REVOKED"}
        invalid = service.get(MANAGER, request.communication_id, draft.draft_id, now=NOW)
        assert invalid.review_state == "INVALIDATED" and not invalid.effective_approval
        assert invalid.decision == first.decision and invalid.invalidation_audit_id
    with Session(engine) as db:
        authority.overrides = {}
        invalid = DraftReviewService(db, draft_authority, authority).get(
            MANAGER, request.communication_id, draft.draft_id, now=NOW)
        assert invalid.review_state == "INVALIDATED" and invalid.decision == first.decision


def test_review_and_audit_rollback_is_atomic(migrated, monkeypatch):
    engine, _ = migrated
    with Session(engine) as db:
        request, draft, draft_authority = prepare_graph(db)
        service = DraftReviewService(db, draft_authority, FixtureReviewAuthority())
        before = db.scalar(select(func.count()).select_from(AuditEventRecord))
        original = service._audit
        def fail_after_audit(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("test transaction failure after audit flush")
        monkeypatch.setattr(service, "_audit", fail_after_audit)
        with pytest.raises(RuntimeError, match="transaction failure"):
            service.approve(MANAGER, request.communication_id, draft.draft_id,
                ApproveDraftRequest(request_key="atomic_approve_key", expected_content_hash=draft.content_hash), now=NOW)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(DraftReviewRecord)) == 0
        assert db.scalar(select(func.count()).select_from(AuditEventRecord)) == before


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
@pytest.mark.parametrize("competing_action", ["approve", "reject"])
def test_postgresql_concurrent_review_uses_one_terminal_decision(migrated, competing_action):
    engine, _ = migrated
    with Session(engine) as db:
        request, draft, draft_authority = prepare_graph(db)
    barrier = Barrier(2, timeout=15)
    def decide(action):
        with Session(engine) as db:
            # Establish two independent PostgreSQL connections before racing.
            db.connection()
            barrier.wait()
            service = DraftReviewService(db, draft_authority, FixtureReviewAuthority())
            try:
                if action == "approve":
                    result = service.approve(MANAGER, request.communication_id, draft.draft_id,
                        ApproveDraftRequest(request_key="concurrent_approve_key", expected_content_hash=draft.content_hash), now=NOW)
                else:
                    result = service.reject(MANAGER, request.communication_id, draft.draft_id,
                        RejectDraftRequest(request_key="concurrent_reject_key", expected_content_hash=draft.content_hash,
                                           reason="Concurrent rejection"), now=NOW)
                return result.decision.review_id
            except DomainError as error:
                assert error.status_code == 409 and error.code == "REVIEW_ALREADY_DECIDED"
                return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(decide, ["approve", competing_action]))
    if competing_action == "approve":
        assert results[0] == results[1] and "conflict" not in results
    else:
        assert results.count("conflict") == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(DraftReviewRecord)) == 1
        assert db.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.event_type.in_(["communication.draft_approved", "communication.draft_rejected"]))) == 1


@pytest.mark.parametrize("populated", [False, True])
def test_registered_api_uses_migrated_database_without_authority_bypass(migrated, populated):
    engine, _ = migrated
    request = None
    if populated:
        with Session(engine) as db:
            seed_core(db)
            request = CommunicationRequestService(db, FixtureAuthority()).create(OWNER, COMMAND, now=NOW)
    def session_override():
        with Session(engine) as db:
            yield db
    # Only replace the database dependency; production authority boundaries must deny.
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = session_override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/communications", headers=HEADERS)
            assert response.status_code == 200 and len(response.json()) == int(populated)
            summary = client.get("/v1/communications/summary", headers=HEADERS)
            assert summary.status_code == 200
            result = summary.json()
            assert result["total"] == int(populated) and result["needs_attention"] == 0
            assert result["drafted"] is None and result["sent"] is None
            assert result["unavailable_reasons"] == {
                "drafted": "DRAFT_REVALIDATION_UNAVAILABLE", "sent": "SENDING_RECORDS_UNAVAILABLE",
            }
            blocked = client.post("/v1/communications/requests", headers=HEADERS, json=COMMAND.model_dump())
            assert blocked.status_code == 503 and blocked.json()["code"] == "COMMUNICATION_AUTHORITY_UNAVAILABLE"
            if request:
                blocked = client.post(f"/v1/communications/{request.communication_id}/prepare", headers=HEADERS, json={})
                assert blocked.status_code == 503 and blocked.json()["code"] == "DRAFT_REVALIDATION_UNAVAILABLE"
                blocked = client.post(f"/v1/communications/{request.communication_id}/drafts/missing/approve",
                    headers=HEADERS, json={"request_key": "unavailable_review", "expected_content_hash": "a" * 64})
                assert blocked.status_code == 503 and blocked.json()["code"] == "REVIEW_AUTHORITY_UNAVAILABLE"
            assert client.get("/health").status_code == 200
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_p4_downgrade_preserves_core_and_recovery_then_reupgrade(migrated):
    engine, cfg = migrated
    with Session(engine) as db:
        seed_core(db)
        raw_graph(db)
    recovery = Table("recovery_cases", MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(recovery.insert().values(tenant_id="tenant_a", case_id="case_preserved",
            commitment_id="com_001", risk_episode_id="episode_preserved", opening_event_id="opening_preserved",
            status="COMPLETED", case_version=1, commitment_version=11, payload_schema_version=1,
            case_payload={}, resolution_refs=[], created_at=NOW, updated_at=NOW))
    original_tables = set(inspect(engine).get_table_names()) - TABLES
    with engine.connect() as connection:
        before = {name: connection.scalar(text(f'SELECT count(*) FROM "{name}"'))
                  for name in original_tables if name != "alembic_version"}
    command.downgrade(cfg, PREVIOUS)
    assert set(inspect(engine).get_table_names()) == original_tables
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == PREVIOUS
        for name, count in before.items():
            assert connection.scalar(text(f'SELECT count(*) FROM "{name}"')) == count
    command.upgrade(cfg, "head")
    assert TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        assert connection.scalar(select(func.count()).select_from(recovery)) == 1
        for name in TABLES:
            assert connection.scalar(text(f'SELECT count(*) FROM "{name}"')) == 0
