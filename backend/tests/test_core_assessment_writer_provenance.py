"""P5 Core writer preserves exact P2 result identity and fails closed on missing sources."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.feasibility_adapters import (
    AuthoritativeAssessmentHistoryReader,
    AuthoritativeAssessmentWriter,
)
from app.core.models import AuditEventRecord, CommitmentRecord
from app.feasibility.api_schemas import AssessCommitmentRequest
from app.feasibility.production_fixtures import build_production_example
from app.feasibility.service import evaluate


def test_core_writer_preserves_p2_identity_without_fallback(session: Session) -> None:
    snapshot, commitment = build_production_example()
    result = evaluate(snapshot, None, commitment)
    session.add(CommitmentRecord(
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        order_id=commitment.order_id,
        customer_id=commitment.customer_id,
        terms=commitment.terms.model_dump(mode="json"),
        agreement_state="CONFIRMED",
        feasibility_state="NOT_ASSESSED",
        risk_state="NORMAL",
        recovery_state="NONE",
        fulfilment_state="NOT_STARTED",
        commitment_version=commitment.commitment_version,
        evidence_refs=[],
        updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    context = RequestContext(
        tenant_id=commitment.tenant_id,
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id="corr_core_writer_provenance",
    )
    request = AssessCommitmentRequest(
        expected_commitment_version=commitment.commitment_version,
        expected_snapshot_version=snapshot.current_snapshot_version,
    )
    writer = AuthoritativeAssessmentWriter()

    for broken, code in (
        (result.model_copy(update={"assessment_id": ""}), "ASSESSMENT_PROVENANCE_MISSING"),
        (result.model_copy(update={"snapshot_id": ""}), "ASSESSMENT_PROVENANCE_MISSING"),
        (result.model_copy(update={"snapshot_id": "snap_wrong"}), "ASSESSMENT_PROVENANCE_MISMATCH"),
        (result.model_copy(update={"snapshot_version": result.snapshot_version + 1}), "ASSESSMENT_PROVENANCE_MISMATCH"),
        (result.model_copy(update={"commitment_id": "com_wrong"}), "ASSESSMENT_PROVENANCE_MISMATCH"),
    ):
        with pytest.raises(DomainError) as error:
            writer.assess(session, context, commitment, request, snapshot=snapshot, result=broken)
        assert error.value.code == code
        assert session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id)).commitment_version == commitment.commitment_version

    persisted = writer.assess(session, context, commitment, request, snapshot=snapshot, result=result)
    assert persisted.assessment_id == result.assessment_id
    assert persisted.commitment_version == commitment.commitment_version
    assert persisted.snapshot_version == result.snapshot_version

    history = AuthoritativeAssessmentHistoryReader().get_assessment(
        session, context, commitment.commitment_id, result.assessment_id,
    )
    assert history.assessment_id == result.assessment_id
    assert history.commitment_version == result.commitment_version
    assert history.snapshot_version == result.snapshot_version

    audit = session.scalar(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == commitment.tenant_id,
        AuditEventRecord.commitment_id == commitment.commitment_id,
        AuditEventRecord.new_state["assessment_id"].as_string() == result.assessment_id,
    ))
    assert audit is not None
    assert audit.new_state["assessment_commitment_version"] == result.commitment_version
    assert audit.new_state["commitment_version"] == result.commitment_version + 1
    assert audit.new_state["snapshot_id"] == result.snapshot_id
    assert audit.new_state["snapshot_version"] == result.snapshot_version
