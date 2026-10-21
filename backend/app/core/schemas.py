from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
)


def _require_offset(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return value


def _decimal_as_string(value: Decimal) -> str:
    return format(value, "f")


OffsetAwareDatetime = Annotated[datetime, AfterValidator(_require_offset)]
PositiveDecimal = Annotated[
    Decimal,
    Field(gt=Decimal("0")),
    PlainSerializer(_decimal_as_string, return_type=str, when_used="json"),
]
NonNegativeDecimal = Annotated[
    Decimal,
    Field(ge=Decimal("0")),
    PlainSerializer(_decimal_as_string, return_type=str, when_used="json"),
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True)


class AgreementState(StrEnum):
    REQUESTED = "REQUESTED"
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class FeasibilityState(StrEnum):
    NOT_ASSESSED = "NOT_ASSESSED"
    FEASIBLE = "FEASIBLE"
    CONDITIONAL = "CONDITIONAL"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


class RiskState(StrEnum):
    NORMAL = "NORMAL"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"
    RESOLVED = "RESOLVED"


class RecoveryState(StrEnum):
    NONE = "NONE"
    PLANNING = "PLANNING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class FulfilmentState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    UNVERIFIED = "UNVERIFIED"


class ContextStatus(StrEnum):
    INFORMATION_READY = "INFORMATION_READY"
    INFORMATION_PARTIAL = "INFORMATION_PARTIAL"
    CONFLICT = "CONFLICT"
    UNRESOLVED = "UNRESOLVED"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class CustomerIdentityStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    LINK_CANDIDATE = "LINK_CANDIDATE"
    LINK_VERIFIED = "LINK_VERIFIED"
    CONFLICT = "CONFLICT"


class SolverStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    COMPLETED = "COMPLETED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ApprovalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class ExecutionState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    VALIDATED = "VALIDATED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_REPLAN = "NEEDS_REPLAN"


class MessageStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    QUEUED = "QUEUED"
    SUBMITTED = "SUBMITTED"
    SENT = "SENT"
    DELIVERY_UNKNOWN = "DELIVERY_UNKNOWN"
    FAILED = "FAILED"
    DELIVERED = "DELIVERED"


class ConfirmationState(StrEnum):
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    COUNTEROFFER_RECEIVED = "COUNTEROFFER_RECEIVED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    UNRESOLVED = "UNRESOLVED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class CommunicationChannel(StrEnum):
    MOCK_WHATSAPP = "MOCK_WHATSAPP"
    MOCK_EMAIL = "MOCK_EMAIL"
    MOCK_TELEGRAM = "MOCK_TELEGRAM"
    UNKNOWN = "UNKNOWN"


class RequestedItem(ContractModel):
    sku: str = Field(min_length=1)
    quantity: PositiveDecimal
    unit: str = Field(min_length=1)


class BusinessContext(ContractModel):
    tenant_id: str = Field(min_length=1)
    context_id: str = Field(min_length=1)
    source_message_ids: list[str] = Field(min_length=1)
    customer_id: str | None = None
    customer_identity_status: CustomerIdentityStatus = CustomerIdentityStatus.UNVERIFIED
    order_id: str | None = None
    requested_items: list[RequestedItem] = Field(min_length=1)
    requested_delivery_at: OffsetAwareDatetime | None = None
    special_instructions: str | None = None
    field_evidence: dict[str, list[str]] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    context_version: int = Field(ge=1)
    status: ContextStatus

    @field_validator("status", mode="before")
    @classmethod
    def normalize_legacy_ready(cls, value: object) -> object:
        return ContextStatus.INFORMATION_READY if value == "READY" else value


class CommitmentTerms(ContractModel):
    sku: str = Field(min_length=1)
    quantity: PositiveDecimal
    unit: str = Field(min_length=1)
    deadline: OffsetAwareDatetime
    special_instructions: str | None = None


class Commitment(ContractModel):
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    terms: CommitmentTerms
    agreement_state: AgreementState
    feasibility_state: FeasibilityState
    risk_state: RiskState
    recovery_state: RecoveryState
    fulfilment_state: FulfilmentState
    commitment_version: int = Field(ge=1)
    evidence_refs: list[str] = Field(min_length=1)
    updated_at: OffsetAwareDatetime


class ConstraintReason(ContractModel):
    code: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    shortage: NonNegativeDecimal | None = None
    unit: str | None = None
    deadline: OffsetAwareDatetime | None = None
    severity: str = Field(pattern="^(HARD|SOFT|INFORMATIONAL)$")
    evidence_refs: list[str] = Field(default_factory=list)


class FeasibilityAssessment(ContractModel):
    assessment_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    commitment_version: int = Field(ge=1)
    snapshot_version: int = Field(ge=1)
    status: FeasibilityState
    constraints: list[ConstraintReason] = Field(default_factory=list)
    affected_commitment_ids: list[str] = Field(
        default_factory=list,
        description="List of commitment IDs demonstrably impacted by operational changes. Empty list if none or unconfirmed.",
    )
    evidence_refs: list[str] = Field(default_factory=list)
    solver_status: SolverStatus
    assumptions: list[str] = Field(default_factory=list)
    assessed_at: OffsetAwareDatetime


class PlannedAction(ContractModel):
    action_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    requires_approval: bool
    idempotency_key: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)


