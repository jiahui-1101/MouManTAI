"""P4 evidence workflow DTOs; Core owns authoritative agreement transitions."""
from typing import Literal
from pydantic import Field

from app.core.schemas import ContractModel, ConfirmationState, OffsetAwareDatetime
from .schemas import RecoveryCommunicationReference, ReferenceId

ResponseIntent = Literal["ACCEPT", "REJECT", "COUNTEROFFER", "CLARIFICATION", "UNKNOWN"]


class CreateConfirmation(ContractModel):
    outbound_id: str = Field(min_length=1, max_length=128)
    ttl_minutes: int = Field(default=60, strict=True, ge=1, le=1440)


class ProcessConfirmationResponse(ContractModel):
    # Selector only: never accepts provider/identity/role/decision claims.
    inbound_message_id: str = Field(min_length=1, max_length=128)


class ConfirmationBasis(ContractModel):
    """Server-only result of current P4/Core authority revalidation."""
    reference: RecoveryCommunicationReference
    customer_id: ReferenceId
    recipient_identity_id: ReferenceId
    channel: Literal["MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    terms_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_evidence_refs: list[ReferenceId] = Field(min_length=1)
    expires_at: OffsetAwareDatetime


class VerifiedInboundResponse(ContractModel):
    """Private adapter DTO, not an HTTP body or a second customer model."""
    tenant_id: ReferenceId
    message_id: ReferenceId
    provider_message_id: str = Field(min_length=1, max_length=200)
    customer_id: ReferenceId
    recipient_identity_id: ReferenceId
    channel: Literal["MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"]
    text: str = Field(max_length=4096, repr=False)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_refs: list[ReferenceId] = Field(min_length=1)


class ConfirmationView(ContractModel):
    confirmation_id: str
    tenant_id: str
    communication_id: str
    outbound_id: str
    customer_id: str
    channel: str
    reference: RecoveryCommunicationReference
    terms_digest: str
    content_hash: str
    state: ConfirmationState
    expires_at: OffsetAwareDatetime
    created_at: OffsetAwareDatetime
    consumed_at: OffsetAwareDatetime | None
    revoked_at: OffsetAwareDatetime | None
    blocked_reasons: list[str]
    core_transition_applied: Literal[False] = False
    evidence_scope: Literal["P4_EVIDENCE_ONLY"] = "P4_EVIDENCE_ONLY"
    integration_mode: Literal["SYNTHETIC_ONLY"] = "SYNTHETIC_ONLY"


class IssuedConfirmation(ContractModel):
    confirmation: ConfirmationView
    confirmation_token: str = Field(repr=False)


class ConfirmationAttemptView(ContractModel):
    attempt_id: str
    confirmation_id: str
    inbound_message_id: str
    intent: ResponseIntent
    reason: str
    evidence_refs: list[str]
    proposed_changes: dict | None
    received_at: OffsetAwareDatetime
    # No token/hash, raw body, raw provider ID or sender/contact in public history.
