export type DecimalString = string;
export type ISO8601 = string;

export type AgreementState =
  | "REQUESTED"
  | "OFFERED"
  | "CONFIRMED"
  | "REJECTED"
  | "CANCELLED";

export type FeasibilityState =
  | "NOT_ASSESSED"
  | "FEASIBLE"
  | "CONDITIONAL"
  | "INFEASIBLE"
  | "UNKNOWN";

export type RiskState = "NORMAL" | "AT_RISK" | "BREACHED" | "RESOLVED";

export type RecoveryState =
  | "NONE"
  | "PLANNING"
  | "PENDING_APPROVAL"
  | "EXECUTING"
  | "COMPLETED"
  | "RECOVERY_REQUIRED";

export type FulfilmentState =
  | "NOT_STARTED"
  | "IN_PROGRESS"
  | "PARTIALLY_FULFILLED"
  | "FULFILLED"
  | "UNVERIFIED";

export type ContextStatus =
  | "INFORMATION_READY"
  | "INFORMATION_PARTIAL"
  | "CONFLICT"
  | "UNRESOLVED"
  | "PROCESSING_FAILED";

export type CustomerIdentityStatus =
  | "UNVERIFIED"
  | "LINK_CANDIDATE"
  | "LINK_VERIFIED"
  | "CONFLICT";

export type SolverStatus = "NOT_RUN" | "COMPLETED" | "TIMEOUT" | "ERROR" | "STALE" | "UNKNOWN";

export type ApprovalState = "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "INVALIDATED";

export type ExecutionState =
  | "NOT_STARTED"
  | "VALIDATED"
  | "PENDING"
  | "APPROVED"
  | "EXECUTING"
  | "VERIFYING"
  | "SUCCEEDED"
  | "FAILED"
  | "NEEDS_REPLAN";

export type MessageStatus =
  | "DRAFT"
  | "VALIDATED"
  | "PENDING_APPROVAL"
  | "QUEUED"
  | "SUBMITTED"
  | "SENT"
  | "DELIVERY_UNKNOWN"
  | "FAILED"
  | "DELIVERED";

export type ConfirmationState =
  | "AWAITING_RESPONSE"
  | "ACCEPTED"
  | "REJECTED"
  | "COUNTEROFFER_RECEIVED"
  | "CLARIFICATION_REQUIRED"
  | "UNRESOLVED"
  | "EXPIRED"
  | "SUPERSEDED";

export type CommunicationChannel = "MOCK_WHATSAPP" | "MOCK_EMAIL" | "MOCK_TELEGRAM" | "UNKNOWN";

export interface RequestedItem {
  sku: string;
  quantity: DecimalString;
  unit: string;
}

export interface BusinessContext {
  tenant_id: string;
  context_id: string;
  commitment_id?: string | null;
  source_message_ids: string[];
  customer_id?: string | null;
  customer_identity_status: CustomerIdentityStatus;
  order_id?: string | null;
  requested_items: RequestedItem[];
  requested_delivery_at?: ISO8601 | null;
  special_instructions?: string | null;
  field_evidence: Record<string, string[]>;
  conflicts: string[];
  missing_fields: string[];
  context_version: number;
  status: ContextStatus;
}

export interface CommitmentTerms {
  sku: string;
  quantity: DecimalString;
  unit: string;
  deadline: ISO8601;
  special_instructions?: string | null;
}

export interface Commitment {
  tenant_id: string;
  commitment_id: string;
  order_id: string;
  customer_id: string;
  terms: CommitmentTerms;
  agreement_state: AgreementState;
  feasibility_state: FeasibilityState;
  risk_state: RiskState;
  recovery_state: RecoveryState;
  fulfilment_state: FulfilmentState;
  commitment_version: number;
  evidence_refs: string[];
  updated_at: ISO8601;
}

export interface ConstraintReason {
  code: string;
  resource_id: string;
  shortage?: DecimalString | null;
  unit?: string | null;
  deadline?: ISO8601 | null;
  severity: "HARD" | "SOFT" | "INFORMATIONAL";
  evidence_refs: string[];
}

