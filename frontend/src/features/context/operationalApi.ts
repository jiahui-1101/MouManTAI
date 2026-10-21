import { PreviewError } from './api';
import type { DevelopmentContext, IngestResponse, MessagePage, RawMessageEnvelope, StoredMessage } from './types';

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
};
