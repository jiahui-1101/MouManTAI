"""P3 recovery event contracts and publication boundary.

No P5 CoreEventType values or outbox tables are introduced here. Without an
approved P5 transactional publisher, receipts remain INTEGRATION_PENDING.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Protocol

from pydantic import ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import create_domain_event
from app.core.schemas import (
    ContractModel,
    DomainEvent,
    FeasibilityState,
    NonNegativeDecimal,
    OffsetAwareDatetime,
)


class RecoveryEventType(StrEnum):
    PLAN_GENERATED = "recovery.plan_generated"
    APPROVAL_REQUIRED = "recovery.approval_required"
    ACTION_COMPLETED = "recovery.action_completed"
    ACTION_FAILED = "recovery.action_failed"
    REPLAN_REQUIRED = "recovery.replan_required"
    COMMUNICATION_REQUESTED = "recovery.communication_requested"


class EventPublicationStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    INTEGRATION_PENDING = "INTEGRATION_PENDING"


class PlanGeneratedPayload(ContractModel):
    evaluation_id: str
    feasibility_status: FeasibilityState
    action_types: tuple[str, ...]
    recommended_under_policy: bool


class ApprovalRequiredPayload(ContractModel):
    approval_id: str
    action_scope: tuple[str, ...]
    maximum_approved_amount_myr: NonNegativeDecimal
    approval_expires_at: OffsetAwareDatetime


class ActionCompletedPayload(ContractModel):
    action_ids: tuple[str, ...] = Field(min_length=1)
    operation_refs: tuple[str, ...] = Field(min_length=1)


class ActionFailedPayload(ContractModel):
    action_ids: tuple[str, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = Field(min_length=1)


class ReplanRequiredPayload(ContractModel):
    reason_code: str
    source_event_id: str | None = None
    invalidated_plan_ids: tuple[str, ...] = ()


class CommunicationRequestedPayload(ContractModel):
    communication_request_id: str
    proposal_id: str
    proposal_version: int = Field(ge=1)
    recipient_identity_ref: str | None = None


RecoveryEventPayload = (
    PlanGeneratedPayload | ApprovalRequiredPayload | ActionCompletedPayload | ActionFailedPayload
    | ReplanRequiredPayload | CommunicationRequestedPayload
)


_PAYLOAD_TYPES = {
    RecoveryEventType.PLAN_GENERATED: PlanGeneratedPayload,
    RecoveryEventType.APPROVAL_REQUIRED: ApprovalRequiredPayload,
    RecoveryEventType.ACTION_COMPLETED: ActionCompletedPayload,
    RecoveryEventType.ACTION_FAILED: ActionFailedPayload,
    RecoveryEventType.REPLAN_REQUIRED: ReplanRequiredPayload,
    RecoveryEventType.COMMUNICATION_REQUESTED: CommunicationRequestedPayload,
}


class RecoveryDomainEvent(ContractModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1)
    event_type: RecoveryEventType
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    commitment_version: int = Field(ge=1)
    recovery_case_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    snapshot_version: int | None = Field(default=None, ge=1)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    occurred_at: OffsetAwareDatetime
    payload: RecoveryEventPayload

    @model_validator(mode="after")
    def payload_matches_event_type(self) -> RecoveryDomainEvent:
        if not isinstance(self.payload, _PAYLOAD_TYPES[self.event_type]):
            raise TypeError("event payload must match event_type")
        return self

    def to_p5_domain_event(self) -> DomainEvent:
        payload = self.payload.model_dump(mode="json")
        payload.update({
            "recovery_case_id": self.recovery_case_id,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "snapshot_version": self.snapshot_version,
            "evidence_refs": list(self.evidence_refs),
        })
        return create_domain_event(
            event_id=self.event_id,
            event_type=self.event_type.value,
            tenant_id=self.tenant_id,
            commitment_id=self.commitment_id,
            commitment_version=self.commitment_version,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            occurred_at=self.occurred_at,
            payload=payload,
        )


class EventPublicationReceipt(ContractModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    status: EventPublicationStatus
    detail_code: str | None = None
    attempted_at: OffsetAwareDatetime


class P3RecoveryEventPublisherPort(Protocol):
    def publish(
        self, event: RecoveryDomainEvent, *, db: Session | None = None,
        context: RequestContext | None = None,
    ) -> EventPublicationReceipt: ...


class ApprovedP5OutboxBoundary(Protocol):
    """Adapter shape only; P5 has not exposed a general public append boundary yet."""

    def publish(self, db: Session, context: RequestContext, event: DomainEvent) -> None: ...


class PendingRecoveryEventPublisher:
    def publish(self, event: RecoveryDomainEvent, *, db: Session | None = None,
                context: RequestContext | None = None) -> EventPublicationReceipt:
        del db, context
        return EventPublicationReceipt(
            event_id=event.event_id, status=EventPublicationStatus.INTEGRATION_PENDING,
            detail_code="P5_TRANSACTIONAL_PUBLISHER_UNAVAILABLE", attempted_at=datetime.now(UTC),
        )


class P5OutboxPublisherAdapter:
    """Calls an explicitly injected P5 boundary; never writes OutboxEventRecord directly."""

    def __init__(self, boundary: ApprovedP5OutboxBoundary) -> None:
        self.boundary = boundary

    def publish(self, event: RecoveryDomainEvent, *, db: Session | None = None,
                context: RequestContext | None = None) -> EventPublicationReceipt:
        # Only this value currently exists in P5 CoreEventType. The remaining
        # P3 event names stay local until a coordinated shared-contract change.
        if event.event_type != RecoveryEventType.COMMUNICATION_REQUESTED:
            return EventPublicationReceipt(
                event_id=event.event_id, status=EventPublicationStatus.INTEGRATION_PENDING,
                detail_code="P5_CORE_EVENT_TYPE_UNSUPPORTED", attempted_at=datetime.now(UTC),
            )
        if db is None or context is None:
            return EventPublicationReceipt(
                event_id=event.event_id, status=EventPublicationStatus.INTEGRATION_PENDING,
                detail_code="P5_DATABASE_CONTEXT_REQUIRED", attempted_at=datetime.now(UTC),
            )
        try:
            self.boundary.publish(db, context, event.to_p5_domain_event())
        except DomainError as exc:
            return EventPublicationReceipt(
                event_id=event.event_id, status=EventPublicationStatus.INTEGRATION_PENDING,
                detail_code=exc.code, attempted_at=datetime.now(UTC),
            )
        return EventPublicationReceipt(
            event_id=event.event_id, status=EventPublicationStatus.PUBLISHED,
            attempted_at=datetime.now(UTC),
        )


class RecoveryEventCoordinator:
    """Creates stable event IDs and deduplicates publication attempts in process."""

    def __init__(self, publisher: P3RecoveryEventPublisherPort | None = None) -> None:
        self.publisher = publisher or PendingRecoveryEventPublisher()
        self._receipts: dict[tuple[str, str], EventPublicationReceipt] = {}
        self._events: dict[tuple[str, str], RecoveryDomainEvent] = {}
        self._lock = RLock()

    @staticmethod
    def prepare(
        *, event_type: RecoveryEventType, tenant_id: str, commitment_id: str,
        commitment_version: int, recovery_case_id: str, plan_id: str, plan_version: int,
        snapshot_version: int | None, correlation_id: str, causation_id: str | None,
        evidence_refs: tuple[str, ...] | list[str], payload: RecoveryEventPayload,
        occurred_at: datetime | None = None,
    ) -> RecoveryDomainEvent:
        happened = occurred_at or datetime.now(UTC)
        fingerprint = {
            "event_type": event_type.value, "tenant_id": tenant_id,
            "commitment_id": commitment_id, "commitment_version": commitment_version,
            "recovery_case_id": recovery_case_id, "plan_id": plan_id,
            "plan_version": plan_version, "snapshot_version": snapshot_version,
            "causation_id": causation_id, "evidence_refs": sorted(set(evidence_refs)),
            "payload": payload.model_dump(mode="json"),
        }
        digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
        return RecoveryDomainEvent(
            event_id=f"evt_p3_{digest}", event_type=event_type, tenant_id=tenant_id,
            commitment_id=commitment_id, commitment_version=commitment_version,
            recovery_case_id=recovery_case_id, plan_id=plan_id, plan_version=plan_version,
            snapshot_version=snapshot_version, correlation_id=correlation_id,
            causation_id=causation_id, evidence_refs=tuple(sorted(set(evidence_refs))),
            occurred_at=happened, payload=payload,
        )

    def publish(self, event: RecoveryDomainEvent, *, db: Session | None = None,
                context: RequestContext | None = None) -> EventPublicationReceipt:
        key = (event.tenant_id, event.event_id)
        with self._lock:
            previous = self._receipts.get(key)
            if previous and previous.status == EventPublicationStatus.PUBLISHED:
                return previous
            receipt = self.publisher.publish(event, db=db, context=context)
            self._events[key] = event
            self._receipts[key] = receipt
            return receipt

    def pending_events(self, tenant_id: str | None = None) -> tuple[RecoveryDomainEvent, ...]:
        with self._lock:
            return tuple(event for (tenant, _), event in self._events.items()
                         if (tenant_id is None or tenant == tenant_id)
                         and self._receipts[(tenant, event.event_id)].status == EventPublicationStatus.INTEGRATION_PENDING)
