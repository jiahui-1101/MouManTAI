"""P4-local integration references; authoritative business models remain in Core."""

from typing import Annotated

from pydantic import AfterValidator, Field

from app.core.schemas import ContractModel, OffsetAwareDatetime


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("reference must not be blank")
    return value


ReferenceId = Annotated[str, Field(strict=True, min_length=1), AfterValidator(_nonblank)]
ReferenceVersion = Annotated[int, Field(strict=True, ge=1)]


class RecoveryCommunicationReference(ContractModel):
    """Reference-only view of the existing recovery.communication_requested event.

    No terms, verified identity, channel permission or approval is inferred here.
    A structurally valid reference is not permission to create or send a message.
    """

    source_event_id: ReferenceId
    tenant_id: ReferenceId
    correlation_id: ReferenceId
    causation_id: ReferenceId | None = None
    occurred_at: OffsetAwareDatetime
    commitment_id: ReferenceId
    commitment_version: ReferenceVersion
    plan_id: ReferenceId
    plan_version: ReferenceVersion
    proposal_id: ReferenceId
    proposal_version: ReferenceVersion
