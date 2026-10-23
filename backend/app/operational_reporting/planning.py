"""Read-only P4 intent and feedback gates. No outbound side effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from .models import (
    EventKind,
    EvidenceTier,
    Milestone,
    OperationalEvent,
    OrderFacts,
    RecipientPolicy,
    SendHistory,
    StatusProjection,
    Template,
    status_matches,
)


class Eligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    ALREADY_HANDLED = "ALREADY_HANDLED"
    UNKNOWN = "UNKNOWN"


_EVENT_TO_MILESTONE = {
    EventKind.ACCEPTED: Milestone.ORDER_ACCEPTED,
    EventKind.PREPARING: Milestone.PREPARING,
    EventKind.READY: Milestone.READY,
    EventKind.OUT_FOR_DELIVERY: Milestone.OUT_FOR_DELIVERY,
    EventKind.FULFILLED: Milestone.COMPLETED,
}


@dataclass(frozen=True)
class NotificationPlan:
    result: Eligibility
    reason: str
    dedup_key: str | None = None
    event_id: str | None = None
    event_version: int | None = None
    template_id: str | None = None
    template_version: str | None = None
    recipient_identity_id: str | None = None
    channel: str | None = None


def _key(*parts: str) -> str:
    return sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _recipient_gate(
    facts: OrderFacts, recipient: RecipientPolicy
) -> tuple[Eligibility, str] | None:
    if (recipient.tenant_id, recipient.order_id, recipient.customer_id) != (
        facts.tenant_id,
        facts.order_id,
        facts.customer_id,
    ):
        return Eligibility.BLOCKED, "RECIPIENT_BINDING_MISMATCH"
    if not recipient.identity_verified or not recipient.recipient_identity_id:
        return Eligibility.BLOCKED, "IDENTITY_UNVERIFIED"
    if not recipient.channel or not recipient.channel_capable:
        return Eligibility.BLOCKED, "CHANNEL_UNAVAILABLE"
    if recipient.consent is None or recipient.policy_allows is None or not recipient.policy_version:
        return Eligibility.UNKNOWN, "POLICY_UNKNOWN"
    if not recipient.consent or not recipient.policy_allows:
        return Eligibility.BLOCKED, "POLICY_DENIED"
    return None


def plan_milestone(
    facts: OrderFacts,
    status: StatusProjection,
    event: OperationalEvent,
    recipient: RecipientPolicy,
    template: Template,
    history: SendHistory,
    *,
    as_of: datetime,
    max_age_seconds: int = 3600,
) -> NotificationPlan:
    gate = _recipient_gate(facts, recipient)
    if gate:
        return NotificationPlan(*gate)
    if not history.complete:
        return NotificationPlan(Eligibility.UNKNOWN, "SEND_HISTORY_UNKNOWN")
    if (event.tenant_id, event.order_id, event.commitment_id) != (
        facts.tenant_id,
        facts.order_id,
        facts.commitment_id,
    ):
        return NotificationPlan(Eligibility.BLOCKED, "EVENT_BINDING_MISMATCH")
    if not event.verified or event not in facts.events:
        return NotificationPlan(Eligibility.BLOCKED, "EVENT_NOT_VERIFIED_IN_SNAPSHOT")
    if event.occurred_at.tzinfo is None or event.occurred_at.utcoffset() is None:
        return NotificationPlan(Eligibility.UNKNOWN, "EVENT_TIME_UNKNOWN")
    if not status_matches(facts, status, as_of=as_of, max_age_seconds=max_age_seconds):
        return NotificationPlan(Eligibility.UNKNOWN, "STATUS_READER_STALE_OR_MISMATCHED")
    if status.milestone == Milestone.NOT_AVAILABLE:
        return NotificationPlan(
            Eligibility.UNKNOWN, status.diagnostics[0] if status.diagnostics else "STATUS_UNKNOWN"
        )
    if status.evidence_tier not in (EvidenceTier.VERIFIED, EvidenceTier.DEMO_ONLY):
        return NotificationPlan(Eligibility.UNKNOWN, "STATUS_EVIDENCE_UNKNOWN")
    if _EVENT_TO_MILESTONE.get(event.kind) != status.milestone:
        return NotificationPlan(Eligibility.BLOCKED, "EVENT_MILESTONE_MISMATCH")
    if (
        status.source_event_id != event.event_id
        or event.aggregate_version > facts.aggregate_version
    ):
        return NotificationPlan(Eligibility.BLOCKED, "EVENT_SUPERSEDED")
    if template.milestone != status.milestone or not template.identity or not template.version:
        return NotificationPlan(Eligibility.BLOCKED, "TEMPLATE_MISMATCH")
    if (as_of - event.occurred_at).total_seconds() > max_age_seconds:
        return NotificationPlan(Eligibility.BLOCKED, "EVENT_STALE")
    key = _key(
        facts.tenant_id,
        facts.order_id,
        event.event_id,
        str(event.aggregate_version),
        status.milestone.value,
        recipient.channel or "",
        template.identity,
        template.version,
    )
    if key in history.handled_keys:
        return NotificationPlan(Eligibility.ALREADY_HANDLED, "DUPLICATE", key)
    return NotificationPlan(
        Eligibility.ELIGIBLE,
        "PROPOSED_ONLY",
        key,
        event.event_id,
        event.aggregate_version,
        template.identity,
        template.version,
        recipient.recipient_identity_id,
        recipient.channel,
    )


def feedback_readiness(
    facts: OrderFacts,
    status: StatusProjection,
    recipient: RecipientPolicy,
    history: SendHistory,
    *,
    as_of: datetime,
) -> NotificationPlan:
    gate = _recipient_gate(facts, recipient)
    if gate:
        return NotificationPlan(*gate)
    if not history.complete:
        return NotificationPlan(Eligibility.UNKNOWN, "SEND_HISTORY_UNKNOWN")
    if not status_matches(facts, status, as_of=as_of):
        return NotificationPlan(Eligibility.UNKNOWN, "STATUS_READER_STALE_OR_MISMATCHED")
    if status.milestone != Milestone.COMPLETED or facts.fulfilment_state != "FULFILLED":
        return NotificationPlan(Eligibility.BLOCKED, "FULFILMENT_NOT_VERIFIED")
    if status.evidence_tier not in (EvidenceTier.VERIFIED, EvidenceTier.DEMO_ONLY):
        return NotificationPlan(Eligibility.UNKNOWN, "FULFILMENT_EVIDENCE_UNKNOWN")
    completed = next((e for e in facts.events if e.event_id == status.source_event_id), None)
    if completed is None or not completed.verified or completed.kind != EventKind.FULFILLED:
        return NotificationPlan(Eligibility.UNKNOWN, "FULFILMENT_EVENT_MISSING")
    if (completed.tenant_id, completed.order_id, completed.commitment_id) != (
        facts.tenant_id,
        facts.order_id,
        facts.commitment_id,
    ):
        return NotificationPlan(Eligibility.UNKNOWN, "FULFILMENT_BINDING_MISMATCH")
    if completed.occurred_at.tzinfo is None or completed.occurred_at.utcoffset() is None:
        return NotificationPlan(Eligibility.UNKNOWN, "FULFILMENT_TIME_UNKNOWN")
    key = _key(
        facts.tenant_id,
        facts.order_id,
        "FEEDBACK",
        completed.event_id,
        str(completed.aggregate_version),
        recipient.channel or "",
    )
    if key in history.handled_keys:
        return NotificationPlan(Eligibility.ALREADY_HANDLED, "DUPLICATE", key)
    return NotificationPlan(
        Eligibility.ELIGIBLE,
        "INVITATION_MAY_BE_PLANNED",
        key,
        completed.event_id,
        completed.aggregate_version,
        recipient_identity_id=recipient.recipient_identity_id,
        channel=recipient.channel,
    )
