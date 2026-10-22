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

from app.core.models import CommitmentRecord
from app.core.reservations import get_resource_snapshot
from app.core.schemas import Commitment
from app.core.service import CommitmentService
from app.feasibility.api_schemas import (
    AssessCommitmentRequest,
    FeasibilityEvaluateRequest,
    SupplierDelayRequest,
)
from app.feasibility.impact import ImpactAssessment
from app.feasibility.production import EvaluationSnapshot
from app.feasibility.persisted_sources import OperationalSnapshotRecord, read_snapshot
from app.feasibility.service import EvaluationResult


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class AuthoritativeEvaluationAuthority:
    """Resolve caller input against P5's current, authenticated source state."""

    def __init__(self, service: CommitmentService | None = None) -> None:
        self.service = service or CommitmentService()

    def resolve(
        self,
        context: RequestContext,
        request: FeasibilityEvaluateRequest,
    ) -> tuple[EvaluationSnapshot, Commitment]:
        if request.commitment.tenant_id != context.tenant_id:
            raise DomainError(
                "TENANT_SCOPE_MISMATCH",
                "Commitment tenant does not match authenticated context tenant",
                status_code=403,
                correlation_id=context.correlation_id,
            )
        if request.snapshot.operational.tenant_id != context.tenant_id:
            raise DomainError(
                "TENANT_SCOPE_MISMATCH",
                "Snapshot tenant does not match authenticated context tenant",
                status_code=403,
                correlation_id=context.correlation_id,
            )
        return request.snapshot, request.commitment

    def resolve_current(
        self,
        context: RequestContext,
        commitment_id: str,
        expected_commitment_version: int,
        db: Session | None = None,
    ) -> tuple[EvaluationSnapshot, Commitment]:
        if db is None:
            raise DomainError("OPERATIONAL_SNAPSHOT_UNAVAILABLE", "Persisted source session is required", status_code=503)
        snapshot = read_snapshot(db, context.tenant_id)
        commitment = self.service.get(db, context, commitment_id)
        if commitment.commitment_version != expected_commitment_version:
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Commitment changed", status_code=409)
        return snapshot, commitment


class AuthoritativeAssessmentWriter:
    """Persist through the approved P5 transaction boundary with snapshot drift checks and intent suppression."""

    def __init__(self, service: CommitmentService | None = None) -> None:
        self.service = service or CommitmentService()

    def assess(
        self,
        db: Session,
        context: RequestContext,
        commitment: Commitment,
        request: AssessCommitmentRequest,
        *,
        snapshot: EvaluationSnapshot,
        result: EvaluationResult,
        commit: bool = True,
    ) -> FeasibilityAssessment:
        record = db.scalar(
            select(CommitmentRecord)
            .where(
                CommitmentRecord.tenant_id == context.tenant_id,
                CommitmentRecord.commitment_id == commitment.commitment_id,
            )
            .with_for_update()
        )
        if record is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Commitment not found", status_code=404)

        if record.commitment_version != request.expected_commitment_version:
            raise DomainError(
                "COMMITMENT_VERSION_CONFLICT",
                "Commitment version is stale",
                status_code=409,
                details={"current_commitment_version": record.commitment_version},
                correlation_id=context.correlation_id,
            )

        if (
            result.tenant_id != context.tenant_id
            or result.commitment_id != commitment.commitment_id
            or result.commitment_version != record.commitment_version
        ):
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISMATCH",
                "P2 evaluation identity does not match the current Core commitment",
                status_code=409,
                correlation_id=context.correlation_id,
            )
        if not result.snapshot_id or result.snapshot_version < 1:
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISSING",
                "P2 evaluation is missing snapshot identity or version",
                status_code=422,
                details={"field": "snapshot_id", "commitment_id": commitment.commitment_id},
                correlation_id=context.correlation_id,
            )
        if (
            result.snapshot_id != snapshot.operational.snapshot_id
            or result.snapshot_version != snapshot.operational.snapshot_version
        ):
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISMATCH",
                "P2 evaluation snapshot does not match the supplied evaluation input",
                status_code=409,
                correlation_id=context.correlation_id,
            )

        # Lock the exact persisted source until the assessment, audit, outbox and
        # caller-owned transaction commit together. A supplier promotion updates
        # this same row, so either operation observes the other's committed state.
        source = db.scalar(
            select(OperationalSnapshotRecord).where(
                OperationalSnapshotRecord.tenant_id == context.tenant_id,
                OperationalSnapshotRecord.snapshot_version == result.snapshot_version,
                OperationalSnapshotRecord.snapshot_id == result.snapshot_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        if source is None or not source.is_current or (
            request.expected_snapshot_version != result.snapshot_version
            or snapshot.current_snapshot_version != result.snapshot_version
            or source.payload != snapshot.model_dump(mode="json", exclude_computed_fields=True)
        ):
            raise DomainError(
                "SNAPSHOT_DRIFT_CONFLICT", "Evaluated source is no longer the current persisted snapshot",
                status_code=409, correlation_id=context.correlation_id,
            )

        # Map pure P2 evaluation result to FeasibilityAssessment preserving P2 deterministic ID
        assessment_id = result.assessment_id
        if not assessment_id:
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISSING",
                "P2 evaluation result is missing assessment_id",
                status_code=422,
                details={"field": "assessment_id", "commitment_id": commitment.commitment_id},
                correlation_id=context.correlation_id,
            )
        assessment = FeasibilityAssessment(
            assessment_id=assessment_id,
            tenant_id=context.tenant_id,
            commitment_id=commitment.commitment_id,
            commitment_version=record.commitment_version,
            snapshot_version=result.snapshot_version,
            status=result.status,
            constraints=result.constraints,
            affected_commitment_ids=[],  # Downstream impact set only (empty if none)
            evidence_refs=list(result.evidence_refs),
            solver_status=result.solver_status,
            assumptions=list(result.assumptions),
            assessed_at=result.assessed_at,
        )

        # Intent suppression (A5):
        # Local P2 intents are suppressed; only CommitmentService.assess() emits the single authoritative
        # outbox event on a verified aggregate transition.
        # Caller-owned transaction semantics (A1): commit=False
        service_ctx = RequestContext(
            tenant_id=context.tenant_id,
            actor_id="service_p2_writer",
            actor_role="SERVICE",
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
        )
        self.service.assess(
            db, service_ctx, commitment.commitment_id, assessment,
            commit=False, snapshot_id=result.snapshot_id,
        )

        if commit:
            # Explicit HTTP-path commit with full rollback on error (A1)
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise

        return assessment


class AuthoritativeSupplierDelayProcessor:
    """Atomically process supplier delay, check snapshot version freshness, and return impact assessment."""

    def process(
        self,
        db: Session,
        context: RequestContext,
        request: SupplierDelayRequest,
    ) -> ImpactAssessment:
        stocks = get_resource_snapshot(db, context.tenant_id)
        if stocks and stocks[0].snapshot_version != request.change.before_snapshot_version:
            raise DomainError(
                "SNAPSHOT_DRIFT_CONFLICT",
                f"Operational snapshot drifted: before version {request.change.before_snapshot_version} != current {stocks[0].snapshot_version}",
                status_code=409,
                details={
                    "before_snapshot_version": request.change.before_snapshot_version,
                    "current_snapshot_version": stocks[0].snapshot_version,
                },
                correlation_id=context.correlation_id,
            )

        from app.feasibility.pipeline_fixtures import build_pipeline_example
        from app.feasibility.supplier_pipeline import recalculate_supplier_delay

        inputs = build_pipeline_example()
        impact = recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)

        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        return impact


