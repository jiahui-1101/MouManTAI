"""P3 consumer for P5's commitment.at_risk outbox events.

The consumer is intentionally not auto-registered at import time. P5 owns the
outbox worker/bootstrap; it may register this handler through its existing
subscriber registry once the P3 in-memory case repository is accepted for the
target runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field, ValidationError
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.schemas import (
    AgreementState,
    Commitment,
    ConstraintReason,
    ContractModel,
    DomainEvent,
    FeasibilityState,
    FulfilmentState,
    OffsetAwareDatetime,
    RecoveryState,
    RiskState,
)

from .integrations import CommitmentReader, P5CommitmentReader
from .models import RecoveryCaseStatus, RecoveryResolutionReference, RecoveryTriggerReference
from .service import RecoveryPlanner, default_recovery_planner


class CommitmentAtRiskPayload(ContractModel):
    """Typed subset of the currently emitted P5 at-risk payload."""

    commitment_id: str | None = None
    assessment_id: str = Field(min_length=1)
    assessment_commitment_version: int | None = Field(default=None, ge=1)
    assessment_evidence_refs: list[str] = Field(default_factory=list)
    snapshot_version: int = Field(ge=1)
    feasibility_status: FeasibilityState | None = None
    constraints: list[ConstraintReason] = Field(default_factory=list)
    affected_commitment_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class CommitmentAtRiskEvent(ContractModel):
    event_id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    commitment_version: int = Field(ge=1)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    occurred_at: OffsetAwareDatetime
    payload: CommitmentAtRiskPayload

    @classmethod
    def from_domain_event(cls, event: DomainEvent) -> CommitmentAtRiskEvent:
        parsed = cls.model_validate(event.model_dump(mode="python"))
        if parsed.event_type != "commitment.at_risk":
            raise ValueError("unsupported event type")
        if parsed.schema_version != 1:
            raise ValueError("unsupported event schema version")
        if parsed.payload.commitment_id not in (None, parsed.commitment_id):
            raise ValueError("payload commitment_id does not match event envelope")
        if parsed.payload.feasibility_status not in (None, FeasibilityState.INFEASIBLE):
            raise ValueError("at-risk trigger payload is not INFEASIBLE")
        if (parsed.payload.assessment_commitment_version is not None
                and parsed.payload.assessment_commitment_version >= parsed.commitment_version):
            raise ValueError(
                "source assessment commitment version must precede the post-transition event version"
            )
        return parsed


class CommitmentLifecyclePayload(ContractModel):
    commitment_id: str | None = None
    assessment_id: str = Field(min_length=1)
    feasibility_state: FeasibilityState


class CommitmentLifecycleEvent(ContractModel):
    event_id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    commitment_version: int = Field(ge=1)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    occurred_at: OffsetAwareDatetime
    payload: CommitmentLifecyclePayload

    @classmethod
    def from_domain_event(cls, event: DomainEvent) -> CommitmentLifecycleEvent:
        parsed = cls.model_validate(event.model_dump(mode="python"))
        if parsed.event_type != "commitment.lifecycle_changed" or parsed.schema_version != 1:
            raise ValueError("unsupported lifecycle event type or schema version")
        if parsed.payload.commitment_id not in (None, parsed.commitment_id):
            raise ValueError("payload commitment_id does not match event envelope")
        if parsed.payload.feasibility_state != FeasibilityState.FEASIBLE:
            raise ValueError("lifecycle event does not confirm a feasible resolution assessment")
        return parsed


class RecoveryTriggerStatus(StrEnum):
    CASE_CREATED = "CASE_CREATED"
    CASE_REUSED = "CASE_REUSED"
    CASE_COMPLETED = "CASE_COMPLETED"
    CASE_ALREADY_COMPLETED = "CASE_ALREADY_COMPLETED"
    DUPLICATE = "DUPLICATE"
    NO_ACTIVE_CASE = "NO_ACTIVE_CASE"
    IGNORED_UNRELATED = "IGNORED_UNRELATED"
    REJECTED_MALFORMED = "REJECTED_MALFORMED"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_VERSION_MISMATCH = "REJECTED_VERSION_MISMATCH"
    REJECTED_WRONG_TENANT_OR_MISSING = "REJECTED_WRONG_TENANT_OR_MISSING"
    REJECTED_INELIGIBLE = "REJECTED_INELIGIBLE"


class RecoveryTriggerOutcome(ContractModel):
    status: RecoveryTriggerStatus
    event_id: str | None = None
    recovery_case_id: str | None = None
    reason: str | None = None


class SubscriberRegistry(Protocol):
    def register_subscriber(
        self,
        event_type: str,
        consumer_name: str,
        handler_fn: Callable[[Session, DomainEvent], Any],
    ) -> None: ...


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


class RecoveryTriggerConsumer:
    """Validate Core's current state, then idempotently create/reuse a P3 case."""

    consumer_name = "p3.recovery_trigger.v1"

    def __init__(
        self,
        *,
        planner: RecoveryPlanner | None = None,
        commitment_reader: CommitmentReader | None = None,
    ) -> None:
        self.planner = planner or default_recovery_planner
        self.commitment_reader = commitment_reader or P5CommitmentReader()

    @staticmethod
    def _rejected(
        status: RecoveryTriggerStatus,
        *,
        event_id: str | None = None,
        reason: str,
    ) -> RecoveryTriggerOutcome:
        return RecoveryTriggerOutcome(status=status, event_id=event_id, reason=reason)

    @staticmethod
    def _eligible(commitment: Commitment) -> bool:
        return (
            commitment.agreement_state == AgreementState.CONFIRMED
            and commitment.feasibility_state == FeasibilityState.INFEASIBLE
            and commitment.risk_state == RiskState.AT_RISK
            and commitment.recovery_state in {
                RecoveryState.RECOVERY_REQUIRED,
                RecoveryState.PLANNING,
                RecoveryState.PENDING_APPROVAL,
                RecoveryState.EXECUTING,
            }
            and commitment.fulfilment_state != FulfilmentState.FULFILLED
        )

    def handle(self, db: Session, event: DomainEvent) -> RecoveryTriggerOutcome:
        try:
            trigger = CommitmentAtRiskEvent.from_domain_event(event)
        except (ValidationError, ValueError, TypeError) as exc:
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_MALFORMED,
                event_id=getattr(event, "event_id", None),
                reason=str(exc),
            )

        if self.planner.repository.has_processed_trigger_event(trigger.tenant_id, trigger.event_id):
            case = self.planner.repository.get_case_for_trigger_event(trigger.tenant_id, trigger.event_id)
            return RecoveryTriggerOutcome(
                status=RecoveryTriggerStatus.DUPLICATE,
                event_id=trigger.event_id,
                recovery_case_id=case.case_id if case else None,
            )

        # Construct a service context only inside this P5 outbox-consumer seam.
        # It is not accepted from headers and is not an approval/execution actor.
        context = RequestContext(
            tenant_id=trigger.tenant_id,
            actor_id="service_core",
            actor_role="SERVICE",
            correlation_id=trigger.correlation_id,
            causation_id=trigger.causation_id,
        )
        try:
            commitment = self.commitment_reader.get_commitment(
                db,
                context,
                trigger.commitment_id,
            )
        except DomainError as exc:
            if exc.code == "COMMITMENT_NOT_FOUND":
                return self._rejected(
                    RecoveryTriggerStatus.REJECTED_WRONG_TENANT_OR_MISSING,
                    event_id=trigger.event_id,
                    reason="No Commitment exists in the event tenant scope",
                )
            raise

        if (commitment.tenant_id, commitment.commitment_id) != (
            trigger.tenant_id,
            trigger.commitment_id,
        ):
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_WRONG_TENANT_OR_MISSING,
                event_id=trigger.event_id,
                reason="P5 returned a Commitment outside the event identity scope",
            )
        if trigger.commitment_version < commitment.commitment_version:
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_STALE,
                event_id=trigger.event_id,
                reason="Event commitment version is older than the authoritative Commitment",
            )
        if trigger.commitment_version != commitment.commitment_version:
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_VERSION_MISMATCH,
                event_id=trigger.event_id,
                reason="Event commitment version does not match the authoritative Commitment",
            )
        if not self._eligible(commitment):
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_INELIGIBLE,
                event_id=trigger.event_id,
                reason="Authoritative Commitment is not confirmed, infeasible, and at risk",
            )

        evidence_refs = _unique([
            *trigger.payload.evidence_refs,
            *trigger.payload.assessment_evidence_refs,
            *(evidence for constraint in trigger.payload.constraints for evidence in constraint.evidence_refs),
        ])
        reference = RecoveryTriggerReference(
            event_id=trigger.event_id,
            tenant_id=trigger.tenant_id,
            commitment_id=trigger.commitment_id,
            commitment_version=trigger.commitment_version,
            assessment_id=trigger.payload.assessment_id,
            assessment_commitment_version=trigger.payload.assessment_commitment_version,
            assessment_provenance_status=(
                "SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED"
                if trigger.payload.assessment_commitment_version is not None
                else "SOURCE_COMMITMENT_VERSION_MISSING"
            ),
            snapshot_version=trigger.payload.snapshot_version,
            affected_commitment_ids=trigger.payload.affected_commitment_ids,
            correlation_id=trigger.correlation_id,
            causation_id=trigger.causation_id,
            evidence_refs=evidence_refs,
            occurred_at=trigger.occurred_at,
        )
        try:
            case, created, duplicate = self.planner.create_trigger_case(commitment, reference)
        except DomainError as exc:
            if exc.code == "RECOVERY_TRIGGER_STALE":
                return self._rejected(
                    RecoveryTriggerStatus.REJECTED_STALE,
                    event_id=trigger.event_id,
                    reason=exc.message,
                )
            raise
        if duplicate:
            status = RecoveryTriggerStatus.DUPLICATE
        elif created:
            status = RecoveryTriggerStatus.CASE_CREATED
        else:
            status = RecoveryTriggerStatus.CASE_REUSED
        return RecoveryTriggerOutcome(
            status=status,
            event_id=trigger.event_id,
            recovery_case_id=case.case_id,
        )

    def handle_commitment_lifecycle_changed(
        self,
        db: Session,
        event: DomainEvent,
    ) -> RecoveryTriggerOutcome:
        """Close a P3 incident only after the current P5 Commitment confirms resolution.

        This handler is provided for P5's existing lifecycle event boundary but is
        not registered automatically. P5 must preserve per-commitment event order
        or supply durable event-history reconciliation before enabling it.
        """
        if event.event_type != "commitment.lifecycle_changed":
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_MALFORMED,
                event_id=event.event_id,
                reason="lifecycle handler received an unsupported event type",
            )
        if event.payload.get("feasibility_state") != FeasibilityState.FEASIBLE.value:
            return RecoveryTriggerOutcome(
                status=RecoveryTriggerStatus.IGNORED_UNRELATED,
                event_id=event.event_id,
                reason="lifecycle event does not report a feasible assessment that could resolve risk",
            )
        try:
            resolution_event = CommitmentLifecycleEvent.from_domain_event(event)
        except (ValidationError, ValueError, TypeError) as exc:
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_MALFORMED,
                event_id=getattr(event, "event_id", None),
                reason=str(exc),
            )

        if self.planner.repository.has_processed_resolution_event(
            resolution_event.tenant_id,
            resolution_event.event_id,
        ):
            case = self.planner.repository.get_case_for_resolution_event(
                resolution_event.tenant_id,
                resolution_event.event_id,
            )
            return RecoveryTriggerOutcome(
                status=RecoveryTriggerStatus.DUPLICATE,
                event_id=resolution_event.event_id,
                recovery_case_id=case.case_id if case else None,
            )

        context = RequestContext(
            tenant_id=resolution_event.tenant_id,
            actor_id="service_core",
            actor_role="SERVICE",
            correlation_id=resolution_event.correlation_id,
            causation_id=resolution_event.causation_id,
        )
        try:
            commitment = self.commitment_reader.get_commitment(
                db,
                context,
                resolution_event.commitment_id,
            )
        except DomainError as exc:
            if exc.code == "COMMITMENT_NOT_FOUND":
                return self._rejected(
                    RecoveryTriggerStatus.REJECTED_WRONG_TENANT_OR_MISSING,
                    event_id=resolution_event.event_id,
                    reason="No Commitment exists in the event tenant scope",
                )
            raise

        if (commitment.tenant_id, commitment.commitment_id) != (
            resolution_event.tenant_id,
            resolution_event.commitment_id,
        ):
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_WRONG_TENANT_OR_MISSING,
                event_id=resolution_event.event_id,
                reason="P5 returned a Commitment outside the event identity scope",
            )
        if resolution_event.commitment_version < commitment.commitment_version:
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_STALE,
                event_id=resolution_event.event_id,
                reason="Resolution event is older than the authoritative Commitment",
            )
        if resolution_event.commitment_version != commitment.commitment_version:
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_VERSION_MISMATCH,
                event_id=resolution_event.event_id,
                reason="Resolution event does not match the authoritative Commitment version",
            )
        if (commitment.risk_state != RiskState.RESOLVED
                or commitment.recovery_state != RecoveryState.COMPLETED):
            return self._rejected(
                RecoveryTriggerStatus.REJECTED_INELIGIBLE,
                event_id=resolution_event.event_id,
                reason="P5 has not confirmed both resolved risk and completed recovery state",
            )

        reference = RecoveryResolutionReference(
            event_id=resolution_event.event_id,
            tenant_id=resolution_event.tenant_id,
            commitment_id=resolution_event.commitment_id,
            commitment_version=resolution_event.commitment_version,
            assessment_id=resolution_event.payload.assessment_id,
            correlation_id=resolution_event.correlation_id,
            causation_id=resolution_event.causation_id,
            occurred_at=resolution_event.occurred_at,
        )
        try:
            case, completed = self.planner.complete_resolved_case(commitment, reference)
        except DomainError as exc:
            if exc.code == "RECOVERY_RESOLUTION_STALE":
                return self._rejected(
                    RecoveryTriggerStatus.REJECTED_STALE,
                    event_id=resolution_event.event_id,
                    reason=exc.message,
                )
            raise
        if completed:
            outcome_status = RecoveryTriggerStatus.CASE_COMPLETED
        elif case is not None and case.status == RecoveryCaseStatus.COMPLETED:
            outcome_status = RecoveryTriggerStatus.CASE_ALREADY_COMPLETED
        else:
            outcome_status = RecoveryTriggerStatus.NO_ACTIVE_CASE
        return RecoveryTriggerOutcome(
            status=outcome_status,
            event_id=resolution_event.event_id,
            recovery_case_id=case.case_id if case else None,
        )


def register_with_p5_dispatcher(
    consumer: RecoveryTriggerConsumer,
    *,
    dispatcher: SubscriberRegistry | None = None,
) -> None:
    """Register through P5's existing dispatcher; P5 must call this at startup."""
    if dispatcher is None:
        from app.core.outbox import default_dispatcher

        dispatcher = default_dispatcher
    dispatcher.register_subscriber(
        "commitment.at_risk",
        consumer.consumer_name,
        consumer.handle,
    )
    dispatcher.register_subscriber(
        "commitment.lifecycle_changed",
        f"{consumer.consumer_name}.resolution",
        consumer.handle_commitment_lifecycle_changed,
    )
