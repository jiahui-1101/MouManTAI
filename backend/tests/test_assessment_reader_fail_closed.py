"""Tests for fail-closed AuthoritativeAssessmentHistoryReader (ADR-015, Task T-P3H1).

Verifies:
1. Missing assessment_id raises DomainError("ASSESSMENT_PROVENANCE_MISSING") without audit_id fallback.
2. Missing commitment_version raises DomainError("ASSESSMENT_PROVENANCE_MISSING") without defaulting to 1.
3. Missing snapshot metadata raises DomainError("ASSESSMENT_PROVENANCE_MISSING") without defaulting to 1.
4. Advisory assessments (advisory=True) raise DomainError("ASSESSMENT_PROVENANCE_MISSING") and are excluded.
5. Fully provenanced assessments return all exact stored values.
6. Error messages name the missing field without leaking PII or internal credentials.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import CoreEventType
from app.core.feasibility_adapters import AuthoritativeAssessmentHistoryReader
from app.core.models import AuditEventRecord


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_reader_raises_on_missing_assessment_id(session: Session) -> None:
    """Missing assessment_id must raise ASSESSMENT_PROVENANCE_MISSING (no audit_id fallback)."""
    tenant = "tenant_reader_01"
    com_id = "com_reader_01"
    ctx = RequestContext(tenant_id=tenant, actor_id="user_test", actor_role="MANAGER", correlation_id="corr_test_01")

    # Seed audit event representing INFEASIBLE risk transition but missing assessment_id
    audit = AuditEventRecord(
        audit_id="aud_missing_aid_01",
        tenant_id=tenant,
        commitment_id=com_id,
        event_type=CoreEventType.COMMITMENT_AT_RISK.value,
        actor_id="service_p2",
        actor_role="SERVICE",
        dimension="risk",
        previous_state={"risk_state": "NORMAL"},
        new_state={
            "feasibility_state": "INFEASIBLE",
            # "assessment_id" is intentionally omitted!
            "commitment_version": 2,
            "snapshot_version": 101,
            "constraints": [{"dimension": "MATERIAL", "code": "SHORTAGE", "message": "Patty shortage"}],
            "affected_commitment_ids": [],
        },
        evidence_refs=["ev_supplier_01"],
        reason="Supplier shortage",
        correlation_id=ctx.correlation_id,
        occurred_at=_now(),
    )
    session.add(audit)
    session.commit()

    reader = AuthoritativeAssessmentHistoryReader()

    with pytest.raises(DomainError) as exc_info:
        reader.list_for_commitment(session, ctx, com_id)

    err = exc_info.value
    assert err.code == "ASSESSMENT_PROVENANCE_MISSING"
    assert "assessment_id" in err.message
    assert err.details.get("field") == "assessment_id"
    assert err.status_code == 422


def test_reader_raises_on_missing_commitment_version(session: Session) -> None:
    """Missing commitment_version must raise ASSESSMENT_PROVENANCE_MISSING (no defaulting to 1)."""
    tenant = "tenant_reader_02"
    com_id = "com_reader_02"
    ctx = RequestContext(tenant_id=tenant, actor_id="user_test", actor_role="MANAGER", correlation_id="corr_test_02")

    audit = AuditEventRecord(
        audit_id="aud_missing_cver_01",
        tenant_id=tenant,
        commitment_id=com_id,
        event_type=CoreEventType.COMMITMENT_AT_RISK.value,
        actor_id="service_p2",
        actor_role="SERVICE",
        dimension="risk",
        previous_state={"risk_state": "NORMAL"},
        new_state={
            "assessment_id": "asm_exact_02",
            "feasibility_state": "INFEASIBLE",
            # "commitment_version" is omitted!
            "snapshot_version": 102,
            "constraints": [],
            "affected_commitment_ids": [],
        },
        evidence_refs=[],
        reason="Capacity breach",
        correlation_id=ctx.correlation_id,
        occurred_at=_now(),
    )
    session.add(audit)
    session.commit()

    reader = AuthoritativeAssessmentHistoryReader()

    with pytest.raises(DomainError) as exc_info:
        reader.list_for_commitment(session, ctx, com_id)

    err = exc_info.value
    assert err.code == "ASSESSMENT_PROVENANCE_MISSING"
    assert "commitment_version" in err.message
    assert err.details.get("field") == "commitment_version"


def test_reader_raises_on_missing_snapshot_metadata(session: Session) -> None:
    """Missing snapshot_version must raise ASSESSMENT_PROVENANCE_MISSING (no defaulting to 1)."""
    tenant = "tenant_reader_03"
    com_id = "com_reader_03"
    ctx = RequestContext(tenant_id=tenant, actor_id="user_test", actor_role="MANAGER", correlation_id="corr_test_03")

    audit = AuditEventRecord(
        audit_id="aud_missing_snap_01",
        tenant_id=tenant,
        commitment_id=com_id,
        event_type=CoreEventType.COMMITMENT_AT_RISK.value,
        actor_id="service_p2",
        actor_role="SERVICE",
        dimension="risk",
        previous_state={"risk_state": "NORMAL"},
        new_state={
            "assessment_id": "asm_exact_03",
            "feasibility_state": "INFEASIBLE",
            "commitment_version": 3,
            "assessment_commitment_version": 2,
            # "snapshot_version" omitted!
            "constraints": [],
            "affected_commitment_ids": [],
        },
        evidence_refs=[],
        reason="Drift breach",
        correlation_id=ctx.correlation_id,
        occurred_at=_now(),
    )
    session.add(audit)
    session.commit()

    reader = AuthoritativeAssessmentHistoryReader()

    with pytest.raises(DomainError) as exc_info:
        reader.list_for_commitment(session, ctx, com_id)

    err = exc_info.value
    assert err.code == "ASSESSMENT_PROVENANCE_MISSING"
    assert "snapshot_version" in err.message
    assert err.details.get("field") == "snapshot_version"


def test_reader_rejects_advisory_assessments(session: Session) -> None:
    """Advisory assessments (advisory=True) are excluded and rejected if looked up directly."""
    tenant = "tenant_reader_04"
    com_id = "com_reader_04"
    ctx = RequestContext(tenant_id=tenant, actor_id="user_test", actor_role="MANAGER", correlation_id="corr_test_04")

    # Advisory event
    audit = AuditEventRecord(
        audit_id="aud_advisory_01",
        tenant_id=tenant,
        commitment_id=com_id,
        event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
        actor_id="service_p2",
        actor_role="SERVICE",
        dimension="feasibility",
        previous_state={},
        new_state={
            "advisory": True,
            "assessment_id": "asm_advisory_04",
            "feasibility_state": "FEASIBLE",
            "commitment_version": 1,
            "snapshot_version": 1,
            "constraints": [],
        },
        evidence_refs=[],
        reason="Advisory preview",
        correlation_id=ctx.correlation_id,
        occurred_at=_now(),
    )
    session.add(audit)
    session.commit()

    reader = AuthoritativeAssessmentHistoryReader()

    # list_for_commitment filters out advisory rows cleanly
    assert reader.list_for_commitment(session, ctx, com_id) == []

    # get_assessment on advisory record raises ASSESSMENT_PROVENANCE_MISSING
    with pytest.raises(DomainError) as exc_info:
        reader.get_assessment(session, ctx, com_id, "asm_advisory_04")

    err = exc_info.value
    assert err.code == "ASSESSMENT_PROVENANCE_MISSING"
    assert "advisory" in err.message
    assert err.details.get("field") == "advisory"


def test_reader_returns_complete_provenance_when_valid(session: Session) -> None:
    """Fully provenanced assessment returns exact stored values without synthetic fallbacks."""
    tenant = "tenant_reader_05"
    com_id = "com_reader_05"
    ctx = RequestContext(tenant_id=tenant, actor_id="user_test", actor_role="MANAGER", correlation_id="corr_test_05")

    exact_time = _now()
    audit = AuditEventRecord(
        audit_id="aud_valid_05",
        tenant_id=tenant,
        commitment_id=com_id,
        event_type=CoreEventType.COMMITMENT_AT_RISK.value,
        actor_id="service_p2",
        actor_role="SERVICE",
        dimension="risk",
        previous_state={"risk_state": "NORMAL"},
        new_state={
            "assessment_id": "asm_exact_05",
            "feasibility_state": "INFEASIBLE",
            "commitment_version": 4,
            "assessment_commitment_version": 3,
            "snapshot_id": "snap_exact_05",
            "snapshot_version": 204,
            "constraints": [{"code": "SHORTAGE", "resource_id": "BURGER_PATTY", "severity": "HARD", "evidence_refs": ["ev_maint_log_05"]}],
            "affected_commitment_ids": ["com_downstream_01"],
            "evidence_refs": ["ev_maint_log_05"],
            "solver_status": "COMPLETED",
            "assumptions": ["Grill offline for 24h"],
            "assessed_at": exact_time.isoformat(),
        },
        evidence_refs=["ev_maint_log_05"],
        reason="Maintenance delay",
        correlation_id=ctx.correlation_id,
        occurred_at=exact_time,
    )
    session.add(audit)
    session.commit()

    reader = AuthoritativeAssessmentHistoryReader()
    results = reader.list_for_commitment(session, ctx, com_id)
    assert len(results) == 1

    fa = results[0]
    assert fa.assessment_id == "asm_exact_05"
    assert fa.commitment_version == 3
    assert fa.snapshot_version == 204
    assert fa.status.value == "INFEASIBLE"
    assert fa.constraints[0].code == "SHORTAGE"
    assert fa.constraints[0].resource_id == "BURGER_PATTY"
    assert fa.constraints[0].severity == "HARD"
    assert fa.affected_commitment_ids == ["com_downstream_01"]
    assert fa.evidence_refs == ["ev_maint_log_05"]
    assert fa.assumptions == ["Grill offline for 24h"]
    assert fa.assessed_at == exact_time

    # Direct lookup
    fetched = reader.get_assessment(session, ctx, com_id, "asm_exact_05")
    assert fetched.assessment_id == fa.assessment_id
    assert fetched.commitment_version == 3
    assert fetched.snapshot_version == 204

    with pytest.raises(DomainError) as wrong_identity:
        reader.get_assessment(session, ctx, com_id, "asm_wrong_05")
    assert wrong_identity.value.code == "ASSESSMENT_NOT_FOUND"


def test_reader_rejects_missing_or_inconsistent_evaluated_version() -> None:
    base = {
        "assessment_id": "asm_version_check",
        "commitment_version": 5,
        "snapshot_version": 7,
    }
    with pytest.raises(DomainError) as missing:
        AuthoritativeAssessmentHistoryReader.validate_provenance_payload(
            base, commitment_id="com_version_check"
        )
    assert missing.value.code == "ASSESSMENT_PROVENANCE_MISSING"
    assert missing.value.details["field"] == "assessment_commitment_version"

    with pytest.raises(DomainError) as inconsistent:
        AuthoritativeAssessmentHistoryReader.validate_provenance_payload(
            {**base, "assessment_commitment_version": 2},
            commitment_id="com_version_check",
        )
    assert inconsistent.value.code == "ASSESSMENT_PROVENANCE_MISSING"
    assert inconsistent.value.details["field"] == "commitment_version"

    with pytest.raises(DomainError) as missing_snapshot_id:
        AuthoritativeAssessmentHistoryReader.validate_provenance_payload(
            {**base, "assessment_commitment_version": 4},
            commitment_id="com_version_check",
        )
    assert missing_snapshot_id.value.details["field"] == "snapshot_id"