export interface FeasibilityAssessment {
  assessment_id: string;
  tenant_id: string;
  commitment_id: string;
  commitment_version: number;
  snapshot_version: number;
  status: FeasibilityState;
  constraints: ConstraintReason[];
  /** Downstream commitments impacted by this evaluation (the impact set only, not the evaluated commitment itself). Empty list [] represents an isolated evaluation or no downstream disruption. */
  affected_commitment_ids: string[];
  evidence_refs: string[];
  solver_status: SolverStatus;
  assumptions: string[];
  assessed_at: ISO8601;
}

export interface PlannedAction {
  action_id: string;
  type: string;
  requires_approval: boolean;
  idempotency_key: string;
  parameters: Record<string, unknown>;
  preconditions: string[];
}

export interface RecoveryPlan {
  tenant_id: string;
  recovery_case_id: string;
  plan_id: string;
  plan_version: number;
  commitment_id: string;
  based_on_assessment_id: string;
  snapshot_version: number;
  feasibility_status: FeasibilityState;
  estimated_extra_cost: DecimalString;
  currency: string;
  estimated_delay_minutes: number;
  risks: string[];
  actions: PlannedAction[];
  approval_state: ApprovalState;
  execution_state: ExecutionState;
}

export interface CommunicationRequest {
  communication_id: string;
  tenant_id: string;
  commitment_id: string;
  proposal_id: string;
  proposal_version: number;
  recipient_identity_id: string;
  channel: CommunicationChannel;
  message_status: MessageStatus;
  message_template_key: string;
  approval_state: ApprovalState;
  confirmation_id: string;
  confirmation_state: ConfirmationState;
  expires_at: ISO8601;
  evidence_refs: string[];
}

export interface Confirmation {
  confirmation_id: string;
  tenant_id: string;
  commitment_id: string;
  proposal_id: string;
  proposal_version: number;
  recipient_identity_id: string;
  state: ConfirmationState;
  accepted_terms?: Record<string, unknown> | null;
  response_evidence_refs: string[];
  expires_at: ISO8601;
  responded_at?: ISO8601 | null;
}

export interface DomainEvent {
  event_id: string;
  schema_version: number;
  event_type: string;
  tenant_id: string;
  commitment_id?: string | null;
  commitment_version?: number | null;
  correlation_id: string;
  causation_id?: string | null;
  occurred_at: ISO8601;
  payload: Record<string, unknown>;
}

export type OutboxStatus = "PENDING" | "PUBLISHED" | "FAILED" | "DEAD_LETTER";

export interface CommitmentCreateRequest {
  commitment_id?: string | null;
  order_id: string;
  customer_id: string;
  terms: CommitmentTerms;
  evidence_refs: string[];
  causation_id?: string | null;
}

export type CommitmentTransitionDimension =
  | "agreement"
  | "feasibility"
  | "risk"
  | "recovery"
  | "fulfilment";

export interface CommitmentTransitionRequest {
  dimension: CommitmentTransitionDimension;
  target_state: string;
  expected_commitment_version: number;
  evidence_refs: string[];
  reason: string;
  causation_id?: string | null;
}

export interface AuditEvent {
  audit_id: string;
  tenant_id: string;
  commitment_id: string;
  event_type: string;
  actor_id: string;
  actor_role: string;
  dimension: string;
  previous_state: Record<string, unknown> | null;
  new_state: Record<string, unknown>;
  evidence_refs: string[];
  reason: string;
  correlation_id: string;
  causation_id?: string | null;
  occurred_at: ISO8601;
}

export interface CommitmentTransitionResponse {
  commitment: Commitment;
  audit_event: AuditEvent;
  domain_event: DomainEvent;
}

export type AttentionCategory =
  | "STALE_PLAN"
  | "UNKNOWN_FEASIBILITY"
  | "MANUAL_REVIEW"
  | "FAILED_EXECUTION"
  | "UNRESOLVED_CONFIRMATION";

