"""Authoritative Core Feasibility Adapters.

Concrete P5 implementation of P2 feasibility ports per D-013, D-017, D-032, D-033, ADR-015:
- AuthoritativeAssessmentHistoryReader (strict fail-closed provenance validation)
- AuthoritativeAssessmentWriter
- AuthoritativeEvaluationAuthority
- AuthoritativeSupplierDelayProcessor
- AuthoritativeImpactReader
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import CoreEventType
from app.core.models import AuditEventRecord
from app.core.schemas import (
    ConstraintReason,
    FeasibilityAssessment,
    FeasibilityState,
)

# Re-export unchanged adapters from feasibility
from app.feasibility.adapters import (
    AuthoritativeAssessmentWriter,
    AuthoritativeEvaluationAuthority,
    AuthoritativeImpactReader,
    AuthoritativeSupplierDelayProcessor,
)


class AuthoritativeAssessmentHistoryReader:
    """Read append-only versioned assessment history from AuditEventRecord with strict fail-closed provenance.

    Enforces ADR-015 and P3 Handoff P3-1 contract guarantees:
    - Never defaults missing assessment_id to audit_id.
    - Never defaults missing commitment_version or snapshot_version to 1.
    - Rejects advisory assessments (advisory=True) with ASSESSMENT_PROVENANCE_MISSING.
    - Fails closed with typed DomainError("ASSESSMENT_PROVENANCE_MISSING", ...) naming the missing field without PII.
    """

    @staticmethod
    def validate_provenance_payload(
        new_state: dict[str, Any],
        *,
        commitment_id: str,
        correlation_id: str | None = None,
    ) -> None:
        """Strictly validate assessment provenance fields; raises DomainError if missing or advisory."""
        if new_state.get("advisory") is True:
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISSING",
                "Assessment record is advisory and cannot be used as authoritative recovery provenance",
                status_code=422,
                details={"field": "advisory", "commitment_id": commitment_id},
                correlation_id=correlation_id,
            )

        if not new_state.get("assessment_id"):
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISSING",
                "Authoritative assessment record is missing required field: assessment_id",
                status_code=422,
                details={"field": "assessment_id", "commitment_id": commitment_id},
                correlation_id=correlation_id,
            )

        if new_state.get("commitment_version") is None:
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISSING",
                "Authoritative assessment record is missing required field: commitment_version",
                status_code=422,
                details={"field": "commitment_version", "commitment_id": commitment_id},
                correlation_id=correlation_id,
            )

        if new_state.get("snapshot_version") is None:
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISSING",
                "Authoritative assessment record is missing required field: snapshot_version",
                status_code=422,
                details={"field": "snapshot_version", "commitment_id": commitment_id},
                correlation_id=correlation_id,
            )

    def list_for_commitment(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
    ) -> list[FeasibilityAssessment]:
        """List all authoritative assessments for a commitment in chronological order."""
        audits = db.scalars(
            select(AuditEventRecord)
            .where(
                AuditEventRecord.tenant_id == context.tenant_id,
                AuditEventRecord.commitment_id == commitment_id,
                AuditEventRecord.event_type.in_([
                    CoreEventType.COMMITMENT_AT_RISK.value,
                    CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
                ]),
            )
            .order_by(AuditEventRecord.occurred_at.asc())
        ).all()

        results: list[FeasibilityAssessment] = []
        for a in audits:
            if not isinstance(a.new_state, dict):
                continue

            # Advisory assessments are never included in authoritative history (D-033)
            if a.new_state.get("advisory") is True:
                continue

            fa_status_str = a.new_state.get("feasibility_state") or (
                "INFEASIBLE" if a.event_type == CoreEventType.COMMITMENT_AT_RISK.value else None
            )
            if not fa_status_str:
                continue

            try:
                fa_status = FeasibilityState(fa_status_str)
            except ValueError:
                continue

            # Enforce fail-closed provenance validation on each candidate assessment
            self.validate_provenance_payload(
                a.new_state,
                commitment_id=commitment_id,
                correlation_id=context.correlation_id,
            )

            assessment_id = a.new_state["assessment_id"]
            commitment_version = a.new_state["commitment_version"]
            snapshot_version = a.new_state["snapshot_version"]

            constraints_raw = a.new_state.get("constraints") or []
            constraints = [
                ConstraintReason.model_validate(c) if isinstance(c, dict) else c
                for c in constraints_raw
            ]

            results.append(
                FeasibilityAssessment(
                    assessment_id=assessment_id,
                    tenant_id=a.tenant_id,
                    commitment_id=commitment_id,
                    commitment_version=commitment_version,
                    snapshot_version=snapshot_version,
                    status=fa_status,
                    constraints=constraints,
                    affected_commitment_ids=a.new_state.get("affected_commitment_ids", []),
                    evidence_refs=a.new_state.get("evidence_refs", a.evidence_refs or []),
                    solver_status=a.new_state.get("solver_status", "COMPLETED"),
                    assumptions=a.new_state.get("assumptions", []),
                    assessed_at=a.occurred_at if (a.occurred_at and a.occurred_at.tzinfo) else (a.occurred_at.replace(tzinfo=timezone.utc) if a.occurred_at else datetime.now(timezone.utc)),
                )
            )
        return results

    def get_assessment(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        assessment_id: str,
    ) -> FeasibilityAssessment:
        """Fetch a specific authoritative assessment by ID, failing closed if missing or invalid."""
        # Check raw audit records for explicit fail-closed error reporting
        audits = db.scalars(
            select(AuditEventRecord)
            .where(
                AuditEventRecord.tenant_id == context.tenant_id,
                AuditEventRecord.commitment_id == commitment_id,
            )
            .order_by(AuditEventRecord.occurred_at.desc())
        ).all()

        matching_audit: AuditEventRecord | None = None
        for a in audits:
            if isinstance(a.new_state, dict):
                if a.new_state.get("assessment_id") == assessment_id or a.audit_id == assessment_id:
                    matching_audit = a
                    break

        if matching_audit is not None and isinstance(matching_audit.new_state, dict):
            # Validate provenance on the found match; raises DomainError if advisory or missing fields
            self.validate_provenance_payload(
                matching_audit.new_state,
                commitment_id=commitment_id,
                correlation_id=context.correlation_id,
            )

        assessments = self.list_for_commitment(db, context, commitment_id)
        for fa in assessments:
            if fa.assessment_id == assessment_id:
                return fa

        raise DomainError(
            "ASSESSMENT_NOT_FOUND",
            "Authoritative assessment was not found",
            status_code=404,
            details={"commitment_id": commitment_id, "assessment_id": assessment_id},
            correlation_id=context.correlation_id,
        )


__all__ = [
    "AuthoritativeAssessmentHistoryReader",
    "AuthoritativeAssessmentWriter",
    "AuthoritativeEvaluationAuthority",
    "AuthoritativeImpactReader",
    "AuthoritativeSupplierDelayProcessor",
]
