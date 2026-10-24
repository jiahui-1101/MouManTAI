"""P4-local integration references; authoritative business models remain in Core."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from app.core.schemas import (
    ApprovalState, CommitmentTerms, CommunicationChannel, ContractModel, MessageStatus, OffsetAwareDatetime,
)


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


class CreateCommunicationRequest(ContractModel):
    """Client selects a persisted event; all authority is resolved server-side."""

    source_event_id: str = Field(strict=True, min_length=1, max_length=128, pattern=r"\S")


class RequestStatus(StrEnum):
    BLOCKED = "BLOCKED"
    READY_FOR_DRAFTING = "READY_FOR_DRAFTING"


class RequestAuthorization(ContractModel):
    """Server-only P3/P5 adapter result, never an HTTP request body.

    The installed adapter must enforce create policy and read trusted approval records.
    This DTO is a P4 integration boundary, not a second approval workflow.
    """

    reference: RecoveryCommunicationReference
    approved_terms: CommitmentTerms
    approval_evidence_refs: list[ReferenceId] = Field(min_length=1)
    approval_expires_at: OffsetAwareDatetime
    proposal_expires_at: OffsetAwareDatetime | None = None
    recipient_identity_id: ReferenceId | None = None
    recipient_customer_id: ReferenceId | None = None
    recipient_evidence_refs: list[ReferenceId] = Field(default_factory=list)
    channel: CommunicationChannel | None = None
    channel_evidence_refs: list[ReferenceId] = Field(default_factory=list)


class CommunicationRequestView(ContractModel):
    """P4 request-intake view, not a replacement for Core CommunicationRequest.

    No confirmation or message is created here. The Core contract requires template,
    recipient and confirmation fields that are not yet known at intake time.
    Readiness is a creation-time snapshot and must be rechecked before future drafting.
    """

    communication_id: ReferenceId
    reference: RecoveryCommunicationReference
    request_status: RequestStatus
    blocking_reasons: list[str]
    proposed_terms: CommitmentTerms
    message_status: Literal[MessageStatus.DRAFT] = MessageStatus.DRAFT
    approval_evidence_refs: list[ReferenceId]
    approval_expires_at: OffsetAwareDatetime
    proposal_evidence_refs: list[ReferenceId]
    recipient_identity_id: ReferenceId | None
    recipient_evidence_refs: list[ReferenceId]
    channel: CommunicationChannel | None
    channel_evidence_refs: list[ReferenceId]
    expires_at: OffsetAwareDatetime | None
    created_by: ReferenceId
    created_at: OffsetAwareDatetime
    outbound_status: Literal["QUEUED", "SENT", "FAILED", "DELIVERY_UNKNOWN"] | None = None
    source_origin: Literal["GMAIL", "TELEGRAM", "WHATSAPP", "SYNTHETIC"] | str | None = None
    delivery_mode: Literal["REAL", "SIMULATED"] | str | None = None


class PrepareDraftRequest(ContractModel):
    language: Literal["en", "ms", "zh"] = "en"
    template_key: str = Field(default="delivery_change", strict=True, min_length=1, max_length=64)


class CommunicationSummary(ContractModel):
    """Tenant-wide database counts at checked_at; None means unavailable, not zero."""

    tenant_id: ReferenceId
    total: int = Field(ge=0)
    drafted: int | None = Field(default=None, ge=0)
    sent: int | None = Field(default=None, ge=0)
    needs_attention: int = Field(ge=0)
    checked_at: OffsetAwareDatetime
    unavailable_reasons: dict[Literal["drafted", "sent", "needs_attention"], str] = Field(default_factory=dict)


class MessageDraftView(ContractModel):
    draft_id: ReferenceId
    tenant_id: ReferenceId
    communication_id: ReferenceId
    reference: RecoveryCommunicationReference
    order_id: ReferenceId
    template_key: str
    template_version: int = Field(ge=1)
    language: Literal["en", "ms", "zh"]
    channel: CommunicationChannel
    subject: str | None
    body: str
    approved_terms: CommitmentTerms
    approval_evidence_refs: list[ReferenceId] = Field(min_length=1)
    proposal_evidence_refs: list[str]
    recipient_identity_id: ReferenceId
    recipient_evidence_refs: list[ReferenceId] = Field(min_length=1)
    channel_evidence_refs: list[ReferenceId] = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal[MessageStatus.DRAFT] = MessageStatus.DRAFT
    send_authorized: Literal[False] = False
    expires_at: OffsetAwareDatetime
    created_at: OffsetAwareDatetime


ReviewAction = Literal["READ_REVIEW", "APPROVE_DRAFT", "REJECT_DRAFT"]
ReviewDecisionAction = Literal["APPROVE_DRAFT", "REJECT_DRAFT"]


class ApproveDraftRequest(ContractModel):
    request_key: str = Field(strict=True, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    expected_content_hash: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")


class RejectDraftRequest(ApproveDraftRequest):
    reason: Annotated[str, Field(strict=True, min_length=1, max_length=1000), AfterValidator(_nonblank)]


class ReviewAuthorization(ContractModel):
    """Server-only P5 policy result, not client claims or a Core approval."""

    tenant_id: ReferenceId
    actor_id: ReferenceId
    actor_role: ReferenceId
    communication_id: ReferenceId
    draft_id: ReferenceId
    action: ReviewAction
    evidence_refs: list[ReferenceId] = Field(min_length=1)
    expires_at: OffsetAwareDatetime
    allowed_actions: list[ReviewDecisionAction] = Field(default_factory=list)
    existing_review_status: Literal["VALID", "REVOKED", "UNKNOWN"] = "UNKNOWN"
    existing_review_evidence_refs: list[ReferenceId] = Field(default_factory=list)


class DraftReviewDecision(ContractModel):
    review_id: ReferenceId
    tenant_id: ReferenceId
    communication_id: ReferenceId
    draft_id: ReferenceId
    reference: RecoveryCommunicationReference
    request_key: str
    action: ReviewDecisionAction
    reviewer_id: ReferenceId
    reviewer_role: ReferenceId
    reviewed_at: OffsetAwareDatetime
    expires_at: OffsetAwareDatetime
    content_hash: str
    validation_hash: str
    language: Literal["en", "ms", "zh"]
    recipient_identity_id: ReferenceId
    channel: CommunicationChannel
    core_approval_evidence_refs: list[ReferenceId]
    authorization_evidence_refs: list[ReferenceId]
    reason: str | None
    audit_id: ReferenceId
    correlation_id: ReferenceId


class DraftReviewView(ContractModel):
    tenant_id: ReferenceId
    communication_id: ReferenceId
    draft_id: ReferenceId
    review_state: ApprovalState
    effective_approval: bool = False
    send_authorized: Literal[False] = False
    allowed_actions: list[ReviewDecisionAction] = Field(default_factory=list)
    decision: DraftReviewDecision | None = None
    invalidated_at: OffsetAwareDatetime | None = None
    invalidation_code: str | None = None
    invalidation_audit_id: str | None = None
    checked_at: OffsetAwareDatetime


class SendMessageRequest(ApproveDraftRequest):
    pass


class SendAuthorization(ContractModel):
    """Server-only SEND_MESSAGE grant; never an HTTP body or a demo role."""
    tenant_id: ReferenceId
    actor_id: ReferenceId
    actor_role: ReferenceId
    communication_id: ReferenceId
    draft_id: ReferenceId
    review_id: ReferenceId
    content_hash: str
    validation_hash: str
    action: Literal["SEND_MESSAGE"]
    evidence_refs: list[ReferenceId] = Field(min_length=1)
    expires_at: OffsetAwareDatetime


class SendEligibility(ContractModel):
    tenant_id: ReferenceId
    communication_id: ReferenceId
    draft_id: ReferenceId
    can_send: bool
    content_hash: str | None = None
    approved_review_id: str | None = None
    expires_at: OffsetAwareDatetime | None = None
    blocked_reason: str | None = None
    checked_at: OffsetAwareDatetime


class SendAttemptView(ContractModel):
    attempt_number: int
    status: Literal["QUEUED", "SENT", "FAILED", "DELIVERY_UNKNOWN"]
    provider_reference: str | None
    error_code: str | None
    started_at: OffsetAwareDatetime
    finished_at: OffsetAwareDatetime | None


class OutboundMessageView(ContractModel):
    tenant_id: str
    outbound_id: str
    communication_id: str
    draft_id: str
    approved_review_id: str
    content_hash: str
    channel: CommunicationChannel
    status: Literal["QUEUED", "SENT", "FAILED", "DELIVERY_UNKNOWN"]
    provider_reference: str | None
    provider_confirmed: bool
    created_at: OffsetAwareDatetime
    updated_at: OffsetAwareDatetime
    sent_at: OffsetAwareDatetime | None
    failed_at: OffsetAwareDatetime | None
    last_error_code: str | None
    retry_allowed: Literal[False] = False
    reconciliation_required: bool
    attempts: list[SendAttemptView]
