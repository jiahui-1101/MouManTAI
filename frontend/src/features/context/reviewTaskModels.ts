/**
 * v2.2 Human Review Task Models (Target Contract)
 *
 * Designed for upcoming P1/P4 v2.2 backend endpoints:
 *   GET  /v1/reviews
 *   POST /v1/reviews/{id}/resolve
 *
 * When backend endpoints are not yet deployed, the adapter operates in provisional mode,
 * projecting review items from verified P1 inbound messages and order contexts.
 */

import type { OrderContextRecord, StoredMessage } from './types';

export type ReviewTaskType =
  | 'AMBIGUITY'
  | 'FAILED_EXTRACTION'
  | 'COMMERCIAL_RISK'
  | 'UNRESOLVED_CLARIFICATION'
  | 'IDENTITY_CONFLICT'
  | 'POLICY_CONFLICT';

export type ReviewTaskStatus =
  | 'OPEN'
  | 'ASSIGNED'
  | 'IN_REVIEW'
  | 'RESOLVED'
  | 'ESCALATED_TO_MANAGER';

export type ReviewTaskPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT';

export type ReviewResolutionAction =
  | 'RESOLVED_WITH_EDITS'
  | 'ACCEPTED_EXTRACTION'
  | 'REQUEST_MORE_INFO'
  | 'MARK_UNRESOLVED'
  | 'ESCALATE_TO_MANAGER';

export interface ReviewTask {
  task_id: string;
  tenant_id: string;
  task_type: ReviewTaskType;
  status: ReviewTaskStatus;
  priority: ReviewTaskPriority;
  assigned_to?: string | null;
  message_id?: string;
  context_id?: string;
  order_id?: string;
  customer_id?: string;
  channel?: string;
  snippet?: string;
  qwen_intent?: string;
  uncertainty_reason?: string;
  created_at: string;
  updated_at: string;
  version: number;
  source_mode: 'AUTHORITATIVE_BACKEND_QUEUE' | 'PROVISIONAL_INQUIRY_PROJECTION';
  // Hydrated references
  context?: OrderContextRecord | null;
  message?: StoredMessage | null;
}

export interface ReviewTaskQuery {
  status?: ReviewTaskStatus | 'ALL';
  priority?: ReviewTaskPriority | 'ALL';
  task_type?: ReviewTaskType | 'ALL';
  assigned_to?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface ResolveReviewTaskRequest {
  expected_task_version: number;
  resolution: ReviewResolutionAction;
  field_edits?: Record<string, unknown>;
  note?: string;
  reassign_to?: string;
}

export interface ResolveReviewTaskResponse {
  task_id: string;
  status: ReviewTaskStatus;
  resolved_by: string;
  resolved_at: string;
  resolution: ReviewResolutionAction;
  updated_context_version?: number;
}
