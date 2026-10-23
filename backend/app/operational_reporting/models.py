"""Trusted-reader input contracts; construction does not establish authenticity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class EvidenceTier(StrEnum):
    UNKNOWN = "UNKNOWN"
    REPORTED = "REPORTED"
    DEMO_ONLY = "DEMO_ONLY"
    VERIFIED = "VERIFIED"


class Milestone(StrEnum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    COMPLETION_REPORTED = "COMPLETION_REPORTED"
    COMPLETED = "COMPLETED"


class EventKind(StrEnum):
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    COMPLETION_REPORTED = "COMPLETION_REPORTED"
    FULFILLED = "FULFILLED"


@dataclass(frozen=True)
class Evidence:
    ref: str
    kind: str
    tier: EvidenceTier
    tenant_id: str
    commitment_id: str


@dataclass(frozen=True)
class OperationalEvent:
    event_id: str
    kind: EventKind | str
    tenant_id: str
    order_id: str
    commitment_id: str
    aggregate_version: int
    occurred_at: datetime
    evidence_refs: tuple[str, ...]
    verified: bool


@dataclass(frozen=True)
class OrderFacts:
    tenant_id: str
    order_id: str
    commitment_id: str
    customer_id: str
    agreement_state: str
    fulfilment_state: str
    aggregate_version: int
    source_version: int
    updated_at: datetime
    snapshot_at: datetime
    due_at: datetime | None
    events: tuple[OperationalEvent, ...]
    evidence: tuple[Evidence, ...]
    planned_quantity: Decimal | None = None
    actual_quantity: Decimal | None = None
    quantity_unit: str | None = None
    actual_quantity_unit: str | None = None
    planned_quantity_ref: str | None = None
    actual_quantity_ref: str | None = None
    planned_duration_minutes: Decimal | None = None
    actual_duration_minutes: Decimal | None = None
    planned_duration_ref: str | None = None
    actual_duration_ref: str | None = None
    delay_reason: str | None = None


@dataclass(frozen=True)
class StatusProjection:
    """A status supplied by the authoritative order-status reader, not calculated here."""

    tenant_id: str
    order_id: str
    commitment_id: str
    customer_id: str
    milestone: Milestone
    source_event_id: str | None
    aggregate_version: int
    snapshot_at: datetime
    evidence_tier: EvidenceTier
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class RecipientPolicy:
    tenant_id: str
    order_id: str
    customer_id: str
    recipient_identity_id: str | None
    channel: str | None
    identity_verified: bool
    channel_capable: bool
    consent: bool | None
    policy_allows: bool | None
    policy_version: str | None


@dataclass(frozen=True)
class SendHistory:
    """A trusted P4 history lookup result, including completeness of the lookup."""

    complete: bool
    handled_keys: frozenset[str]


@dataclass(frozen=True)
class Template:
    identity: str
    version: str
    milestone: Milestone


def status_matches(
    facts: OrderFacts, status: StatusProjection, *, as_of: datetime, max_age_seconds: int = 3600
) -> bool:
    """Check coherence; the caller must still establish the reader's authority."""

    times = (as_of, facts.snapshot_at, facts.updated_at, status.snapshot_at)
    if any(t.tzinfo is None or t.utcoffset() is None for t in times):
        return False
    return (
        (status.tenant_id, status.order_id, status.commitment_id, status.customer_id)
        == (facts.tenant_id, facts.order_id, facts.commitment_id, facts.customer_id)
        and facts.source_version == facts.aggregate_version == status.aggregate_version
        and facts.aggregate_version >= 1
        and status.snapshot_at == facts.snapshot_at
        and facts.updated_at <= facts.snapshot_at <= as_of
        and 0 <= (as_of - facts.snapshot_at).total_seconds() <= max_age_seconds
    )
