"""Tenant-scoped, versioned operational inputs for isolated P2 integration.

Snapshots contain typed P2 material, inventory, supplier ETA and production facts.
The immutable payload is validated on every read. No fixture is used as a fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, Index, Integer, JSON, String, UniqueConstraint, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import CommitmentRecord, OutboxEventRecord
from app.core.schemas import Commitment
from app.core.service import CommitmentService
from app.db.base import Base

from .api_schemas import FeasibilityEvaluateRequest, SupplierDelayRequest
from .impact import ImpactAssessment
from .history import to_core_assessment
from .production import EvaluationSnapshot
from .supplier_pipeline import SupplierDelayInputs, recalculate_supplier_delay


class OperationalSnapshotRecord(Base):
    __tablename__ = "p2_operational_snapshots"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "snapshot_id", name="uq_p2_snapshot_identity"),)


Index(
    "uq_p2_one_current_snapshot", OperationalSnapshotRecord.tenant_id, unique=True,
    postgresql_where=text("is_current"), sqlite_where=text("is_current = 1"),
)


def _snapshot_from_record(row: OperationalSnapshotRecord) -> EvaluationSnapshot:
    try:
        snapshot = EvaluationSnapshot.model_validate(row.payload)
    except Exception as exc:
        raise DomainError(
            "OPERATIONAL_SNAPSHOT_CORRUPT",
            "Persisted operational snapshot is invalid",
            status_code=500,
        ) from exc
    if (
        snapshot.operational.tenant_id,
        snapshot.operational.snapshot_id,
        snapshot.operational.snapshot_version,
    ) != (row.tenant_id, row.snapshot_id, row.snapshot_version):
        raise DomainError(
            "OPERATIONAL_SNAPSHOT_CORRUPT",
            "Snapshot payload identity mismatch",
            status_code=500,
        )
    return snapshot


class SupplierDelayEventRecord(Base):
    __tablename__ = "p2_supplier_delay_events"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    before_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    after_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    impact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    impact_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "before_snapshot_version"],
            ["p2_operational_snapshots.tenant_id", "p2_operational_snapshots.snapshot_version"],
            name="fk_p2_delay_before_snapshot", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "after_snapshot_version"],
            ["p2_operational_snapshots.tenant_id", "p2_operational_snapshots.snapshot_version"],
            name="fk_p2_delay_after_snapshot", ondelete="RESTRICT",
        ),
    )


def stage_snapshot(
    db: Session, snapshot: EvaluationSnapshot, *, current: bool = False,
) -> OperationalSnapshotRecord:
    """Stage a complete synthetic source snapshot; caller owns transaction and provenance."""
    op = snapshot.operational
    if snapshot.current_snapshot_version != op.snapshot_version:
        raise DomainError("SNAPSHOT_VERSION_CONFLICT", "Snapshot version fields disagree", status_code=409)
    previous = db.scalar(select(OperationalSnapshotRecord).where(
        OperationalSnapshotRecord.tenant_id == op.tenant_id,
    ).order_by(OperationalSnapshotRecord.snapshot_version.desc()).limit(1))
    if previous is not None and op.snapshot_version <= previous.snapshot_version:
        raise DomainError("SNAPSHOT_VERSION_CONFLICT", "Snapshot version must advance", status_code=409)
    if current and previous is not None:
        raise DomainError("SNAPSHOT_CURRENT_CONFLICT", "Use a supplier change to advance current source", status_code=409)
    record = OperationalSnapshotRecord(
        tenant_id=op.tenant_id, snapshot_version=op.snapshot_version,
        snapshot_id=op.snapshot_id, payload=snapshot.model_dump(mode="json", exclude_computed_fields=True),
        is_current=current, created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.flush()
    return record


def read_snapshot(db: Session, tenant_id: str, version: int | None = None) -> EvaluationSnapshot:
    stmt = select(OperationalSnapshotRecord).where(OperationalSnapshotRecord.tenant_id == tenant_id)
    stmt = stmt.where(
        OperationalSnapshotRecord.is_current.is_(True) if version is None
        else OperationalSnapshotRecord.snapshot_version == version
    )
    rows = db.scalars(stmt).all()
    if len(rows) != 1:
        raise DomainError("OPERATIONAL_SNAPSHOT_UNAVAILABLE", "One trusted snapshot is required", status_code=503)
    return _snapshot_from_record(rows[0])


class PersistedEvaluationAuthority:
    """Resolve the current P2 input from the same request transaction as Core."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.service = CommitmentService()

    def resolve_current(
        self, context: RequestContext, commitment_id: str, expected_commitment_version: int,
    ) -> tuple[EvaluationSnapshot, Commitment]:
        snapshot = read_snapshot(self.db, context.tenant_id)
        commitment = self.service.get(self.db, context, commitment_id)
        if commitment.commitment_version != expected_commitment_version:
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Commitment changed", status_code=409)
        return snapshot, commitment

    def resolve(
        self, context: RequestContext, request: FeasibilityEvaluateRequest,
    ) -> tuple[EvaluationSnapshot, Commitment]:
        snapshot, commitment = self.resolve_current(
            context, request.commitment.commitment_id, request.commitment.commitment_version,
        )
        if snapshot.model_dump(mode="json", exclude_computed_fields=True) != request.snapshot.model_dump(
            mode="json", exclude_computed_fields=True,
        ):
            raise DomainError("EVALUATION_INPUT_VERSION_CONFLICT", "Snapshot differs from persisted source", status_code=409)
        return snapshot, commitment


