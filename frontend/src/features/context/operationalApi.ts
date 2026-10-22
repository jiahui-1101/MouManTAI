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
}

export interface OperationalApi {
  config(): Promise<DevelopmentContext>;
  list(query: MessageQuery): Promise<MessagePage>;
  detail(id: string): Promise<StoredMessage>;
  ingest(envelope: RawMessageEnvelope): Promise<IngestResponse>;
  process(id: string, reprocess?: boolean): Promise<ProcessResponse>;
  getExtraction(id: string): Promise<ExtractionAttemptRecord>;
  listAttempts(id: string): Promise<ExtractionHistoryResponse>;
  getAssociation(id: string): Promise<MessageAssociationRecord>;
  decideAssociation(id: string, request: AssociationDecisionRequest, headers?: Record<string, string>): Promise<MessageAssociationRecord>;
  getContext(id: string): Promise<OrderContextRecord>;
  getContextByOrder(orderId: string): Promise<OrderContextRecord>;
  createContextFromMessage(messageId: string): Promise<OrderContextRecord>;
  reviewContext(id: string, req: ContextReviewRequest, headers?: Record<string, string>): Promise<OrderContextRecord>;
  updateContext(id: string, req: ContextUpdateRequest, headers?: Record<string, string>): Promise<OrderContextRecord>;
  listContextVersions(id: string): Promise<OrderContextVersionRecord[]>;
  listContextReviews(id: string): Promise<ContextReviewRecord[]>;
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
      if (typeof body.detail === 'string') message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((item: { msg?: string }) => item.msg ?? 'Invalid input').join('; ');
    } catch { /* Keep the status-based diagnostic when the server does not return JSON. */ }
    throw new PreviewError(message, response.status);
  }
  return response.json() as Promise<T>;
}

const processingRequests = new Map<string, Promise<ProcessResponse>>();
function processMessage(id: string, reprocess = false): Promise<ProcessResponse> {
  const existing = processingRequests.get(id);
  if (existing) return existing;
  const promise = request<ProcessResponse>(`/v1/messages/${encodeURIComponent(id)}/process${reprocess ? '?reprocess=true' : ''}`, {
    method: 'POST', headers: { 'X-P1-Operation-ID': crypto.randomUUID() },
  }).finally(() => processingRequests.delete(id));
  processingRequests.set(id, promise);
  return promise;
}

export const operationalApi: OperationalApi = {
  config: () => request('/dev/p1/config'),
  list: ({ channel, search, processing, offset }) => {
    const params = new URLSearchParams({ limit: '25', offset: String(offset) });
    if (channel !== 'ALL') params.set('channel', channel);
    if (search) params.set('search', search);
    if (processing !== 'ALL') params.set('processing_status', processing);
    return request(`/v1/messages?${params}`);
  },
  detail: id => request(`/v1/messages/${encodeURIComponent(id)}`),
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
  getContext: id => request(`/v1/contexts/${encodeURIComponent(id)}`),
  getContextByOrder: orderId => request(`/v1/contexts/by-order/${encodeURIComponent(orderId)}`),
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
  listContextVersions: id => request(`/v1/contexts/${encodeURIComponent(id)}/versions`),
  listContextReviews: id => request(`/v1/contexts/${encodeURIComponent(id)}/reviews`),
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

