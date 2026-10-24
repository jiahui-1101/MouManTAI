// Type-only entry point for future P4 components. Keep canonical definitions in shared/types.
export type {
  ApprovalState,
  CommunicationChannel,
  CommunicationRequest,
  Confirmation,
  ConfirmationState,
  DomainEvent,
  MessageStatus,
} from "../../shared/types";

import type {
ApprovalState,
CommitmentTerms,
CommunicationChannel,
CommunicationRequest as CoreCommunicationRequest,
DomainEvent,
ISO8601,
MessageStatus,
RecoveryPlan,
} from "../../shared/types";

// P4 intake response differs from Core's later sending/confirmation contract.
// These two request-status literals mirror app.communication.schemas.RequestStatus.
export interface CommunicationRequestView {
  communication_id: CoreCommunicationRequest["communication_id"];
  reference: DraftReference;
  request_status: "BLOCKED" | "READY_FOR_DRAFTING";
  blocking_reasons: string[];
  proposed_terms: CommitmentTerms;
  message_status: Extract<MessageStatus, "DRAFT">;
  approval_evidence_refs: string[];
  approval_expires_at: ISO8601;
  proposal_evidence_refs: string[];
  recipient_identity_id: string | null;
  recipient_evidence_refs: string[];
  channel: CommunicationChannel | null;
  channel_evidence_refs: string[];
  expires_at: ISO8601 | null;
  created_by: string;
  created_at: ISO8601;
  outbound_status?: OutboundStatus | null;
  source_origin?: CaseOrigin | string | null;
  delivery_mode?: DeliveryMode | string | null;
}

export type CaseOrigin = "GMAIL" | "TELEGRAM" | "WHATSAPP" | "SYNTHETIC";
export type DeliveryMode = "REAL" | "SIMULATED";

export type DraftLanguage = "en" | "ms" | "zh";

export interface CommunicationSummary {
  tenant_id: DraftReference["tenant_id"];
  total: number;
  drafted: number | null;
  sent: number | null;
  needs_attention: number;
  checked_at: ISO8601;
  unavailable_reasons: Partial<Record<"drafted" | "sent" | "needs_attention", string>>;
}

export interface PrepareDraftRequest {
language?: DraftLanguage;
template_key?: string;
}

// Local event projection; shared business field types continue to come from Core.
export type DraftReference = Pick<
RecoveryPlan, "tenant_id" | "commitment_id" | "plan_id" | "plan_version"
> & Pick<DomainEvent, "correlation_id" | "occurred_at"> & {
source_event_id: DomainEvent["event_id"];
causation_id: NonNullable<DomainEvent["causation_id"]> | null;
commitment_version: NonNullable<DomainEvent["commitment_version"]>;
proposal_id: CoreCommunicationRequest["proposal_id"];
proposal_version: CoreCommunicationRequest["proposal_version"];
};

export interface MessageDraftView {
draft_id: string;
tenant_id: CoreCommunicationRequest["tenant_id"];
communication_id: CoreCommunicationRequest["communication_id"];
reference: DraftReference;
order_id: string;
template_key: string;
template_version: number;
language: DraftLanguage;
channel: CommunicationChannel;
subject: string | null;
body: string;
approved_terms: CommitmentTerms;
approval_evidence_refs: string[];
proposal_evidence_refs: string[];
recipient_identity_id: CoreCommunicationRequest["recipient_identity_id"];
recipient_evidence_refs: string[];
channel_evidence_refs: string[];
content_hash: string;
validation_hash: string;
status: Extract<MessageStatus, "DRAFT">;
send_authorized: false;
expires_at: ISO8601;
created_at: ISO8601;
}

export type ReviewDecisionAction = "APPROVE_DRAFT" | "REJECT_DRAFT";
export type OutboundStatus = Extract<MessageStatus, "QUEUED" | "SENT" | "FAILED" | "DELIVERY_UNKNOWN">;
export interface SendEligibility {
  tenant_id: string; communication_id: string; draft_id: string;
  can_send: boolean; content_hash: string | null; approved_review_id: string | null;
  expires_at: string | null; blocked_reason: string | null; checked_at: string;
}
export interface OutboundMessageView {
  tenant_id: string; outbound_id: string; communication_id: string; draft_id: string;
  approved_review_id: string; content_hash: string; channel: CommunicationChannel;
  status: OutboundStatus; provider_reference: string | null; provider_confirmed: boolean;
  created_at: string; updated_at: string; sent_at: string | null; failed_at: string | null;
  last_error_code: string | null; retry_allowed: false; reconciliation_required: boolean;
  attempts: { attempt_number: number; status: OutboundStatus; provider_reference: string | null;
    error_code: string | null; started_at: string; finished_at: string | null }[];
}
export interface DraftReviewDecision extends Pick<MessageDraftView,
  "tenant_id" | "communication_id" | "draft_id" | "reference" | "content_hash" | "validation_hash" |
  "language" | "recipient_identity_id" | "channel" | "expires_at"> {
  review_id: string;
  request_key: string;
  action: ReviewDecisionAction;
  reviewer_id: string;
  reviewer_role: string;
  reviewed_at: ISO8601;
  core_approval_evidence_refs: string[];
  authorization_evidence_refs: string[];
  reason: string | null;
  audit_id: string;
  correlation_id: string;
}
export interface DraftReviewView {
  tenant_id: string;
  communication_id: string;
  draft_id: string;
  review_state: ApprovalState;
  effective_approval: boolean;
  send_authorized: false;
  allowed_actions: ReviewDecisionAction[];
  decision: DraftReviewDecision | null;
  invalidated_at: ISO8601 | null;
  invalidation_code: string | null;
  invalidation_audit_id: string | null;
  checked_at: ISO8601;
}
export interface DraftReviewCommand {
  request_key: string;
  expected_content_hash: string;
  reason?: string;
}
