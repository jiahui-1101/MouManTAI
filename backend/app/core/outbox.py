from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import DomainError
from .events import OutboxStatus
from .models import AuditEventRecord, CommitmentRecord, OutboxEventRecord, ProcessedEventRecord
from .schemas import DomainEvent

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def to_domain_event(record: OutboxEventRecord) -> DomainEvent:
    return DomainEvent.model_validate(
        {
            "event_id": record.event_id,
            "schema_version": 1,
            "event_type": record.event_type,
            "tenant_id": record.tenant_id,
            "commitment_id": record.commitment_id,
            "commitment_version": record.commitment_version,
            "correlation_id": record.correlation_id,
            "causation_id": record.causation_id,
            "occurred_at": _aware(record.occurred_at),
            "payload": record.payload,
        }
    )


@dataclass
class OutboxBatchResult:
    processed_count: int = 0
    published_count: int = 0
    failed_count: int = 0
    dead_letter_count: int = 0


SubscriberHandler = Callable[[Session, DomainEvent], Any]

MANDATORY_SUBSCRIBERS: dict[str, str] = {
    "commitment.confirmed": "p2_confirmed_evaluator",
    "commitment.at_risk": "p3.recovery_trigger.v1",
}


class OutboxDispatcher:
    MANDATORY_SUBSCRIBERS = MANDATORY_SUBSCRIBERS

    def __init__(self) -> None:
        # event_type -> {consumer_name: handler_fn}
        self._subscribers: dict[str, dict[str, SubscriberHandler]] = defaultdict(dict)
        self._lock = threading.RLock()

    def register_subscriber(
        self,
        event_type: str,
        consumer_name: str,
        handler_fn: SubscriberHandler,
    ) -> None:
        with self._lock:
            self._subscribers[event_type][consumer_name] = handler_fn

    def unregister_subscriber(self, event_type: str, consumer_name: str) -> None:
        with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type].pop(consumer_name, None)

    def clear_subscribers(self) -> None:
        with self._lock:
            self._subscribers.clear()

    def get_subscribers(self, event_type: str) -> list[tuple[str, SubscriberHandler]]:
        with self._lock:
            # Also support wildcard '*' subscribers if needed
            handlers = dict(self._subscribers.get(event_type, {}))
            for name, handler in self._subscribers.get("*", {}).items():
                if name not in handlers:
                    handlers[name] = handler
            return list(handlers.items())

    @staticmethod
    def is_stale_event(session: Session, event: DomainEvent) -> bool:
        """Version guard: if event.commitment_version < current.commitment_version, return True."""
        if not event.commitment_id or event.commitment_version is None:
            return False

        commitment = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
        if commitment is None:
            return False

        is_stale = event.commitment_version < commitment.commitment_version
        if is_stale:
            logger.warning(
                "Stale event ignored: event_id=%s version=%s < current_version=%s",
                event.event_id,
                event.commitment_version,
                commitment.commitment_version,
            )
        return is_stale

    @staticmethod
    def execute_consumer(
        session: Session,
        event: DomainEvent,
        consumer_name: str,
        handler_fn: SubscriberHandler,
    ) -> bool:
        """Idempotent consumer invocation: checks processed_events before execution."""
        existing = session.scalar(
            select(ProcessedEventRecord).where(
                ProcessedEventRecord.tenant_id == event.tenant_id,
                ProcessedEventRecord.event_id == event.event_id,
                ProcessedEventRecord.consumer_name == consumer_name,
            )
        )
        if existing is not None:
            logger.info(
                "Duplicate event skipped: tenant=%s event=%s consumer=%s",
                event.tenant_id,
                event.event_id,
                consumer_name,
            )
            return False

        handler_fn(session, event)
        processed = ProcessedEventRecord(
            tenant_id=event.tenant_id,
            event_id=event.event_id,
            consumer_name=consumer_name,
            processed_at=_now(),
        )
        session.add(processed)
        session.commit()
        return True

    def process_outbox_batch(
        self,
        session: Session,
        batch_size: int = 50,
        max_attempts: int = 5,
        backoff_base_seconds: float = 2.0,
    ) -> OutboxBatchResult:
        """Poll and dispatch pending outbox events with idempotency and retry handling."""
        now = _now()
        stmt = (
            select(OutboxEventRecord)
            .where(
                OutboxEventRecord.status.in_([OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]),
                (OutboxEventRecord.next_retry_at.is_(None)) | (OutboxEventRecord.next_retry_at <= now),
            )
            .order_by(OutboxEventRecord.occurred_at.asc())
            .limit(batch_size)
        )
        records = session.scalars(stmt).all()
        result = OutboxBatchResult(processed_count=len(records))

        for record in records:
            event = to_domain_event(record)

            # A newer aggregate version does not prove a required evaluation ran.
            # Keep an unprocessed mandatory event available for explicit reconciliation;
            # replaying its stale business update would also be unsafe.
            if self.is_stale_event(session, event):
                required_consumer = self.MANDATORY_SUBSCRIBERS.get(event.event_type)
                if required_consumer is not None:
                    completed = session.scalar(
                        select(ProcessedEventRecord).where(
                            ProcessedEventRecord.tenant_id == event.tenant_id,
                            ProcessedEventRecord.event_id == event.event_id,
                            ProcessedEventRecord.consumer_name == required_consumer,
                        )
                    )
                    if completed is None:
                        logger.warning(
                            "Stale mandatory event awaits subscriber reconciliation: event_id=%s consumer=%s",
                            event.event_id,
                            required_consumer,
                        )
                        record.attempts += 1
                        record.last_error = "STALE_MANDATORY_SUBSCRIBER_INCOMPLETE"
                        if record.attempts >= max_attempts:
                            record.status = OutboxStatus.DEAD_LETTER.value
                            record.next_retry_at = None
                            result.dead_letter_count += 1
                        else:
                            record.status = OutboxStatus.FAILED.value
                            delay = min(3600.0, backoff_base_seconds ** record.attempts)
                            record.next_retry_at = _now() + timedelta(seconds=delay)
                            result.failed_count += 1
                        session.commit()
                        continue

                # The mandatory subscriber completed before the event became stale.
                # Record supersession once, without reapplying old business state.
                commitment = (
                    session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
                    if event.commitment_id
                    else None
                )
                curr_ver = commitment.commitment_version if commitment else None
                audit = AuditEventRecord(
                    audit_id=_id("aud"),
                    tenant_id=event.tenant_id,
                    commitment_id=event.commitment_id or "com_none",
                    event_type="commitment.event_superseded",
                    actor_id="system_reconciliation",
                    actor_role="SYSTEM",
                    dimension="agreement" if "confirmed" in event.event_type else "lifecycle",
                    previous_state={"commitment_version": event.commitment_version},
                    new_state={"superseded": True, "stale_event_id": event.event_id, "current_commitment_version": curr_ver},
                    evidence_refs=[],
                    reason=f"Event {event.event_id} at version {event.commitment_version} superseded before evaluation",
                    correlation_id=event.correlation_id,
                    causation_id=event.event_id,
                    occurred_at=_now(),
                )
                session.add(audit)
                record.status = OutboxStatus.PUBLISHED.value
                record.published_at = _now()
                session.commit()
                result.published_count += 1
                continue

            # Mandatory subscriber policy (D-017): specifically named subscriber must be registered (no wildcards)
            required_consumer = self.MANDATORY_SUBSCRIBERS.get(event.event_type)
            if required_consumer is not None:
                with self._lock:
                    is_registered = required_consumer in self._subscribers.get(event.event_type, {})
                if not is_registered:
                    logger.warning(
                        "Mandatory subscriber '%s' for event '%s' (event_id=%s) is not registered; leaving %s",
                        required_consumer,
                        event.event_type,
                        record.event_id,
                        record.status,
                    )
                    # Never mark PUBLISHED prematurely!
                    continue

            subscribers = self.get_subscribers(event.event_type)

            if not subscribers:
                # No subscribers registered for this non-mandatory event; publish cleanly
                record.status = OutboxStatus.PUBLISHED.value
                record.published_at = _now()
                session.commit()
                result.published_count += 1
                continue

            event_failed = False
            for consumer_name, handler_fn in subscribers:
                # Check idempotency per consumer
                is_processed = session.scalar(
                    select(ProcessedEventRecord).where(
                        ProcessedEventRecord.tenant_id == event.tenant_id,
                        ProcessedEventRecord.event_id == event.event_id,
                        ProcessedEventRecord.consumer_name == consumer_name,
                    )
                )
                if is_processed is not None:
                    continue

                try:
                    handler_fn(session, event)
                    processed = ProcessedEventRecord(
                        tenant_id=event.tenant_id,
                        event_id=event.event_id,
                        consumer_name=consumer_name,
                        processed_at=_now(),
                    )
                    session.add(processed)
                except Exception as exc:
                    session.rollback()
                    event_failed = True
                    rec = session.get(OutboxEventRecord, record.event_id)
                    if rec:
                        rec.attempts += 1
                        rec.last_error = f"{type(exc).__name__}: {str(exc)}"
                        if rec.attempts >= max_attempts:
                            rec.status = OutboxStatus.DEAD_LETTER.value
                            rec.next_retry_at = None
                            result.dead_letter_count += 1
                        else:
                            rec.status = OutboxStatus.FAILED.value
                            delay = min(3600.0, backoff_base_seconds ** rec.attempts)
                            rec.next_retry_at = _now() + timedelta(seconds=delay)
                            result.failed_count += 1
                        session.commit()
                    break

            if not event_failed:
                rec = session.get(OutboxEventRecord, record.event_id)
                if rec:
                    rec.status = OutboxStatus.PUBLISHED.value
                    rec.published_at = _now()
                    session.commit()
                    result.published_count += 1

        return result

    @staticmethod
    def requeue_dead_letter(session: Session, event_id: str) -> OutboxEventRecord:
        """Reset a dead-lettered event to PENDING so it can be retried during reconciliation."""
        record = session.get(OutboxEventRecord, event_id)
        if record is None:
            raise DomainError("EVENT_NOT_FOUND", f"Event '{event_id}' not found", status_code=404)

        record.status = OutboxStatus.PENDING.value
        record.attempts = 0
        record.last_error = None
        record.next_retry_at = None
        record.published_at = None
        session.commit()
        session.refresh(record)
        return record


