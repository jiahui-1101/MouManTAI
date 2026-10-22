"""P5 persisted source adapter for P2's confirmed-event consumer.

The adapter uses the dispatcher's Session and never commits or rolls back. Its
lock order is Commitment row first, then the tenant's current snapshot row; the
P2 writer follows the same order and revalidates both before staging an audit.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import CommitmentRecord
from app.core.service import CommitmentService
from app.feasibility.consumer import TrustedCurrentEvaluationInput
from app.feasibility.persisted_sources import OperationalSnapshotRecord
from app.feasibility.production import EvaluationSnapshot


class PersistedConfirmedEventSourceProvider:
    """Resolve only the tenant's locked, persisted current Commitment and snapshot."""

    @staticmethod
    def _context(tenant_id: str) -> RequestContext:
        return RequestContext(
            tenant_id=tenant_id,
            actor_id="service_p2_confirmed_evaluator",
            actor_role="SERVICE",
            correlation_id="p2-confirmed-source",
        )

    def resolve_current(
        self,
        session: Session,
        tenant_id: str,
        commitment_id: str,
        commitment_version: int,
    ) -> TrustedCurrentEvaluationInput:
        commitment_row = session.scalar(
            select(CommitmentRecord)
            .where(
                CommitmentRecord.tenant_id == tenant_id,
                CommitmentRecord.commitment_id == commitment_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if commitment_row is None or commitment_row.commitment_version != commitment_version:
            raise DomainError(
                "P2_OPERATIONAL_SOURCE_BINDING_MISMATCH",
                "Persisted Commitment is absent or has changed",
                status_code=409,
            )

        rows = session.scalars(
            select(OperationalSnapshotRecord)
            .where(
                OperationalSnapshotRecord.tenant_id == tenant_id,
                OperationalSnapshotRecord.is_current.is_(True),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        if len(rows) != 1:
            raise DomainError(
                "OPERATIONAL_SNAPSHOT_UNAVAILABLE",
                "Exactly one persisted current operational snapshot is required",
                status_code=503,
            )
        row = rows[0]
        try:
            snapshot = EvaluationSnapshot.model_validate(row.payload)
            context = self._context(tenant_id)
            commitment = CommitmentService().get(session, context, commitment_id)
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError(
                "OPERATIONAL_SNAPSHOT_CORRUPT",
                "Persisted operational snapshot or Commitment is invalid",
                status_code=503,
            ) from exc

        op = snapshot.operational
        if (
            row.tenant_id != tenant_id
            or op.tenant_id != tenant_id
            or row.snapshot_id != op.snapshot_id
            or row.snapshot_version != op.snapshot_version
            or snapshot.current_snapshot_version != row.snapshot_version
            or commitment.tenant_id != tenant_id
            or commitment.commitment_id != commitment_id
            or commitment.commitment_version != commitment_version
        ):
            raise DomainError(
                "OPERATIONAL_SNAPSHOT_BINDING_MISMATCH",
                "Persisted snapshot and Commitment identities do not match the confirmed event scope",
                status_code=409,
            )

        evidence_refs = [
            ref
            for source in op.sources
            for ref in source.evidence_refs
        ]
        if snapshot.production is not None:
            evidence_refs.extend(
                ref
                for source in snapshot.production.sources
                for ref in source.evidence_refs
            )
        if not evidence_refs or len(evidence_refs) != len(set(evidence_refs)):
            raise DomainError(
                "P2_OPERATIONAL_SOURCE_EVIDENCE_MISSING",
                "Persisted current snapshot has missing or duplicate source evidence",
                status_code=503,
            )

        return TrustedCurrentEvaluationInput(
            snapshot=snapshot,
            commitment=commitment,
            source_mode="PERSISTED_OPERATIONAL",
            source_evidence_refs=tuple(evidence_refs),
        )

    def validate_current(
        self,
        session: Session,
        tenant_id: str,
        snapshot_id: str,
        snapshot_version: int,
    ) -> None:
        row = session.scalar(
            select(OperationalSnapshotRecord)
            .where(
                OperationalSnapshotRecord.tenant_id == tenant_id,
                OperationalSnapshotRecord.snapshot_id == snapshot_id,
                OperationalSnapshotRecord.snapshot_version == snapshot_version,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or not row.is_current:
            raise DomainError(
                "SNAPSHOT_VERSION_CONFLICT",
                "Operational snapshot is no longer the current persisted version",
                status_code=409,
            )
        self._validate_snapshot_row(row, tenant_id, snapshot_id, snapshot_version)

    @staticmethod
    def _validate_snapshot_row(
        row: OperationalSnapshotRecord,
        tenant_id: str,
        snapshot_id: str,
        snapshot_version: int,
    ) -> None:
        try:
            snapshot = EvaluationSnapshot.model_validate(row.payload)
        except Exception as exc:
            raise DomainError(
                "OPERATIONAL_SNAPSHOT_CORRUPT",
                "Persisted operational snapshot is invalid",
                status_code=503,
            ) from exc
        if (
            row.tenant_id != tenant_id
            or row.snapshot_id != snapshot_id
            or row.snapshot_version != snapshot_version
            or snapshot.operational.tenant_id != tenant_id
            or snapshot.operational.snapshot_id != snapshot_id
            or snapshot.operational.snapshot_version != snapshot_version
            or snapshot.current_snapshot_version != snapshot_version
        ):
            raise DomainError(
                "OPERATIONAL_SNAPSHOT_BINDING_MISMATCH",
                "Persisted operational snapshot identity changed",
                status_code=409,
            )
