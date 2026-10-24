/**
 * v2.2 Issue-Based Clarification Models (Target Contract)
 *
 * Designed for upcoming P1/P4 v2.2 backend endpoints:
 *   GET  /v1/conversations/{id}/issues
 *   POST /v1/conversations/{id}/clarify
 *
 * Reflects business invariants FE-CUS-04 and BE-CUS-04:
 * - Deterministic validators decide progress per issue.
 * - After two consecutive answered no-progress attempts, backend escalates to Human Review.
 * - No-reply timer is tracked in a separate follow-up lane with a deduplicated single reminder.
 * - Clarifications remain PREVIEW ONLY · NOT SENT until an authoritative backend send contract is deployed.
 */

export type ClarificationIssueStatus =
  | 'UNRESOLVED'
  | 'AWAITING_REPLY'
  | 'REMINDER_DUE'
  | 'REMINDER_SENT_ONCE'
  | 'RESOLVED'
  | 'ESCALATED_TO_HUMAN_REVIEW'
  | 'EXPIRED';

export type ClarificationDeliveryState =
  | 'PENDING'
  | 'SENT'
  | 'DELIVERED'
  | 'FAILED'
  | 'UNKNOWN'
  | 'PREVIEW_NOT_SENT';

export interface ClarificationQuestionRecord {
  question_id: string;
  question_text: string;
  sent_at: string;
  channel: string;
  provider_message_id?: string;
  provider_status: 'QUEUED' | 'SENT' | 'DELIVERED' | 'FAILED';
}

export interface ClarificationResponseRecord {
  response_id: string;
  inbound_message_id: string;
  text: string;
  received_at: string;
  was_effective_delta: boolean;
  validator_explanation?: string;
}

export interface ClarificationIssue {
  issue_id: string;
  field_name: string;
  current_value?: string;
  proposed_candidates: string[];
  original_problem: string;
  consecutive_no_progress_count: number;
  status: ClarificationIssueStatus;
  questions_sent: ClarificationQuestionRecord[];
  customer_responses: ClarificationResponseRecord[];
  escalation_reason?: string;
  resolved_at?: string;
  resolved_by?: string;
}

export interface ConversationIssuesResponse {
  conversation_id: string;
  tenant_id: string;
  issues: ClarificationIssue[];
  total_turns_used: number;
  max_turns_allowed: number;
  response_due_at?: string | null;
  reminder_due_at?: string | null;
  escalate_or_expire_at?: string | null;
  has_escalated_issues: boolean;
  source_mode: 'AUTHORITATIVE_BACKEND' | 'PROVISIONAL_CONTEXT_PROJECTION';
}

export interface SendClarificationRequest {
  conversation_id: string;
  context_id?: string;
  order_id?: string;
  issue_ids: string[];
  draft_text: string;
  channel: string;
  recipient_identity_id: string;
  approval_note?: string;
}

export interface SendClarificationResponse {
  outbound_id: string;
  conversation_id: string;
  delivery_status: ClarificationDeliveryState;
  sent_at?: string;
  provider_reference?: string;
  error_reason?: string;
  backend_status: 'SENT' | 'QUEUED' | 'PREVIEW_NOT_SENT';
}