# Global default instance
default_dispatcher = OutboxDispatcher()


def register_subscriber(
    event_type: str,
    consumer_name: str,
    handler_fn: SubscriberHandler,
) -> None:
    default_dispatcher.register_subscriber(event_type, consumer_name, handler_fn)


def unregister_subscriber(event_type: str, consumer_name: str) -> None:
    default_dispatcher.unregister_subscriber(event_type, consumer_name)


def clear_subscribers() -> None:
    default_dispatcher.clear_subscribers()


def is_stale_event(session: Session, event: DomainEvent) -> bool:
    return default_dispatcher.is_stale_event(session, event)


def execute_consumer(
    session: Session,
    event: DomainEvent,
    consumer_name: str,
    handler_fn: SubscriberHandler,
) -> bool:
    return default_dispatcher.execute_consumer(session, event, consumer_name, handler_fn)


def process_outbox_batch(
    session: Session,
    batch_size: int = 50,
    max_attempts: int = 5,
    backoff_base_seconds: float = 2.0,
) -> OutboxBatchResult:
    return default_dispatcher.process_outbox_batch(
        session=session,
        batch_size=batch_size,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
    )


def requeue_dead_letter(session: Session, event_id: str) -> OutboxEventRecord:
    return default_dispatcher.requeue_dead_letter(session=session, event_id=event_id)


def run_worker(
    session_factory: Callable[[], Session],
    poll_interval: float = 1.0,
    stop_event: threading.Event | None = None,
    dispatcher: OutboxDispatcher | None = None,
) -> None:
    """Long-running background polling loop for the outbox worker."""
    active_dispatcher = dispatcher or default_dispatcher
    while stop_event is None or not stop_event.is_set():
        with session_factory() as session:
            try:
                active_dispatcher.process_outbox_batch(session)
            except Exception as exc:
                logger.error("Outbox worker iteration failed: %s", exc, exc_info=True)
        time.sleep(poll_interval)
