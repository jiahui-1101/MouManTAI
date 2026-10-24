import { authHeaders, type RequestAuthHeaders } from '../../shared/api';
import { PreviewError } from './api';
import type {
  AssociationDecisionRequest,
  AttachmentRecord,
  ContextReviewRecord,
  ContextReviewRequest,
  ContextUpdateRequest,
  DevelopmentContext,
  DocumentExtractionResult,
  ExtractionAttemptRecord,
  ExtractionHistoryResponse,
  IngestResponse,
  MessageAssociationRecord,
  MessagePage,
  OrderContextRecord,
  OrderContextVersionRecord,
  ProcessResponse,
  RawMessageEnvelope,
  StoredMessage,
} from './types';

export interface MessageQuery {
  channel: string;
  search: string;
  processing: string;
  offset: number;
  limit?: number;
}

export function getReviewCatalog(headers?: Record<string, string>): Promise<{ sku: string; unit: string }[]> {
  return request('/v1/contexts/catalog', headers ? { headers } : undefined);
}

export function notifyReviewContextSaved(): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event('moumantai:review-context-saved'));
}

export const RESOLVED_TASKS_KEY = 'moumantai:resolved_tasks';

export function getResolvedTaskIds(): Set<string> {
  if (typeof window === 'undefined') return new Set();
  try {
    const raw = localStorage.getItem(RESOLVED_TASKS_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

export function markTaskResolved(taskId: string): void {
  if (typeof window === 'undefined' || !taskId) return;
  try {
    const set = getResolvedTaskIds();
    set.add(taskId);
    localStorage.setItem(RESOLVED_TASKS_KEY, JSON.stringify(Array.from(set)));
  } catch { /* ignore */ }
}

export function unmarkTaskResolved(taskId: string): void {
  if (typeof window === 'undefined' || !taskId) return;
  try {
    const set = getResolvedTaskIds();
    set.delete(taskId);
    localStorage.setItem(RESOLVED_TASKS_KEY, JSON.stringify(Array.from(set)));
  } catch { /* ignore */ }
}

export interface OperationalApi {
  config(): Promise<DevelopmentContext>;
  list(query: MessageQuery): Promise<MessagePage>;
  detail(id: string): Promise<StoredMessage>;
  deleteMessage(id: string, headers?: Record<string, string>): Promise<{ status: string; message_id: string }>;
  ingest(envelope: RawMessageEnvelope): Promise<IngestResponse>;
  process(id: string, reprocess?: boolean, headers?: Record<string, string>): Promise<ProcessResponse>;
  getExtraction(id: string): Promise<ExtractionAttemptRecord>;
  listAttempts(id: string): Promise<ExtractionHistoryResponse>;
  getAssociation(id: string): Promise<MessageAssociationRecord>;
  decideAssociation(id: string, request: AssociationDecisionRequest, headers?: Record<string, string>): Promise<MessageAssociationRecord>;
  getContext(id: string, headers?: Record<string, string>): Promise<OrderContextRecord>;
  getContextByOrder(orderId: string, headers?: Record<string, string>): Promise<OrderContextRecord>;
  createContextFromMessage(messageId: string): Promise<OrderContextRecord>;
  reviewContext(id: string, req: ContextReviewRequest, headers?: Record<string, string>): Promise<OrderContextRecord>;
  updateContext(id: string, req: ContextUpdateRequest, headers?: Record<string, string>): Promise<OrderContextRecord>;
  listContextVersions(id: string, headers?: Record<string, string>): Promise<OrderContextVersionRecord[]>;
  listContextReviews(id: string, headers?: Record<string, string>): Promise<ContextReviewRecord[]>;
  publishContext(id: string, headers?: Record<string, string>): Promise<OrderContextRecord>;
  getCatalog(): Promise<{ sku: string; unit: string }[]>;
  uploadAttachment(file: File): Promise<AttachmentRecord>;
  extractAttachment(evidenceRef: string): Promise<DocumentExtractionResult>;
  getAttachmentExtraction(evidenceRef: string): Promise<DocumentExtractionResult>;
  getAttachmentMetadata(evidenceRef: string): Promise<AttachmentRecord>;
  getAttachmentPageCount(evidenceRef: string): Promise<{ total_pages: number; media_type: string }>;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `Message request failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') {
        message = body.detail;
      } else if (Array.isArray(body.detail)) {
        message = body.detail.map((item: { msg?: string }) => item.msg ?? 'Invalid input').join('; ');
      } else if (body.detail && typeof body.detail === 'object') {
        if (Array.isArray(body.detail.reasons)) {
          message = `${body.detail.message || 'Validation failed'}: ${body.detail.reasons.join('; ')}`;
        } else if (body.detail.message) {
          message = body.detail.message;
        }
      } else if (body.details && typeof body.details === 'object') {
        if (Array.isArray(body.details.reasons)) {
          message = `${body.message || body.details.message || 'Validation failed'}: ${body.details.reasons.join('; ')}`;
        } else if (body.details.message || body.message) {
          message = body.details.message || body.message;
        }
      } else if (typeof body.message === 'string') {
        message = body.message;
      }
    } catch { /* Keep the status-based diagnostic when the server does not return JSON. */ }
    throw new PreviewError(message, response.status);
  }
  return response.json() as Promise<T>;
}

type Requester = <T>(path: string, options?: RequestInit) => Promise<T>;

function createOperationalApi(request: Requester): OperationalApi {
const processingRequests = new Map<string, Promise<ProcessResponse>>();
function processMessage(id: string, reprocess = false, headers: Record<string, string> = {}): Promise<ProcessResponse> {
  const identity = new Headers(headers);
  const key = JSON.stringify([id, identity.get('X-Tenant-ID'), identity.get('X-Actor-ID')]);
  const existing = processingRequests.get(key);
  if (existing) return existing;
  const promise = request<ProcessResponse>(`/v1/messages/${encodeURIComponent(id)}/process${reprocess ? '?reprocess=true' : ''}`, {
    method: 'POST', headers: { ...headers, 'X-P1-Operation-ID': crypto.randomUUID() },
  }).finally(() => processingRequests.delete(key));
  processingRequests.set(key, promise);
  return promise;
}

return {
  config: () => request('/dev/p1/config'),
  list: ({ channel, search, processing, offset, limit = 25 }) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (channel !== 'ALL') params.set('channel', channel);
    if (search) params.set('search', search);
    if (processing !== 'ALL') params.set('processing_status', processing);
    return request(`/v1/messages?${params}`);
  },
  detail: id => request(`/v1/messages/${encodeURIComponent(id)}`),
  deleteMessage: (id: string, headers: Record<string, string> = {}) =>
    request<{ status: string; message_id: string }>(`/v1/messages/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: { ...headers },
    }),
  ingest: envelope => request('/v1/messages/ingest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(envelope) }),
  process: processMessage,
  getExtraction: id => request(`/v1/messages/${encodeURIComponent(id)}/extraction`),
  listAttempts: id => request(`/v1/messages/${encodeURIComponent(id)}/attempts`),
  getAssociation: id => request(`/v1/messages/${encodeURIComponent(id)}/association`),
  decideAssociation: (id, req, headers = {}) =>
    request(`/v1/messages/${encodeURIComponent(id)}/association`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(req),
    }),
  getContext: (id, headers) => request(`/v1/contexts/${encodeURIComponent(id)}`, headers ? { headers } : undefined),
  getContextByOrder: (orderId, headers) => request(`/v1/contexts/by-order/${encodeURIComponent(orderId)}`, headers ? { headers } : undefined),
  createContextFromMessage: messageId =>
    request(`/v1/contexts/from-message/${encodeURIComponent(messageId)}`, { method: 'POST' }),
  reviewContext: (id, req, headers = {}) =>
    request(`/v1/contexts/${encodeURIComponent(id)}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(req),
    }),
  updateContext: (id, req, headers = {}) =>
    request(`/v1/contexts/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(req),
    }),
  listContextVersions: (id, headers) => request(`/v1/contexts/${encodeURIComponent(id)}/versions`, headers ? { headers } : undefined),
  listContextReviews: (id, headers) => request(`/v1/contexts/${encodeURIComponent(id)}/reviews`, headers ? { headers } : undefined),
  publishContext: (id, headers = {}) =>
    request(`/v1/contexts/${encodeURIComponent(id)}/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
    }),
  getCatalog: () => request('/v1/contexts/catalog'),
  uploadAttachment: file => {
    const formData = new FormData();
    formData.append('file', file);
    return request('/v1/attachments/upload', {
      method: 'POST',
      body: formData,
    });
  },
  extractAttachment: evidenceRef =>
    request(`/v1/attachments/${encodeURIComponent(evidenceRef)}/extract`, { method: 'POST' }),
  getAttachmentExtraction: evidenceRef =>
    request(`/v1/attachments/${encodeURIComponent(evidenceRef)}/extraction`),
  getAttachmentMetadata: evidenceRef =>
    request(`/v1/attachments/${encodeURIComponent(evidenceRef)}/metadata`),
  getAttachmentPageCount: evidenceRef =>
    request(`/v1/attachments/${encodeURIComponent(evidenceRef)}/page-count`),
};


}

export const operationalApi = createOperationalApi(request);

export function createScopedOperationalApi(auth: RequestAuthHeaders): OperationalApi {
  const identity = authHeaders(auth);
  return createOperationalApi(<T,>(path: string, options?: RequestInit) => {
    const headers = new Headers(options?.headers);
    for (const [name, value] of Object.entries(identity)) headers.set(name, value);
    return request<T>(path, { ...options, headers });
  });
}