class PersistedSupplierDelayProcessor:
    """Promote a staged snapshot with the shared Commitment -> Snapshot lock order.

    Core confirmed-event assessment locks a Commitment before its current source
    snapshot. This path must use the same order: all affected tenant Commitments
    sorted by ID, followed by the before/after snapshot rows sorted by version.
    The snapshot payload read used to discover the Commitment IDs is deliberately
    unlocked and is revalidated after both lock sets are acquired.
    """

    @staticmethod
    def _prior_event(
        db: Session, tenant_id: str, event_id: str, event_digest: str,
    ) -> ImpactAssessment | None:
        prior = db.scalar(select(SupplierDelayEventRecord).where(
            SupplierDelayEventRecord.tenant_id == tenant_id,
            SupplierDelayEventRecord.event_id == event_id,
        ).execution_options(populate_existing=True))
        if prior is None:
            return None
        if prior.event_digest != event_digest:
            raise DomainError("SUPPLIER_EVENT_ID_CONFLICT", "Event ID has different content", status_code=409)
        return ImpactAssessment.model_validate(prior.impact_payload)

    def process(
        self, db: Session, context: RequestContext, request: SupplierDelayRequest,
    ) -> ImpactAssessment:
        change = request.change
        if change.tenant_id != context.tenant_id:
            raise DomainError("TENANT_SCOPE_MISMATCH", "Supplier event tenant mismatch", status_code=403)
        digest = sha256(json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        with db.no_autoflush:
            prior = self._prior_event(db, context.tenant_id, change.event_id, digest)
        if prior is not None:
            return prior

        # This first read is only a lock-set hint. Do not autoflush unrelated ORM
        # work before the shared lock order, and do not use these rows for the
        # calculation after waiting on another transaction.
        with db.no_autoflush:
            before_candidate = db.scalar(select(OperationalSnapshotRecord).where(
                OperationalSnapshotRecord.tenant_id == context.tenant_id,
                OperationalSnapshotRecord.snapshot_version == change.before_snapshot_version,
            ).execution_options(populate_existing=True))
            after_candidate = db.scalar(select(OperationalSnapshotRecord).where(
                OperationalSnapshotRecord.tenant_id == context.tenant_id,
                OperationalSnapshotRecord.snapshot_version == change.after_snapshot_version,
            ).execution_options(populate_existing=True))
            if before_candidate is None or after_candidate is None:
                raise DomainError(
                    "SNAPSHOT_DRIFT_CONFLICT",
                    "Expected current BEFORE and staged AFTER snapshots",
                    status_code=409,
                )
            before_hint = _snapshot_from_record(before_candidate)
            commitment_ids = tuple(sorted({
                row.commitment_id for row in before_hint.operational.confirmed_commitments
            }))

            # Lock every Commitment the before snapshot can send to Core in a
            # deterministic order before taking either source row lock.
            locked_commitments = db.scalars(
                select(CommitmentRecord)
                .where(
                    CommitmentRecord.tenant_id == context.tenant_id,
                    CommitmentRecord.commitment_id.in_(commitment_ids),
                )
                .order_by(CommitmentRecord.commitment_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all() if commitment_ids else []
            locked_commitment_ids = {row.commitment_id for row in locked_commitments}
            if locked_commitment_ids != set(commitment_ids):
                raise DomainError(
                    "COMMITMENT_VERSION_CONFLICT",
                    "A Commitment referenced by the current source is unavailable",
                    status_code=409,
                )

            # A concurrent identical delivery may have committed while this
            # transaction waited on Commitment locks. Return its durable result.
            prior = self._prior_event(db, context.tenant_id, change.event_id, digest)
            if prior is not None:
                return prior

            snapshot_rows = db.scalars(
                select(OperationalSnapshotRecord)
                .where(
                    OperationalSnapshotRecord.tenant_id == context.tenant_id,
                    OperationalSnapshotRecord.snapshot_version.in_((
                        change.before_snapshot_version,
                        change.after_snapshot_version,
                    )),
                )
                .order_by(OperationalSnapshotRecord.snapshot_version)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
            # Empty-impact snapshots have no Commitment row to serialize two
            # identical deliveries. Recheck after acquiring the source lock too.
            prior = self._prior_event(db, context.tenant_id, change.event_id, digest)
            if prior is not None:
                return prior

        snapshots_by_version = {row.snapshot_version: row for row in snapshot_rows}
        before_record = snapshots_by_version.get(change.before_snapshot_version)
        after_record = snapshots_by_version.get(change.after_snapshot_version)
        if (
            before_record is None
            or after_record is None
            or not before_record.is_current
            or after_record.is_current
        ):
            raise DomainError(
                "SNAPSHOT_DRIFT_CONFLICT",
                "Expected current BEFORE and staged AFTER snapshots",
                status_code=409,
            )
        before = _snapshot_from_record(before_record)
        after = _snapshot_from_record(after_record)
        old_delivery = next((row for row in before.operational.incoming_deliveries
                             if row.delivery_id == request.source_evidence.delivery_id), None)
        new_delivery = next((row for row in after.operational.incoming_deliveries
                             if row.delivery_id == request.source_evidence.delivery_id), None)
        if old_delivery is None or new_delivery is None:
            raise DomainError("SUPPLIER_SOURCE_MISSING", "Supplier delivery missing from versioned source", status_code=422)
        commitments = tuple(self._load_commitment(db, context, row.commitment_id)
                            for row in before.operational.confirmed_commitments)
        for source_row, commitment in zip(before.operational.confirmed_commitments, commitments):
            line = source_row.lines[0] if len(source_row.lines) == 1 else None
            if line is None or (
                commitment.commitment_version != source_row.commitment_version
                or commitment.agreement_state.value != "CONFIRMED"
                or (commitment.terms.sku, commitment.terms.quantity, commitment.terms.unit,
                    commitment.terms.deadline) !=
                (line.sku_id, line.quantity, line.unit, source_row.delivery_deadline)
            ):
                raise DomainError(
                    "COMMITMENT_VERSION_CONFLICT", "Core commitment differs from operational source",
                    status_code=409,
                )
        inputs = SupplierDelayInputs(
            request=request,
            before_snapshot_id=before.operational.snapshot_id,
            after_snapshot_id=after.operational.snapshot_id,
            previous_eta=old_delivery.expected_at,
            updated_eta=new_delivery.expected_at,
            before=before, after=after,
            before_commitments=commitments, after_commitments=commitments,
        )
        try:
            impact = recalculate_supplier_delay(inputs, tenant_id=context.tenant_id)
        except ValueError as exc:
            raise DomainError("SUPPLIER_SOURCE_CONFLICT", str(exc), status_code=409) from exc
        if not {row.commitment_id for row in impact.impacts}.issubset(locked_commitment_ids):
            raise DomainError(
                "SUPPLIER_IMPACT_SCOPE_MISMATCH",
                "P2 impact calculation returned a Commitment outside the locked source scope",
                status_code=409,
            )
        before_record.is_current = False
        db.flush()
        after_record.is_current = True
        db.add(SupplierDelayEventRecord(
            tenant_id=context.tenant_id, event_id=change.event_id,
            before_snapshot_version=change.before_snapshot_version,
            after_snapshot_version=change.after_snapshot_version,
            evidence_ref=request.source_evidence.evidence_ref,
            impact_id=impact.impact_id, impact_payload=impact.model_dump(mode="json"),
            event_digest=digest, occurred_at=change.occurred_at,
        ))
        db.add(OutboxEventRecord(
            event_id=change.event_id, tenant_id=context.tenant_id,
            event_type=change.event_type.value, commitment_id=None, commitment_version=None,
            correlation_id=change.correlation_id, causation_id=None,
            occurred_at=change.occurred_at,
            payload={
                "before_snapshot_id": before.operational.snapshot_id,
                "before_snapshot_version": change.before_snapshot_version,
                "after_snapshot_id": after.operational.snapshot_id,
                "after_snapshot_version": change.after_snapshot_version,
                "evidence_refs": list(change.evidence_refs),
                "impact_id": impact.impact_id,
            },
            status="PENDING", attempts=0,
        ))
        service_context = RequestContext(
            tenant_id=context.tenant_id, actor_id="service_p2_supplier_delay", actor_role="SERVICE",
            correlation_id=change.correlation_id, causation_id=change.event_id,
        )
        try:
            service = CommitmentService()
            for row in impact.impacts:
                if row.after_assessment is None:
                    continue
                assessment = to_core_assessment(row.after_assessment, impact=impact)
                service.assess(
                    db, service_context, row.commitment_id, assessment,
                    commit=False, snapshot_id=after.operational.snapshot_id,
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        return impact

    @staticmethod
    def _load_commitment(db: Session, context: RequestContext, commitment_id: str) -> Commitment:
        return CommitmentService().get(db, context, commitment_id)


class PersistedImpactReader:
    def get(self, db: Session, context: RequestContext, impact_id: str) -> ImpactAssessment:
        rows = db.scalars(select(SupplierDelayEventRecord).where(
            SupplierDelayEventRecord.tenant_id == context.tenant_id,
            SupplierDelayEventRecord.impact_id == impact_id,
        )).all()
        if len(rows) != 1:
            raise DomainError("IMPACT_NOT_FOUND", "Impact not found", status_code=404)
        return ImpactAssessment.model_validate(rows[0].impact_payload)
