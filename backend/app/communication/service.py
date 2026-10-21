"""Pure integration-boundary helpers; no event consumption or business commands."""

from pydantic import ValidationError

from app.core.errors import DomainError
from app.core.events import CoreEventType
from app.core.schemas import DomainEvent

from .schemas import RecoveryCommunicationReference


def inspect_recovery_communication_event(
    event: DomainEvent,
    *,
    expected_tenant_id: str,
) -> RecoveryCommunicationReference:
    """Validate reference shape against a server-resolved tenant, without any IO.

    This is NOT a subscriber, freshness check, identity verifier or approval gate.
    Current authority must be resolved by future P3/P5 adapters before any command.
    Only known references are projected; additional payload data is not forwarded.
    """
    if not expected_tenant_id.strip():
        raise DomainError("TENANT_REQUIRED", "A resolved tenant is required", status_code=400)
    if event.tenant_id != expected_tenant_id:
        raise DomainError("TENANT_MISMATCH", "Event tenant does not match context", status_code=403)
    if event.event_type != CoreEventType.RECOVERY_COMMUNICATION_REQUESTED.value:
        raise DomainError(
            "UNSUPPORTED_COMMUNICATION_EVENT", "Unexpected communication event type",
            status_code=422,
        )
    if event.schema_version != 1:
        raise DomainError(
            "UNSUPPORTED_EVENT_SCHEMA", "Unsupported event schema version", status_code=422,
        )
    if not event.commitment_id or event.payload.get("commitment_id") != event.commitment_id:
        raise DomainError(
            "COMMITMENT_ID_MISMATCH", "Event envelope and payload targets must match",
            status_code=422,
        )
    try:
        return RecoveryCommunicationReference.model_validate({
            "source_event_id": event.event_id,
            "tenant_id": event.tenant_id,
            "correlation_id": event.correlation_id,
            "causation_id": event.causation_id,
            "occurred_at": event.occurred_at,
            "commitment_id": event.commitment_id,
            "commitment_version": event.commitment_version,
            "plan_id": event.payload.get("plan_id"),
            "plan_version": event.payload.get("plan_version"),
            "proposal_id": event.payload.get("proposal_id"),
            "proposal_version": event.payload.get("proposal_version"),
        })
    except ValidationError as exc:
        # Do not copy arbitrary payload values into API errors or logs.
        raise DomainError(
            "INVALID_COMMUNICATION_REFERENCE", "Event contains missing or invalid references",
            status_code=422,
        ) from exc