export type AttentionSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

export interface AttentionItem {
  commitment_id: string;
  order_id: string;
  category: AttentionCategory;
  severity: AttentionSeverity;
  summary: string;
  deep_link_path: string;
  updated_at: ISO8601;
}

export interface OverviewCounts {
  requested: number;
  confirmed: number;
  at_risk: number;
  pending_approval: number;
  execution_in_progress: number;
  awaiting_confirmation: number;
  fulfilled: number;
}

export interface OverviewCommitmentSummary {
  commitment_id: string;
  order_id: string;
  customer_id: string;
  agreement_state: AgreementState;
  feasibility_state: FeasibilityState;
  risk_state: RiskState;
  recovery_state: RecoveryState;
  fulfilment_state: FulfilmentState;
  commitment_version: number;
  terms: CommitmentTerms;
  evidence_refs: string[];
  updated_at: ISO8601;
}

export interface OverviewResponse {
  tenant_id: string;
  actor_id: string;
  actor_role: string;
  integration_mode: "SYNTHETIC";
  last_updated_at: ISO8601;
  counts: OverviewCounts;
  attention_queue: AttentionItem[];
  commitments: OverviewCommitmentSummary[];
}

export type SourceFeature =
  | "F1_CONTEXT"
  | "F2_FEASIBILITY"
  | "F3_RECOVERY"
  | "F4_COMMUNICATION"
  | "CORE";

export interface TimelineEntry {
  entry_id: string;
  occurred_at: ISO8601;
  actor_id: string;
  actor_role: string;
  source_feature: SourceFeature;
  event_type: string;
  action: string;
  previous_state: Record<string, unknown> | null;
  new_state: Record<string, unknown>;
  commitment_version?: number | null;
  correlation_id: string;
  causation_id?: string | null;
  approval_reason?: string | null;
  evidence_refs: string[];
  context_id?: string | null;
  assessment_id?: string | null;
  recovery_case_id?: string | null;
  communication_id?: string | null;
  proposal_id?: string | null;
}

export interface ProposalCreateRequest {
  proposal_id?: string | null;
  proposal_version: number;
  expected_commitment_version: number;
  revised_terms?: CommitmentTerms | null;
  reason: string;
  evidence_refs: string[];
  causation_id?: string | null;
}

export interface ProposalConfirmRequest {
  proposal_id: string;
  proposal_version: number;
  expected_commitment_version: number;
  decision: "ACCEPT" | "REJECT";
  evidence_refs: string[];
  reason: string;
  causation_id?: string | null;
}

export interface RecordFulfilmentRequest {
  expected_commitment_version: number;
  fulfilment_state: "FULFILLED" | "PARTIALLY_FULFILLED";
  evidence_refs: string[];
  reason: string;
  causation_id?: string | null;
}

export interface RecoveryStartRequest {
  expected_commitment_version: number;
  reason: string;
  causation_id?: string | null;
}

export interface RecoveryExecuteRequest {
  expected_commitment_version: number;
  plan: RecoveryPlan;
  current_snapshot_version: number;
  approved_at: ISO8601;
  approval_expires_at: ISO8601;
  revised_terms?: CommitmentTerms | null;
  reason: string;
  causation_id?: string | null;
}

export interface ResourceStock {
  tenant_id: string;
  resource_id: string;
  total_quantity: DecimalString;
  reserved_quantity: DecimalString;
  available_quantity: DecimalString;
  unit: string;
  snapshot_version: number;
  updated_at: ISO8601;
}

export interface ResourceReservation {
  reservation_id: string;
  tenant_id: string;
  commitment_id: string;
  plan_id: string;
  action_id: string;
  idempotency_key: string;
  resource_id: string;
  quantity: DecimalString;
  status: "ACTIVE" | "RELEASED" | "CONSUMED";
  created_at: ISO8601;
}