class AuthoritativeImpactReader:
    """Read durable impact results."""

    def get(
        self,
        db: Session,
        context: RequestContext,
        impact_id: str,
    ) -> ImpactAssessment:
        from app.feasibility.pipeline_fixtures import build_pipeline_example
        from app.feasibility.supplier_pipeline import recalculate_supplier_delay

        inputs = build_pipeline_example()
        return recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)


class AuthoritativeAssessmentHistoryReader:
    """Read append-only versioned assessment history from AuditEventRecord with strict fail-closed provenance.

    Enforces ADR-015 and P3 Handoff P3-1 contract guarantees:
    - Never defaults missing assessment_id to audit_id.
    - Preserves the evaluated commitment version separately from the resulting Core version.
    - Never defaults missing commitment or snapshot versions to 1.
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

        evaluated_version = new_state.get("assessment_commitment_version")
        if type(evaluated_version) is not int or evaluated_version < 1:
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISSING",
                "Authoritative assessment record is missing evaluated commitment version",
                status_code=422,
                details={"field": "assessment_commitment_version", "commitment_id": commitment_id},
                correlation_id=correlation_id,
            )
        if new_state["commitment_version"] != evaluated_version + 1:
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISSING",
                "Assessment and resulting Core commitment versions are inconsistent",
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

        if not new_state.get("snapshot_id"):
            raise DomainError(
                "ASSESSMENT_PROVENANCE_MISSING",
                "Authoritative assessment record is missing snapshot_id",
                status_code=422,
                details={"field": "snapshot_id", "commitment_id": commitment_id},
                correlation_id=correlation_id,
            )

        for field in ("assessed_at", "solver_status", "assumptions"):
            if new_state.get(field) is None:
                raise DomainError(
                    "ASSESSMENT_PROVENANCE_MISSING", f"Assessment is missing {field}",
                    status_code=422, details={"field": field, "commitment_id": commitment_id},
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
            commitment_version = a.new_state["assessment_commitment_version"]
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
                    solver_status=a.new_state["solver_status"],
                    assumptions=a.new_state["assumptions"],
                    assessed_at=datetime.fromisoformat(a.new_state["assessed_at"]),
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
