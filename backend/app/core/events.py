from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .schemas import DomainEvent

FORBIDDEN_PAYLOAD_KEYS = {
    "password",
    "secret",
    "api_key",
    "token",
    "access_token",
    "credit_card",
    "private_key",
    "phone",
    "email",
    "customer_phone",
    "customer_email",
    "contact_phone",
    "contact_email",
    "customer_contact",
    "message_body",
    "raw_message",
    "contact_number",
}


class CoreEventType(StrEnum):
    COMMITMENT_CREATED = "commitment.created"
    COMMITMENT_PROPOSAL_OFFERED = "commitment.proposal_offered"
    COMMITMENT_CONFIRMED = "commitment.confirmed"
    COMMITMENT_AT_RISK = "commitment.at_risk"
    COMMITMENT_RISK_RESOLVED = "commitment.risk_resolved"
    COMMITMENT_FULFILMENT_VERIFIED = "commitment.fulfilment_verified"
    COMMITMENT_LIFECYCLE_CHANGED = "commitment.lifecycle_changed"
    COMMITMENT_PROPOSAL_REJECTED = "commitment.proposal_rejected"
    COMMITMENT_CONTEXT_READY = "commitment.context_ready"
    RECOVERY_STARTED = "recovery.started"
    RECOVERY_PLAN_APPROVED = "recovery.plan_approved"
    RECOVERY_COMMUNICATION_REQUESTED = "recovery.communication_requested"
    AUDIT_RECORDED = "audit.recorded"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


def validate_event_payload(payload: dict[str, Any]) -> None:
    """Ensure event payloads contain only references/IDs and no secrets or unnecessary PII."""
    for key, value in payload.items():
        lowered = key.lower()
        for forbidden in FORBIDDEN_PAYLOAD_KEYS:
            if forbidden in lowered:
                raise ValueError(f"Payload key '{key}' contains forbidden sensitive keyword '{forbidden}'")
        if isinstance(value, dict):
            validate_event_payload(value)


def create_domain_event(
    *,
    event_type: str,
    tenant_id: str,
    correlation_id: str,
    commitment_id: str | None = None,
    commitment_version: int | None = None,
    causation_id: str | None = None,
    payload: dict[str, Any] | None = None,
    event_id: str | None = None,
    occurred_at: datetime | None = None,
    schema_version: int = 1,
) -> DomainEvent:
    """Construct and validate a canonical DomainEvent envelope."""
    now = occurred_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("occurred_at must include explicit UTC timezone offset")

    data = payload or {}
    validate_event_payload(data)

    return DomainEvent.model_validate(
        {
            "event_id": event_id or f"evt_{uuid4().hex[:16]}",
            "schema_version": schema_version,
            "event_type": event_type,
            "tenant_id": tenant_id,
            "commitment_id": commitment_id,
            "commitment_version": commitment_version,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "occurred_at": now,
            "payload": data,
        }
    )