class RecoveryPlan(ContractModel):
    tenant_id: str = Field(min_length=1)
    recovery_case_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    commitment_id: str = Field(min_length=1)
    based_on_assessment_id: str = Field(min_length=1)
    snapshot_version: int = Field(ge=1)
    feasibility_status: FeasibilityState
    estimated_extra_cost: NonNegativeDecimal
    currency: str = Field(pattern="^[A-Z]{3}$")
    estimated_delay_minutes: int = Field(ge=0)
    risks: list[str] = Field(default_factory=list)
    actions: list[PlannedAction] = Field(min_length=1)
    approval_state: ApprovalState
    execution_state: ExecutionState


class CommunicationRequest(ContractModel):
    communication_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    proposal_version: int = Field(ge=1)
    recipient_identity_id: str = Field(min_length=1)
    channel: CommunicationChannel
    message_status: MessageStatus
    message_template_key: str = Field(min_length=1)
    approval_state: ApprovalState
    confirmation_id: str = Field(min_length=1)
    confirmation_state: ConfirmationState
    expires_at: OffsetAwareDatetime
    evidence_refs: list[str] = Field(default_factory=list)


class Confirmation(ContractModel):
    confirmation_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    proposal_version: int = Field(ge=1)
    recipient_identity_id: str = Field(min_length=1)
    state: ConfirmationState
    accepted_terms: dict[str, Any] | None = None
    response_evidence_refs: list[str] = Field(min_length=1)
    expires_at: OffsetAwareDatetime
    responded_at: OffsetAwareDatetime | None = None


class DomainEvent(ContractModel):
    event_id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str | None = None
    commitment_version: int | None = Field(default=None, ge=1)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    occurred_at: OffsetAwareDatetime
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(ContractModel):
    audit_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    actor_role: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any]
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    occurred_at: OffsetAwareDatetime


class CommitmentCreateRequest(ContractModel):
    order_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    terms: CommitmentTerms
    evidence_refs: list[str] = Field(min_length=1)
    causation_id: str | None = None


class CommitmentTransitionRequest(ContractModel):
    dimension: Literal["agreement", "feasibility", "risk", "recovery", "fulfilment"]
    target_state: str = Field(min_length=1)
    expected_commitment_version: int = Field(ge=1)
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    causation_id: str | None = None


class CommitmentTransitionResponse(ContractModel):
    commitment: Commitment
    audit_event: AuditEvent
    domain_event: DomainEvent


class AttentionCategory(StrEnum):
    STALE_PLAN = "STALE_PLAN"
    UNKNOWN_FEASIBILITY = "UNKNOWN_FEASIBILITY"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FAILED_EXECUTION = "FAILED_EXECUTION"
    UNRESOLVED_CONFIRMATION = "UNRESOLVED_CONFIRMATION"


class AttentionSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AttentionItem(ContractModel):
    commitment_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    category: AttentionCategory
    severity: AttentionSeverity
    summary: str = Field(min_length=1)
    deep_link_path: str = Field(min_length=1)
    updated_at: OffsetAwareDatetime


class OverviewCounts(ContractModel):
    requested: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    at_risk: int = Field(ge=0)
    pending_approval: int = Field(ge=0)
    execution_in_progress: int = Field(ge=0)
    awaiting_confirmation: int = Field(ge=0)
    fulfilled: int = Field(ge=0)


class OverviewCommitmentSummary(ContractModel):
    commitment_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    agreement_state: AgreementState
    feasibility_state: FeasibilityState
    risk_state: RiskState
    recovery_state: RecoveryState
    fulfilment_state: FulfilmentState
    commitment_version: int = Field(ge=1)
    terms: CommitmentTerms
    evidence_refs: list[str] = Field(default_factory=list)
    updated_at: OffsetAwareDatetime


class OverviewResponse(ContractModel):
    tenant_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    actor_role: str = Field(min_length=1)
    integration_mode: Literal["SYNTHETIC"] = "SYNTHETIC"
    last_updated_at: OffsetAwareDatetime
    counts: OverviewCounts
    attention_queue: list[AttentionItem] = Field(default_factory=list)
    commitments: list[OverviewCommitmentSummary] = Field(default_factory=list)


class SourceFeature(StrEnum):
    F1_CONTEXT = "F1_CONTEXT"
    F2_FEASIBILITY = "F2_FEASIBILITY"
    F3_RECOVERY = "F3_RECOVERY"
    F4_COMMUNICATION = "F4_COMMUNICATION"
    CORE = "CORE"


class TimelineEntry(ContractModel):
    entry_id: str = Field(min_length=1)
    occurred_at: OffsetAwareDatetime
    actor_id: str = Field(min_length=1)
    actor_role: str = Field(min_length=1)
    source_feature: SourceFeature
    event_type: str = Field(min_length=1)
    action: str = Field(min_length=1)
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any] = Field(default_factory=dict)
    commitment_version: int | None = None
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    approval_reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    context_id: str | None = None
    assessment_id: str | None = None
    recovery_case_id: str | None = None
    communication_id: str | None = None
    proposal_id: str | None = None


class ProposalCreateRequest(ContractModel):
    proposal_id: str | None = None
    proposal_version: int = Field(default=1, ge=1)
    expected_commitment_version: int = Field(ge=1)
    revised_terms: CommitmentTerms | None = None
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    causation_id: str | None = None


class ProposalConfirmRequest(ContractModel):
    proposal_id: str = Field(min_length=1)
    proposal_version: int = Field(default=1, ge=1)
    expected_commitment_version: int = Field(ge=1)
    decision: Literal["ACCEPT", "REJECT"] = "ACCEPT"
    evidence_refs: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    causation_id: str | None = None
    customer_identity_status: CustomerIdentityStatus | None = None


class RecordFulfilmentRequest(ContractModel):
    expected_commitment_version: int = Field(ge=1)
    fulfilment_state: Literal["FULFILLED", "PARTIALLY_FULFILLED"] = "FULFILLED"
    evidence_refs: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    causation_id: str | None = None


class RecoveryStartRequest(ContractModel):
    expected_commitment_version: int = Field(ge=1)
    reason: str = Field(min_length=1)
    causation_id: str | None = None


class RecoveryExecuteRequest(ContractModel):
    expected_commitment_version: int = Field(ge=1)
    plan: RecoveryPlan
    current_snapshot_version: int = Field(ge=1)
    approved_at: OffsetAwareDatetime
    approval_expires_at: OffsetAwareDatetime
    revised_terms: CommitmentTerms | None = None
    reason: str = Field(min_length=1)
    causation_id: str | None = None


