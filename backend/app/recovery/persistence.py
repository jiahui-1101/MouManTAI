"""P3-owned SQLAlchemy mappings and transaction-scoped Recovery Case storage.

The mappings are a migration proposal: P5 owns the Alembic migration and must
review the cross-module foreign keys and active-case index before deployment.
This repository only flushes through the caller's Session; the outbox dispatcher
must commit the case/history rows together with its ProcessedEventRecord.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.errors import DomainError
from app.core.models import CommitmentRecord
from app.core.schemas import Commitment, ConstraintReason
from app.db.base import Base

from .models import (
    RecoveryCase,
    RecoveryCaseStatus,
    RecoveryResolutionReference,
    RecoveryTriggerReference,
)

# A case remains active until the risk episode is authoritatively resolved.
# NO_SAFE_PLAN is deliberately active: it still needs escalation/recovery.
ACTIVE_CASE_STATUSES = (
    RecoveryCaseStatus.OPEN.value,
    RecoveryCaseStatus.AWAITING_EVALUATION_INPUTS.value,
    RecoveryCaseStatus.OPTIONS_READY.value,
    RecoveryCaseStatus.NO_SAFE_PLAN.value,
    RecoveryCaseStatus.NEEDS_REPLAN.value,
)

_ACTIVE_CASE_SQL = "status IN (" + ", ".join(f"'{status}'" for status in ACTIVE_CASE_STATUSES) + ")"
_CASE_STATUS_SQL = "status IN (" + ", ".join(f"'{status.value}'" for status in RecoveryCaseStatus) + ")"


class RecoveryCaseRecord(Base):
    """Durable scalar/index columns plus the versioned P3 aggregate payload."""

    __tablename__ = "recovery_cases"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    commitment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_episode_id: Mapped[str] = mapped_column(String(128), nullable=False)
    opening_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    commitment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    case_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resolution_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolution_commitment_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "commitment_id"],
            ["commitments.tenant_id", "commitments.commitment_id"],
            name="fk_recovery_cases_commitment_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "risk_episode_id", name="uq_recovery_cases_tenant_episode"),
        UniqueConstraint(
            "tenant_id", "case_id", "commitment_id", name="uq_recovery_cases_tenant_case_commitment"
        ),
        CheckConstraint("case_version >= 1", name="ck_recovery_cases_case_version_positive"),
        CheckConstraint("commitment_version >= 1", name="ck_recovery_cases_commitment_version_positive"),
        CheckConstraint("payload_schema_version >= 1", name="ck_recovery_cases_payload_version_positive"),
        CheckConstraint(_CASE_STATUS_SQL, name="ck_recovery_cases_status_valid"),
        Index("ix_recovery_cases_tenant_status_updated", "tenant_id", "status", "updated_at"),
        Index("ix_recovery_cases_tenant_commitment_created", "tenant_id", "commitment_id", "created_at"),
    )


Index(
    "uq_recovery_cases_one_active_per_commitment",
    RecoveryCaseRecord.tenant_id,
    RecoveryCaseRecord.commitment_id,
    unique=True,
    postgresql_where=text(_ACTIVE_CASE_SQL),
    sqlite_where=text(_ACTIVE_CASE_SQL),
)


class RecoveryCaseTriggerRecord(Base):
    """Append-only provenance row for each accepted at-risk trigger event."""

    __tablename__ = "recovery_case_triggers"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    assessment_commitment_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assessment_provenance_status: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    constraints: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    affected_commitment_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "commitment_id"],
            ["commitments.tenant_id", "commitments.commitment_id"],
            name="fk_recovery_case_triggers_commitment_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "case_id", "commitment_id"],
            [
                "recovery_cases.tenant_id",
                "recovery_cases.case_id",
                "recovery_cases.commitment_id",
            ],
            name="fk_recovery_case_triggers_case_tenant_commitment",
            ondelete="RESTRICT",
        ),
        CheckConstraint("commitment_version >= 1", name="ck_recovery_triggers_commitment_version_positive"),
        CheckConstraint("snapshot_version >= 1", name="ck_recovery_triggers_snapshot_version_positive"),
        Index("ix_recovery_triggers_tenant_case_time", "tenant_id", "case_id", "occurred_at"),
        Index(
            "ix_recovery_triggers_tenant_commitment_assessment",
            "tenant_id",
            "commitment_id",
            "assessment_id",
        ),
    )


class SqlAlchemyRecoveryRepository:
    """Caller-session repository; never commits or rolls back its Session."""

    durable = True

    @staticmethod
    def _digest(trigger: RecoveryTriggerReference) -> str:
        canonical = json.dumps(
            trigger.model_dump(mode="json", exclude={"source_event_digest"}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _case_payload(case: RecoveryCase) -> dict[str, Any]:
        durable_case = case.model_copy(update={"storage_mode": "DURABLE_DATABASE"})
        return durable_case.model_dump(mode="json")

    @classmethod
    def _case_from_record(cls, record: RecoveryCaseRecord) -> RecoveryCase:
        if record.payload_schema_version != 1:
            raise DomainError(
                "RECOVERY_CASE_SCHEMA_UNSUPPORTED",
                "Persisted Recovery Case payload schema is unsupported",
                status_code=500,
            )
        try:
            case = RecoveryCase.model_validate(record.case_payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise DomainError(
                "RECOVERY_CASE_INTEGRITY_ERROR",
                "Persisted Recovery Case payload is invalid",
                status_code=500,
            ) from exc
        if (record.tenant_id, record.case_id, record.commitment_id) != (
            case.tenant_id,
            case.case_id,
            case.commitment_id,
        ):
            raise DomainError(
                "RECOVERY_CASE_IDENTITY_CONFLICT",
                "Persisted Recovery Case identity does not match its indexed row identity",
                status_code=500,
            )
        if (
            record.status != case.status.value
            or record.case_version != case.case_version
            or record.commitment_version != case.commitment_version
            or not record.risk_episode_id
            or not record.opening_event_id
            or (case.commitment.tenant_id, case.commitment.commitment_id)
            != (record.tenant_id, record.commitment_id)
            or case.commitment.commitment_version != case.commitment_version
            or case.storage_mode != "DURABLE_DATABASE"
        ):
            raise DomainError(
                "RECOVERY_CASE_INTEGRITY_ERROR",
                "Persisted Recovery Case columns contradict its payload",
                status_code=500,
            )
        if record.resolution_refs != [item.model_dump(mode="json") for item in case.resolution_events]:
            raise DomainError(
                "RECOVERY_CASE_INTEGRITY_ERROR",
                "Persisted Recovery Case resolution history contradicts its payload",
                status_code=500,
            )
        if case.resolution_events:
            latest = case.resolution_events[-1]
            if (record.resolution_event_id, record.resolution_commitment_version) != (
                latest.event_id,
                latest.commitment_version,
            ):
                raise DomainError(
                    "RECOVERY_CASE_INTEGRITY_ERROR",
                    "Persisted Recovery Case resolution identity is inconsistent",
                    status_code=500,
                )
        elif record.resolution_event_id is not None or record.resolution_commitment_version is not None:
            raise DomainError(
                "RECOVERY_CASE_INTEGRITY_ERROR",
                "Persisted Recovery Case resolution identity is inconsistent",
                status_code=500,
            )
        return case.model_copy(update={"storage_mode": "DURABLE_DATABASE"})

    @classmethod
    def _trigger_from_record(cls, record: RecoveryCaseTriggerRecord) -> RecoveryTriggerReference:
        try:
            occurred_at = record.occurred_at
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=UTC)
            trigger = RecoveryTriggerReference(
                event_id=record.event_id,
                tenant_id=record.tenant_id,
                commitment_id=record.commitment_id,
                commitment_version=record.commitment_version,
                assessment_id=record.assessment_id,
                assessment_commitment_version=record.assessment_commitment_version,
                source_event_digest=record.source_event_digest,
                assessment_provenance_status=record.assessment_provenance_status,
                snapshot_id=record.snapshot_id,
                snapshot_version=record.snapshot_version,
                constraints=[ConstraintReason.model_validate(item) for item in record.constraints],
                affected_commitment_ids=record.affected_commitment_ids,
                correlation_id=record.correlation_id,
                causation_id=record.causation_id,
                evidence_refs=record.evidence_refs,
                occurred_at=occurred_at,
            )
        except (ValidationError, TypeError, ValueError, AttributeError) as exc:
            raise DomainError(
                "RECOVERY_TRIGGER_INTEGRITY_ERROR",
                "Persisted Recovery Case trigger is invalid",
                status_code=500,
            ) from exc
        if record.event_digest != cls._digest(trigger):
            raise DomainError(
                "RECOVERY_TRIGGER_INTEGRITY_ERROR",
                "Persisted Recovery Case trigger digest is inconsistent",
                status_code=500,
            )
        return trigger

    @staticmethod
    def _lock_commitment(session: Session, tenant_id: str, commitment_id: str) -> CommitmentRecord:
        row = session.scalar(
            select(CommitmentRecord)
            .where(
                CommitmentRecord.tenant_id == tenant_id,
                CommitmentRecord.commitment_id == commitment_id,
            )
            .with_for_update()
        )
        if row is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Commitment not found in tenant scope", status_code=404)
        return row

    @classmethod
    def _trigger_record(
        cls,
        trigger: RecoveryTriggerReference,
        case_id: str,
    ) -> RecoveryCaseTriggerRecord:
        return RecoveryCaseTriggerRecord(
            tenant_id=trigger.tenant_id,
            event_id=trigger.event_id,
            case_id=case_id,
            commitment_id=trigger.commitment_id,
            commitment_version=trigger.commitment_version,
            assessment_id=trigger.assessment_id,
            assessment_commitment_version=trigger.assessment_commitment_version,
            assessment_provenance_status=trigger.assessment_provenance_status,
            snapshot_id=trigger.snapshot_id,
            snapshot_version=trigger.snapshot_version,
            constraints=[item.model_dump(mode="json") for item in trigger.constraints],
            affected_commitment_ids=list(trigger.affected_commitment_ids),
            evidence_refs=list(trigger.evidence_refs),
            correlation_id=trigger.correlation_id,
            causation_id=trigger.causation_id,
            occurred_at=trigger.occurred_at,
            event_digest=cls._digest(trigger),
            source_event_digest=trigger.source_event_digest,
        )

    def list_case_triggers(
        self,
        session: Session,
        tenant_id: str,
        case_id: str,
        *,
        commitment_id: str | None = None,
    ) -> list[RecoveryTriggerReference]:
        with session.no_autoflush:
            records = session.scalars(
                select(RecoveryCaseTriggerRecord)
                .where(
                    RecoveryCaseTriggerRecord.tenant_id == tenant_id,
                    RecoveryCaseTriggerRecord.case_id == case_id,
                )
                .order_by(RecoveryCaseTriggerRecord.occurred_at, RecoveryCaseTriggerRecord.event_id)
            ).all()
        if commitment_id is not None and any(row.commitment_id != commitment_id for row in records):
            raise DomainError(
                "RECOVERY_TRIGGER_INTEGRITY_ERROR",
                "Persisted Recovery Case trigger binding is inconsistent",
                status_code=500,
            )
        return [self._trigger_from_record(row) for row in records]

    def _read_case(self, session: Session, record: RecoveryCaseRecord) -> RecoveryCase:
        case = self._case_from_record(record)
        history = self.list_case_triggers(
            session, record.tenant_id, record.case_id, commitment_id=record.commitment_id
        )
        if (
            not history
            or record.opening_event_id not in {item.event_id for item in history}
            or len(history) != len(case.trigger_events)
            or {item.event_id: item.model_dump(mode="json") for item in history}
            != {item.event_id: item.model_dump(mode="json") for item in case.trigger_events}
        ):
            raise DomainError(
                "RECOVERY_CASE_INTEGRITY_ERROR",
                "Persisted Recovery Case trigger history contradicts its payload",
                status_code=500,
            )
        return case.model_copy(update={"trigger_events": history})

    def get_case_by_id(
        self,
        session: Session,
        tenant_id: str,
        case_id: str,
        *,
        commitment_id: str | None = None,
    ) -> RecoveryCase | None:
        with session.no_autoflush:
            record = session.get(RecoveryCaseRecord, (tenant_id, case_id))
        if record is None:
            return None
        if commitment_id is not None and record.commitment_id != commitment_id:
            return None
        return self._read_case(session, record)

    def get_active_case(
        self,
        session: Session,
        tenant_id: str,
        commitment_id: str,
        *,
        for_update: bool = False,
    ) -> RecoveryCase | None:
        statement = select(RecoveryCaseRecord).where(
            RecoveryCaseRecord.tenant_id == tenant_id,
            RecoveryCaseRecord.commitment_id == commitment_id,
            RecoveryCaseRecord.status.in_(ACTIVE_CASE_STATUSES),
        )
        if for_update:
            statement = statement.with_for_update()
        with session.no_autoflush:
            records = session.scalars(statement.limit(2)).all()
        if not records:
            return None
        if len(records) != 1:
            raise DomainError(
                "RECOVERY_CASE_INTEGRITY_ERROR",
                "Multiple active Recovery Cases exist for one Commitment",
                status_code=500,
            )
        return self._read_case(session, records[0])

    def read_case_and_history(
        self,
        session: Session,
        tenant_id: str,
        case_id: str,
        *,
        commitment_id: str | None = None,
    ) -> tuple[RecoveryCase, list[RecoveryTriggerReference]] | None:
        case = self.get_case_by_id(session, tenant_id, case_id, commitment_id=commitment_id)
        if case is None:
            return None
        return case, list(case.trigger_events)

    @staticmethod
    def _check_duplicate(
        session: Session,
        trigger: RecoveryTriggerReference,
    ) -> RecoveryCaseTriggerRecord | None:
        record = session.get(RecoveryCaseTriggerRecord, (trigger.tenant_id, trigger.event_id))
        if record is None:
            return None
        if record.event_digest != SqlAlchemyRecoveryRepository._digest(trigger):
            raise DomainError(
                "RECOVERY_EVENT_ID_CONFLICT",
                "The same tenant/event ID was received with different trigger content",
                status_code=409,
            )
        if (record.source_event_digest is None) != (trigger.source_event_digest is None):
            raise DomainError(
                "RECOVERY_EVENT_IDENTITY_UNVERIFIABLE",
                "The stored and incoming trigger do not have matching full-event digest coverage",
                status_code=409,
            )
        if (
            record.source_event_digest is not None
            and record.source_event_digest != trigger.source_event_digest
        ):
            raise DomainError(
                "RECOVERY_EVENT_ID_CONFLICT",
                "The same tenant/event ID was received with different full DomainEvent content",
                status_code=409,
            )
        return record

    @staticmethod
    def _apply_trigger(
        existing: RecoveryCase | None,
        candidate: RecoveryCase,
        trigger: RecoveryTriggerReference,
    ) -> tuple[RecoveryCase, bool, bool]:
        # Reuse the tested P3 aggregate transition logic; this temporary
        # repository is never used as durable storage or as a lock.
        from .service import RecoveryRepository

        memory = RecoveryRepository()
        if existing is not None:
            memory.save_case(existing)
        return memory.record_trigger_event(candidate, trigger)

    @staticmethod
    def _copy_case_columns(record: RecoveryCaseRecord, case: RecoveryCase) -> None:
        if (record.tenant_id, record.case_id, record.commitment_id) != (
            case.tenant_id,
            case.case_id,
            case.commitment_id,
        ):
            raise DomainError(
                "RECOVERY_CASE_IDENTITY_CONFLICT",
                "Cannot update a Recovery Case row with a different aggregate identity",
                status_code=409,
            )
        record.status = case.status.value
        record.case_version = case.case_version
        record.commitment_version = case.commitment_version
        record.case_payload = SqlAlchemyRecoveryRepository._case_payload(case)
        record.updated_at = case.updated_at
        record.resolution_refs = [item.model_dump(mode="json") for item in case.resolution_events]
        if case.resolution_events:
            last = case.resolution_events[-1]
            record.resolution_event_id = last.event_id
            record.resolution_commitment_version = last.commitment_version
            record.resolved_at = last.occurred_at

    def create_or_get_active_case(
        self,
        session: Session,
        case: RecoveryCase,
        trigger: RecoveryTriggerReference,
        *,
        risk_episode_id: str | None = None,
    ) -> tuple[RecoveryCase, bool, bool]:
        if case.status.value not in ACTIVE_CASE_STATUSES:
            raise DomainError(
                "RECOVERY_CASE_INITIAL_STATUS_INVALID",
                "A new or reused risk episode must use an active Recovery Case status",
                status_code=409,
            )
        if (case.tenant_id, case.commitment_id, case.commitment_version) != (
            trigger.tenant_id,
            trigger.commitment_id,
            trigger.commitment_version,
        ):
            raise DomainError(
                "RECOVERY_TRIGGER_BINDING_MISMATCH",
                "Trigger and candidate case bindings differ",
                status_code=409,
            )

        duplicate = self._check_duplicate(session, trigger)
        if duplicate is not None:
            stored = self.get_case_by_id(session, trigger.tenant_id, duplicate.case_id)
            if stored is None:
                raise DomainError(
                    "RECOVERY_CASE_HISTORY_ORPHANED",
                    "Trigger history has no Recovery Case",
                    status_code=500,
                )
            return stored, False, True

        commitment_row = self._lock_commitment(session, trigger.tenant_id, trigger.commitment_id)
        if commitment_row.commitment_version != trigger.commitment_version:
            raise DomainError(
                "RECOVERY_TRIGGER_VERSION_CONFLICT",
                "Trigger is not for the current Commitment version",
                status_code=409,
            )

        active_record = session.scalar(
            select(RecoveryCaseRecord)
            .where(
                RecoveryCaseRecord.tenant_id == trigger.tenant_id,
                RecoveryCaseRecord.commitment_id == trigger.commitment_id,
                RecoveryCaseRecord.status.in_(ACTIVE_CASE_STATUSES),
            )
            .with_for_update()
        )
        if active_record is not None:
            existing = self._case_from_record(active_record).model_copy(update={
                "trigger_events": self.list_case_triggers(session, trigger.tenant_id, active_record.case_id),
            })
            updated, created, duplicate = self._apply_trigger(existing, case, trigger)
            self._copy_case_columns(active_record, updated)
            session.add(self._trigger_record(trigger, active_record.case_id))
            session.flush()
            return self.get_case_by_id(session, trigger.tenant_id, active_record.case_id), created, duplicate  # type: ignore[return-value]

        durable_case = case.model_copy(update={"storage_mode": "DURABLE_DATABASE"})
        if not any(item.event_id == trigger.event_id for item in durable_case.trigger_events):
            durable_case = durable_case.model_copy(update={"trigger_events": [*durable_case.trigger_events, trigger]})
        episode_id = risk_episode_id or trigger.event_id
        now = durable_case.created_at
        record = RecoveryCaseRecord(
            tenant_id=durable_case.tenant_id,
            case_id=durable_case.case_id,
            commitment_id=durable_case.commitment_id,
            risk_episode_id=episode_id,
            opening_event_id=trigger.event_id,
            status=durable_case.status.value,
            case_version=durable_case.case_version,
            commitment_version=durable_case.commitment_version,
            payload_schema_version=1,
            case_payload=self._case_payload(durable_case),
            resolution_refs=[],
            created_at=now,
            updated_at=durable_case.updated_at,
        )
        session.add_all([record, self._trigger_record(trigger, durable_case.case_id)])
        session.flush()
        return self.get_case_by_id(session, trigger.tenant_id, durable_case.case_id), True, False  # type: ignore[return-value]

    def append_trigger_idempotently(
        self,
        session: Session,
        *,
        tenant_id: str,
        case_id: str,
        candidate_case: RecoveryCase,
        trigger: RecoveryTriggerReference,
        expected_case_version: int | None = None,
    ) -> tuple[RecoveryCase, bool]:
        if (tenant_id, case_id, candidate_case.commitment_id) != (
            trigger.tenant_id,
            candidate_case.case_id,
            trigger.commitment_id,
        ):
            raise DomainError(
                "RECOVERY_TRIGGER_BINDING_MISMATCH",
                "Trigger/case tenant identity mismatch",
                status_code=409,
            )
        duplicate = self._check_duplicate(session, trigger)
        if duplicate is not None:
            if duplicate.case_id != case_id:
                raise DomainError(
                    "RECOVERY_EVENT_CASE_BINDING_CONFLICT",
                    "The trigger event is already attached to a different Recovery Case",
                    status_code=409,
                )
            case = self.get_case_by_id(session, tenant_id, duplicate.case_id)
            if case is None:
                raise DomainError(
                    "RECOVERY_CASE_HISTORY_ORPHANED",
                    "Trigger history has no Recovery Case",
                    status_code=500,
                )
            return case, False

        commitment_row = self._lock_commitment(session, tenant_id, trigger.commitment_id)
        if commitment_row.commitment_version != trigger.commitment_version:
            raise DomainError(
                "RECOVERY_TRIGGER_VERSION_CONFLICT",
                "Trigger is not for the current Commitment version",
                status_code=409,
            )

        record = session.scalar(
            select(RecoveryCaseRecord)
            .where(RecoveryCaseRecord.tenant_id == tenant_id, RecoveryCaseRecord.case_id == case_id)
            .with_for_update()
        )
        if record is None:
            raise DomainError("RECOVERY_CASE_NOT_FOUND", "Recovery Case was not found", status_code=404)
        if expected_case_version is not None and record.case_version != expected_case_version:
            raise DomainError("RECOVERY_CASE_VERSION_CONFLICT", "Recovery Case version is stale", status_code=409)
        existing = self._case_from_record(record).model_copy(update={
            "trigger_events": self.list_case_triggers(session, tenant_id, case_id),
        })
        if existing.status is RecoveryCaseStatus.COMPLETED:
            raise DomainError(
                "RECOVERY_CASE_TERMINAL",
                "A completed Recovery Case is immutable; a new risk episode requires a new case identity",
                status_code=409,
            )
        updated, _, _ = self._apply_trigger(existing, candidate_case, trigger)
        self._copy_case_columns(record, updated)
        session.add(self._trigger_record(trigger, case_id))
        session.flush()
        saved = self.get_case_by_id(session, tenant_id, case_id)
        if saved is None:
            raise DomainError("RECOVERY_CASE_NOT_FOUND", "Recovery Case disappeared during update", status_code=500)
        return saved, True

    def mark_needs_replan(
        self,
        session: Session,
        *,
        tenant_id: str,
        case_id: str,
        candidate_case: RecoveryCase,
        trigger: RecoveryTriggerReference,
        expected_case_version: int | None = None,
    ) -> tuple[RecoveryCase, bool]:
        return self.append_trigger_idempotently(
            session,
            tenant_id=tenant_id,
            case_id=case_id,
            candidate_case=candidate_case,
            trigger=trigger,
            expected_case_version=expected_case_version,
        )

    def resolve_case(
        self,
        session: Session,
        *,
        tenant_id: str,
        commitment_id: str,
        commitment: Commitment,
        resolution: RecoveryResolutionReference,
        expected_case_version: int | None = None,
    ) -> tuple[RecoveryCase | None, bool]:
        if (tenant_id, commitment_id, commitment.tenant_id, commitment.commitment_id) != (
            resolution.tenant_id,
            resolution.commitment_id,
            resolution.tenant_id,
            resolution.commitment_id,
        ):
            raise DomainError(
                "RECOVERY_RESOLUTION_BINDING_MISMATCH",
                "Resolution tenant/commitment mismatch",
                status_code=409,
            )
        commitment_row = self._lock_commitment(session, tenant_id, commitment_id)
        if commitment_row.commitment_version != resolution.commitment_version:
            raise DomainError("RECOVERY_RESOLUTION_VERSION_CONFLICT", "Resolution version is not current", status_code=409)
        if commitment.commitment_version != commitment_row.commitment_version:
            raise DomainError("RECOVERY_RESOLUTION_VERSION_CONFLICT", "Commitment read is stale", status_code=409)
        if commitment_row.risk_state != "RESOLVED" or commitment_row.recovery_state != "COMPLETED":
            raise DomainError("RECOVERY_RESOLUTION_NOT_AUTHORITATIVE", "Core has not confirmed resolution", status_code=409)

        record = session.scalar(
            select(RecoveryCaseRecord)
            .where(
                RecoveryCaseRecord.tenant_id == tenant_id,
                RecoveryCaseRecord.commitment_id == commitment_id,
                RecoveryCaseRecord.status.in_(ACTIVE_CASE_STATUSES),
            )
            .with_for_update()
        )
        if record is None:
            prior = session.scalar(
                select(RecoveryCaseRecord).where(
                    RecoveryCaseRecord.tenant_id == tenant_id,
                    RecoveryCaseRecord.commitment_id == commitment_id,
                    RecoveryCaseRecord.resolution_event_id == resolution.event_id,
                )
            )
            if prior is None:
                return None, False
            prior_case = self._case_from_record(prior)
            prior_resolution = next(
                (item for item in prior_case.resolution_events if item.event_id == resolution.event_id),
                None,
            )
            same_resolution = (
                prior_resolution is not None
                and prior_resolution.model_dump(mode="json") == resolution.model_dump(mode="json")
            )
            if not same_resolution:
                raise DomainError("RECOVERY_EVENT_ID_CONFLICT", "Resolution event ID content conflicts", status_code=409)
            return prior_case, False
        current = self._case_from_record(record).model_copy(update={
            "trigger_events": self.list_case_triggers(session, tenant_id, record.case_id),
        })
        if expected_case_version is not None and record.case_version != expected_case_version:
            raise DomainError("RECOVERY_CASE_VERSION_CONFLICT", "Recovery Case version is stale", status_code=409)
        prior_resolution = next(
            (item for item in current.resolution_events if item.event_id == resolution.event_id),
            None,
        )
        if prior_resolution is not None:
            if prior_resolution.model_dump(mode="json") != resolution.model_dump(mode="json"):
                raise DomainError("RECOVERY_EVENT_ID_CONFLICT", "Resolution event ID content conflicts", status_code=409)
            return current, False

        from .service import RecoveryRepository

        memory = RecoveryRepository()
        memory.save_case(current)
        resolved, changed = memory.complete_resolved_case(commitment, resolution)
        if resolved is None:
            return None, False
        self._copy_case_columns(record, resolved)
        session.flush()
        return resolved.model_copy(update={"storage_mode": "DURABLE_DATABASE"}), changed
