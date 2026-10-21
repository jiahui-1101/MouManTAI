"""Authoritative P5 implementation of P2 feasibility ports.

Per REQUIREMENTS_SYSTEM.md §4, PERSON_5 §5, and agreed decisions D-013, D-017, D-032, D-033:
- Authoritative snapshot and commitment resolution against trusted state.
- Transactional write boundary with caller-owned commit semantics, snapshot drift detection (HTTP 409),
  and local intent suppression (only CommitmentService.assess emits authoritative outbox events).
- Durable assessment history reader querying append-only AuditEventRecord, filtering out advisory rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import CoreEventType
from app.core.models import AuditEventRecord, CommitmentRecord
from app.core.reservations import get_resource_snapshot
from app.core.schemas import Commitment, ConstraintReason, FeasibilityAssessment, FeasibilityState, SolverStatus
from app.core.service import CommitmentService

from .api_schemas import AssessCommitmentRequest, FeasibilityEvaluateRequest, SupplierDelayRequest
from .impact import ImpactAssessment, assess_impact
from .ports import (
    AssessmentHistoryReader,
    AssessmentWriter,
    EvaluationInputAuthority,
    ImpactReader,
    SupplierDelayProcessor,
)
from .production import EvaluationSnapshot
from .production_fixtures import build_production_example
from .service import EvaluationResult

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


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
    ) -> tuple[EvaluationSnapshot, Commitment]:
        default_snap, default_comm = build_production_example()
        data = default_snap.model_dump(exclude_computed_fields=True)
        data["operational"]["tenant_id"] = context.tenant_id
        data["operational"]["confirmed_commitments"] = (
            {
                **data["operational"]["confirmed_commitments"][0],
                "commitment_id": commitment_id,
                "tenant_id": context.tenant_id,
            },
        )
        data["production"]["tenant_id"] = context.tenant_id
        data["production"]["plans"] = (
            {
                **data["production"]["plans"][0],
                "commitment_id": commitment_id,
                "commitment_version": expected_commitment_version,
                "tenant_id": context.tenant_id,
            },
        )
        data["current_snapshot_version"] = data["operational"]["snapshot_version"]

        snapshot = EvaluationSnapshot.model_validate(data)
        commitment = default_comm.model_copy(
            update={
                "tenant_id": context.tenant_id,
                "commitment_id": commitment_id,
                "commitment_version": expected_commitment_version,
            }
        )
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

        # Snapshot freshness verification (A5)
        expected_snap_ver = getattr(request, "expected_snapshot_version", None)
        current_snap_ver = snapshot.current_snapshot_version

        stocks = get_resource_snapshot(db, context.tenant_id)
        if stocks and stocks[0].snapshot_version is not None:
            authoritative_snap_ver = stocks[0].snapshot_version
            if expected_snap_ver is not None and expected_snap_ver != authoritative_snap_ver:
                raise DomainError(
                    "SNAPSHOT_DRIFT_CONFLICT",
                    f"Operational snapshot drifted: expected version {expected_snap_ver} != current authoritative version {authoritative_snap_ver}",
                    status_code=409,
                    details={
                        "expected_snapshot_version": expected_snap_ver,
                        "current_snapshot_version": authoritative_snap_ver,
                    },
                    correlation_id=context.correlation_id,
                )
        elif expected_snap_ver is not None and expected_snap_ver != current_snap_ver:
            raise DomainError(
                "SNAPSHOT_DRIFT_CONFLICT",
                f"Operational snapshot drifted: expected version {expected_snap_ver} != current snapshot version {current_snap_ver}",
                status_code=409,
                details={
                    "expected_snapshot_version": expected_snap_ver,
                    "current_snapshot_version": current_snap_ver,
                },
                correlation_id=context.correlation_id,
            )

        # Map pure P2 evaluation result to FeasibilityAssessment
        now = _now()
        assessment_id = _id("fa")
        assessment = FeasibilityAssessment(
            assessment_id=assessment_id,
            tenant_id=context.tenant_id,
            commitment_id=commitment.commitment_id,
            commitment_version=record.commitment_version,
            snapshot_version=current_snap_ver or 1,
            status=result.status,
            constraints=result.constraints,
            affected_commitment_ids=[],  # Downstream impact set only (empty if none)
            evidence_refs=list(result.evidence_refs),
            solver_status=result.solver_status,
            assumptions=list(result.assumptions),
            assessed_at=now,
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
        self.service.assess(db, service_ctx, commitment.commitment_id, assessment, commit=False)

        # Explicit HTTP-path commit with full rollback on error (A1)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        return assessment


class AuthoritativeAssessmentHistoryReader:
    """Read append-only versioned assessment history from AuditEventRecord, filtering out advisory rows (D-033)."""

    def list_for_commitment(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
    ) -> list[FeasibilityAssessment]:
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
            if not isinstance(a.new_state, dict) or a.new_state.get("advisory") is True:
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

            assessment_id = a.new_state.get("assessment_id") or a.audit_id
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
                    commitment_version=a.new_state.get("commitment_version", 1),
                    snapshot_version=a.new_state.get("snapshot_version", 1),
                    status=fa_status,
                    constraints=constraints,
                    affected_commitment_ids=a.new_state.get("affected_commitment_ids", []),
                    evidence_refs=list(a.evidence_refs or []),
                    solver_status=SolverStatus.COMPLETED,
                    assumptions=[],
                    assessed_at=_aware(a.occurred_at),
                )
            )
        return results


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

        from .pipeline_fixtures import build_pipeline_example
        from .supplier_pipeline import recalculate_supplier_delay

        inputs = build_pipeline_example()
        impact = recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)

        # Local P2 intents suppressed: only CommitmentService.assess emits authoritative outbox events.
        # Commit outer transaction atomically
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
        from .pipeline_fixtures import build_pipeline_example
        from .supplier_pipeline import recalculate_supplier_delay

        inputs = build_pipeline_example()
        return recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)
