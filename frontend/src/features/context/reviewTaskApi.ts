/**
 * v2.2 Human Review Task API Adapter
 *
 * Implements dual-mode operation:
 * 1. AUTHORITATIVE_BACKEND_QUEUE: Uses GET /v1/reviews and POST /v1/reviews/{id}/resolve when deployed.
 * 2. PROVISIONAL_INQUIRY_PROJECTION: Falls back to verified P1 context & message operational APIs
 *    (POST /v1/contexts/{id}/review) when the standalone task queue is not yet mounted.
 *
 * Adheres strictly to optimistic locking: always transmits version guards to prevent race conditions.
 */

import { operationalApi } from './operationalApi';
import type {
  ReviewTask,
  ReviewTaskQuery,
  ResolveReviewTaskRequest,
  ResolveReviewTaskResponse,
  ReviewTaskPriority,
  ReviewTaskType,
} from './reviewTaskModels';
import type { StoredMessage, OrderContextRecord } from './types';

let cachedQueueCapability: 'AUTHORITATIVE' | 'PROVISIONAL' | null = null;

export async function detectReviewTaskCapability(): Promise<'AUTHORITATIVE' | 'PROVISIONAL'> {
  if (cachedQueueCapability !== null) return cachedQueueCapability;
  try {
    const res = await fetch('/v1/reviews?limit=1', { method: 'GET' });
    if (res.ok) {
      cachedQueueCapability = 'AUTHORITATIVE';
    } else {
      cachedQueueCapability = 'PROVISIONAL';
    }
  } catch {
    cachedQueueCapability = 'PROVISIONAL';
  }
  return cachedQueueCapability;
}

export function resetReviewTaskCapabilityCache(): void {
  cachedQueueCapability = null;
}

export interface ReviewTaskListResult {
  tasks: ReviewTask[];
  total: number;
  mode: 'AUTHORITATIVE_BACKEND_QUEUE' | 'PROVISIONAL_INQUIRY_PROJECTION';
}

export async function listReviewTasks(query: ReviewTaskQuery = {}): Promise<ReviewTaskListResult> {
  const capability = await detectReviewTaskCapability();

  if (capability === 'AUTHORITATIVE') {
    const params = new URLSearchParams();
    if (query.limit) params.set('limit', String(query.limit));
    if (query.offset) params.set('offset', String(query.offset));
    if (query.status && query.status !== 'ALL') params.set('status', query.status);
    if (query.priority && query.priority !== 'ALL') params.set('priority', query.priority);
    if (query.task_type && query.task_type !== 'ALL') params.set('task_type', query.task_type);
    if (query.search) params.set('search', query.search);

    const res = await fetch(`/v1/reviews?${params.toString()}`);
    if (res.ok) {
      const data = await res.json();
      return {
        tasks: (data.items || []).map((t: ReviewTask) => ({
          ...t,
          source_mode: 'AUTHORITATIVE_BACKEND_QUEUE' as const,
        })),
        total: data.total ?? data.items?.length ?? 0,
        mode: 'AUTHORITATIVE_BACKEND_QUEUE',
      };
    }
    // If endpoint fails unexpectedly, fall through to provisional
  }

  // Fallback: Provisional projection from verified P1 messages and contexts
  const messagePage = await operationalApi.list({
    channel: 'ALL',
    processing: 'ALL',
    search: query.search || '',
    offset: query.offset || 0,
    limit: query.limit || 50,
  });

  const projectedTasks: ReviewTask[] = messagePage.items.map(msg => projectMessageToReviewTask(msg));

  // Filter in memory for provisional mode
  const filtered = projectedTasks.filter(task => {
    if (query.status && query.status !== 'ALL' && task.status !== query.status) return false;
    if (query.priority && query.priority !== 'ALL' && task.priority !== query.priority) return false;
    if (query.task_type && query.task_type !== 'ALL' && task.task_type !== query.task_type) return false;
    return true;
  });

  return {
    tasks: filtered,
    total: messagePage.total ?? filtered.length,
    mode: 'PROVISIONAL_INQUIRY_PROJECTION',
  };
}

