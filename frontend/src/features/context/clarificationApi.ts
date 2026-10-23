/**
 * v2.2 Clarification & Issue Management API Adapter
 *
 * Implements target contract for upcoming v2.2 backend endpoints:
 *   GET  /v1/conversations/{id}/issues
 *   POST /v1/conversations/{id}/clarify
 *
 * Adheres to:
 * - FE-CUS-04: Deterministic validator progress tracking per issue.
 * - Automatic escalation after 2 consecutive answered no-progress attempts.
 * - Single reminder tracking in a separate follow-up lane.
 * - Strict non-simulation: Returns PREVIEW ONLY · NOT SENT when backend send route is absent.
 */

import { reviewCandidates } from './reviewCandidates';
import type {
  ClarificationIssue,
  ConversationIssuesResponse,
  SendClarificationRequest,
  SendClarificationResponse,
} from './clarificationModels';
import type { OrderContextRecord } from './types';

let cachedClarificationCapability: 'AUTHORITATIVE' | 'PROVISIONAL' | null = null;

export async function detectClarificationCapability(conversationId = 'probe'): Promise<'AUTHORITATIVE' | 'PROVISIONAL'> {
  if (cachedClarificationCapability !== null) return cachedClarificationCapability;
  try {
    const res = await fetch(`/v1/conversations/${encodeURIComponent(conversationId)}/issues`, {
      method: 'GET',
    });
    if (res.status !== 404 && res.status !== 405 && res.status !== 501 && res.status < 500) {
      cachedClarificationCapability = 'AUTHORITATIVE';
    } else {
      cachedClarificationCapability = 'PROVISIONAL';
    }
  } catch {
    cachedClarificationCapability = 'PROVISIONAL';
  }
  return cachedClarificationCapability;
}

export function resetClarificationCapabilityCache(): void {
  cachedClarificationCapability = null;
}

export async function getConversationIssues(
  conversationId: string,
  context?: OrderContextRecord | null
): Promise<ConversationIssuesResponse> {
  const capability = await detectClarificationCapability(conversationId);

  if (capability === 'AUTHORITATIVE') {
    const res = await fetch(`/v1/conversations/${encodeURIComponent(conversationId)}/issues`);
    if (res.ok) {
      const data = await res.json();
      return {
        ...data,
        source_mode: 'AUTHORITATIVE_BACKEND',
      };
    }
  }

  // Fallback: Provisional issue projection from verified OrderContextRecord
  return projectIssuesFromContext(conversationId, context);
}

export async function sendClarification(
  req: SendClarificationRequest,
  actorHeaders: Record<string, string> = {
    'X-Actor-ID': 'user_staff_01',
    'X-Actor-Role': 'STAFF',
  }
): Promise<SendClarificationResponse> {
  const capability = await detectClarificationCapability(req.conversation_id);

  if (capability === 'AUTHORITATIVE') {
    const res = await fetch(`/v1/conversations/${encodeURIComponent(req.conversation_id)}/clarify`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...actorHeaders,
      },
      body: JSON.stringify(req),
    });

    if (res.ok) {
      const data = await res.json();
      return {
        outbound_id: data.outbound_id || data.id,
        conversation_id: req.conversation_id,
        delivery_status: data.delivery_status || 'SENT',
        sent_at: data.sent_at || new Date().toISOString(),
        provider_reference: data.provider_reference,
        backend_status: 'SENT',
      };
    }

    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Clarification dispatch failed (${res.status})`);
  }

  // Explicit provisional safeguard: Do NOT simulate external dispatch.
  // Clarification drafts are captured locally / in reviewer notes only.
  return {
    outbound_id: `preview-${Date.now()}`,
    conversation_id: req.conversation_id,
    delivery_status: 'PREVIEW_NOT_SENT',
    backend_status: 'PREVIEW_NOT_SENT',
    error_reason:
      'Backend endpoint POST /v1/conversations/{id}/clarify is not deployed. PREVIEW ONLY · NOT SENT. The draft has been preserved for staff preview and note adoption without triggering external customer dispatch.',
  };
}

/**
 * Derives structured issues from an OrderContextRecord.
 */
function projectIssuesFromContext(
  conversationId: string,
  context?: OrderContextRecord | null
): ConversationIssuesResponse {
  if (!context) {
    return {
      conversation_id: conversationId,
      tenant_id: 'default',
      issues: [],
      total_turns_used: 0,
      max_turns_allowed: 2,
      has_escalated_issues: false,
      source_mode: 'PROVISIONAL_CONTEXT_PROJECTION',
    };
  }

  const issues: ClarificationIssue[] = [];
  const candidates = reviewCandidates(context);
  const missing = context.missing_fields || [];

  for (const field of missing) {
    const matchingCandidates = candidates.filter(c => c.field === field).map(c => c.value);
    issues.push({
      issue_id: `issue-${context.context_id}-${field}`,
      field_name: field,
      current_value: undefined,
      proposed_candidates: matchingCandidates,
      original_problem: `Missing required field: ${field}`,
      consecutive_no_progress_count: 0,
      status: 'UNRESOLVED',
      questions_sent: [],
      customer_responses: [],
    });
  }

  if (context.conflicts && context.conflicts.length > 0) {
    context.conflicts.forEach((conflict, idx) => {
      issues.push({
        issue_id: `issue-${context.context_id}-conflict-${idx}`,
        field_name: 'conflict',
        current_value: conflict,
        proposed_candidates: [],
        original_problem: conflict,
        consecutive_no_progress_count: 0,
        status: 'UNRESOLVED',
        questions_sent: [],
        customer_responses: [],
      });
    });
  }

  return {
    conversation_id: conversationId,
    tenant_id: context.tenant_id || 'default',
    issues,
    total_turns_used: 0,
    max_turns_allowed: 2,
    has_escalated_issues: issues.some(i => i.consecutive_no_progress_count >= 2),
    source_mode: 'PROVISIONAL_CONTEXT_PROJECTION',
  };
}
