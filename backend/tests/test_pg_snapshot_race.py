"""PostgreSQL proof that a source promotion between evaluation and write is rejected."""

import os
from datetime import UTC, datetime
from threading import Event, Thread
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.feasibility_adapters import AuthoritativeAssessmentWriter
from app.core.models import AuditEventRecord, CommitmentRecord
from app.feasibility.api_schemas import AssessCommitmentRequest
from app.feasibility.persisted_sources import OperationalSnapshotRecord, stage_snapshot
from app.feasibility.production import EvaluationSnapshot
from app.feasibility.production_fixtures import build_production_example
from app.feasibility.service import evaluate


def _tenant_copy(value, tenant):
    if isinstance(value, dict):
        return {key: (tenant if key == "tenant_id" else _tenant_copy(item, tenant))
                for key, item in value.items()}
    if isinstance(value, list):
        return [_tenant_copy(item, tenant) for item in value]
    return value


def test_postgresql_concurrent_source_promotion_rejects_stale_assessment():
    configured = os.getenv("TEST_DATABASE_URL")
    if not configured:
        pytest.skip("PostgreSQL race NOT VERIFIED: approved TEST_DATABASE_URL absent")
    url = make_url(configured)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.database == "p4_test_pr16_corrections"
    engine = create_engine(configured)
    tenant = f"tenant_race_{uuid4().hex}"
    source, original = build_production_example()
    source_data = _tenant_copy(source.model_dump(mode="json", exclude_computed_fields=True), tenant)
    current = EvaluationSnapshot.model_validate(source_data)
    next_data = _tenant_copy(source_data, tenant)
    next_data["operational"]["snapshot_version"] = current.operational.snapshot_version + 1
    next_data["operational"]["snapshot_id"] = f"snapshot-race-{uuid4().hex}"
    next_data["current_snapshot_version"] = next_data["operational"]["snapshot_version"]
    next_source = EvaluationSnapshot.model_validate(next_data)
    commitment = original.model_copy(update={"tenant_id": tenant})
    context = RequestContext(tenant_id=tenant, actor_id="service_p2_writer", actor_role="SERVICE",
                             correlation_id=f"corr_{uuid4().hex}")
    with Session(engine) as db:
        db.add(CommitmentRecord(
            tenant_id=tenant, commitment_id=commitment.commitment_id,
            order_id=commitment.order_id, customer_id=commitment.customer_id,
            terms=commitment.terms.model_dump(mode="json"), agreement_state="CONFIRMED",
            feasibility_state="NOT_ASSESSED", risk_state="NORMAL", recovery_state="NONE",
            fulfilment_state="NOT_STARTED", commitment_version=commitment.commitment_version,
            evidence_refs=list(commitment.evidence_refs), updated_at=datetime.now(UTC),
        ))
        stage_snapshot(db, current, current=True)
        stage_snapshot(db, next_source)
        db.commit()

    result = evaluate(current, None, commitment)
    start = Event()
    finished = Event()
    errors = []

    def promote():
        try:
            assert start.wait(10)
            with Session(engine) as db:
                before = db.get(OperationalSnapshotRecord, (tenant, current.operational.snapshot_version))
                after = db.get(OperationalSnapshotRecord, (tenant, next_source.operational.snapshot_version))
                before.is_current = False
                db.flush()
                after.is_current = True
                db.commit()
        except (AssertionError, SQLAlchemyError) as exc:
            errors.append(exc)
        finally:
            finished.set()

    thread = Thread(target=promote)
    thread.start()
    start.set()
    assert finished.wait(15)
    thread.join(1)
    assert not errors
    with Session(engine) as db:
        with pytest.raises(DomainError) as failure:
            AuthoritativeAssessmentWriter().assess(
                db, context, commitment,
                AssessCommitmentRequest(expected_commitment_version=commitment.commitment_version,
                                        expected_snapshot_version=current.operational.snapshot_version),
                snapshot=current, result=result,
            )
        assert failure.value.code == "SNAPSHOT_DRIFT_CONFLICT"
        db.rollback()
        assert db.get(CommitmentRecord, (tenant, commitment.commitment_id)).commitment_version == 1
        assert db.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant,
            AuditEventRecord.new_state["assessment_id"].as_string() == result.assessment_id,
        )).all() == []
    engine.dispose()