export async function getReviewTask(taskId: string): Promise<ReviewTask> {
  const capability = await detectReviewTaskCapability();

  if (capability === 'AUTHORITATIVE') {
    const res = await fetch(`/v1/reviews/${encodeURIComponent(taskId)}`);
    if (res.ok) {
      const task = await res.json();
      return {
        ...task,
        source_mode: 'AUTHORITATIVE_BACKEND_QUEUE',
      };
    }
  }

  // Fallback: load message detail and project
  const msg = await operationalApi.detail(taskId);
  return projectMessageToReviewTask(msg);
}

export async function resolveReviewTask(
  taskId: string,
  req: ResolveReviewTaskRequest,
  contextId?: string,
  actorHeaders: Record<string, string> = {
    'X-Actor-ID': 'user_staff_01',
    'X-Actor-Role': 'STAFF',
  }
): Promise<ResolveReviewTaskResponse> {
  const capability = await detectReviewTaskCapability();

  if (capability === 'AUTHORITATIVE') {
    const res = await fetch(`/v1/reviews/${encodeURIComponent(taskId)}/resolve`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...actorHeaders,
      },
      body: JSON.stringify(req),
    });

    if (res.ok) {
      return res.json();
    }
    // If 409 conflict or other error, read details
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody.detail || `Backend resolution failed (${res.status})`);
  }

  // Fallback: Execute via verified P1 context review
  if (!contextId) {
    throw new Error(
      'Target context ID required to resolve review in provisional mode (POST /v1/contexts/{id}/review).'
    );
  }

  const actionMap: Record<string, 'EDIT_FIELD' | 'ACCEPT_EXTRACTION' | 'REQUEST_MORE_INFO' | 'MARK_UNRESOLVED'> = {
    RESOLVED_WITH_EDITS: 'EDIT_FIELD',
    ACCEPTED_EXTRACTION: 'ACCEPT_EXTRACTION',
    REQUEST_MORE_INFO: 'REQUEST_MORE_INFO',
    MARK_UNRESOLVED: 'MARK_UNRESOLVED',
    ESCALATE_TO_MANAGER: 'REQUEST_MORE_INFO',
  };

  const p1Action = actionMap[req.resolution] || 'EDIT_FIELD';

  const updatedContext: OrderContextRecord = await operationalApi.reviewContext(
    contextId,
    {
      expected_context_version: req.expected_task_version,
      action: p1Action,
      field_edits: req.field_edits || {},
      note: req.note,
    },
    actorHeaders
  );

  return {
    task_id: taskId,
    status: req.resolution === 'MARK_UNRESOLVED' ? 'OPEN' : 'RESOLVED',
    resolved_by: actorHeaders['X-Actor-ID'] || 'user_staff_01',
    resolved_at: new Date().toISOString(),
    resolution: req.resolution,
    updated_context_version: updatedContext.context_version,
  };
}

/**
 * Projects a verified P1 StoredMessage into a ReviewTask representation.
 */
function projectMessageToReviewTask(msg: StoredMessage): ReviewTask {
  let taskType: ReviewTaskType = 'AMBIGUITY';
  let priority: ReviewTaskPriority = 'MEDIUM';

  if (msg.processing_status === 'PROCESSING_FAILED') {
    taskType = 'FAILED_EXTRACTION';
    priority = 'HIGH';
  } else if (msg.processing_status === 'RECEIVED') {
    priority = 'MEDIUM';
  } else if (msg.processing_status === 'PROCESSED') {
    priority = 'LOW';
  }

  return {
    task_id: msg.message_id,
    tenant_id: 'default',
    task_type: taskType,
    status: msg.processing_status === 'PROCESSED' ? 'RESOLVED' : 'OPEN',
    priority,
    message_id: msg.message_id,
    channel: msg.raw?.channel || 'SYNTHETIC',
    snippet: msg.raw?.text || 'No text snippet',
    created_at: msg.ingested_at || new Date().toISOString(),
    updated_at: msg.ingested_at || new Date().toISOString(),
    version: 1,
    source_mode: 'PROVISIONAL_INQUIRY_PROJECTION',
    message: msg,
  };
}
