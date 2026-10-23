"""P5-owned adapters for the persisted P4 → Core → P3 confirmation flow."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.communication.core_confirmation_bridge import read_confirmation_evidence

from .dependencies import RequestContext
from .errors import DomainError
from .events import OutboxStatus
from .models import OutboxEventRecord
from .outbox import to_domain_event
from .schemas import DomainEvent
from .service import CommitmentService


class P5VerifiedCoreConfirmationPort:
    """Core command port consumed by P4's bridge after durable evidence checks."""

    def apply(self, db: Session, event: DomainEvent, evidence: dict):
        # Re-read the durable P4 source at the Core boundary. The bridge also
        # validates before calling this port; this second check prevents a
        # caller from manufacturing the evidence dictionary itself.
        verified = read_confirmation_evidence(db, event)
        if verified != evidence:
            raise DomainError(
                "CONFIRMATION_EVIDENCE_MISMATCH",
                "Confirmation evidence changed before Core applied it",
                status_code=409,
            )
        return CommitmentService().apply_verified_p4_confirmation(db, event, verified)


class P5RecoveryOutboxBoundary:
    """Caller-owned P3 event append; writes into the Core outbox without commit."""

    _SUPPORTED_EVENT_TYPES = {
        "recovery.communication_requested",
        "recovery.replan_required",
    }

    def publish(self, db: Session, context: RequestContext, event: DomainEvent) -> None:
        if (
            context.actor_id != "service_p3_confirmation"
            or context.actor_role != "SERVICE"
            or context.tenant_id != event.tenant_id
            or context.correlation_id != event.correlation_id
            or event.event_type not in self._SUPPORTED_EVENT_TYPES
            or not event.commitment_id
        ):
            raise DomainError(
                "P3_EVENT_SCOPE_INVALID",
                "P3 event is outside the verified confirmation outbox boundary",
                status_code=403,
            )

        existing = db.get(OutboxEventRecord, event.event_id)
        if existing is not None:
            if to_domain_event(existing) != event:
                raise DomainError(
                    "P3_EVENT_ID_CONFLICT",
                    "P3 event_id already exists with different tenant or content",
                    status_code=409,
                )
            return

        db.add(
            OutboxEventRecord(
                event_id=event.event_id,
                tenant_id=event.tenant_id,
                event_type=event.event_type,
                commitment_id=event.commitment_id,
                commitment_version=event.commitment_version,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                occurred_at=event.occurred_at,
                payload=event.payload,
                attempts=0,
                status=OutboxStatus.PENDING.value,
            )
        )
        # The dispatcher commits this append with P3's case mutation and
        # processed_events row under D-032. Never commit inside this port.
        db.flush()
