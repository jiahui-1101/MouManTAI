import { apiRequest, authHeaders, ApiError, type RequestAuthHeaders } from '../../shared/api';
import type { OrderDetail, RequestMessage } from './detailTypes';

export interface OrderDetailSource {
  cacheKey: string;
  load: (id: string, auth: RequestAuthHeaders, signal: AbortSignal) => Promise<OrderDetail | null>;
}
export function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid source record');
  return value as Record<string, unknown>;
}
const optionalText = (value: unknown) => typeof value === 'string' ? value : null;
const textList = (value: unknown): string[] => Array.isArray(value) ? value.filter((s): s is string => typeof s === 'string') : [];

/** Verified legacy P1 DTO mapping. Readiness, context creation and publication are NOT order acceptance. */
export function mapLegacyContext(raw: unknown, id: string, tenant: string): OrderDetail {
  const ctx = record(raw);
  if (ctx.order_id !== id || ctx.tenant_id !== tenant || typeof ctx.context_id !== 'string' ||
      !Number.isInteger(ctx.context_version) || !Array.isArray(ctx.requested_items))
    throw new Error('Context identity or schema mismatch');
  const fields: OrderDetail['fields'] = [];
  const lines = ctx.requested_items.map(rawLine => {
    const line = record(rawLine);
    if (typeof line.sku !== 'string' || typeof line.quantity !== 'string' || typeof line.unit !== 'string')
      throw new Error('Invalid requested item');
    return { sku: line.sku, quantity: { amount: line.quantity, unit: line.unit } };
  });
  const evidence = ctx.field_evidence && typeof ctx.field_evidence === 'object' ? record(ctx.field_evidence) : {};
  for (const [name, value] of Object.entries({ requested_items: lines.map(l => `${l.sku}: ${l.quantity.amount} ${l.quantity.unit}`).join('; '),
    requested_delivery_at: optionalText(ctx.requested_delivery_at), special_instructions: optionalText(ctx.special_instructions) })) {
    fields.push({ name, value, status: 'UNVERIFIED', evidence: Array.isArray(evidence[name]) ? evidence[name].map((span: unknown) => {
      const item = record(span);
      return { ref: optionalText(item.evidence_ref) ?? 'P1 field evidence span', quote: optionalText(item.quote) };
    }) : [] });
  }
  for (const name of textList(ctx.missing_fields)) fields.push({ name, status: 'MISSING' });
  return { id, tenantId: tenant, customer: optionalText(ctx.customer_id), lines, fields,
    currentDeadline: optionalText(ctx.requested_delivery_at), instructions: optionalText(ctx.special_instructions),
    contextId: ctx.context_id, contextVersion: String(ctx.context_version), contextStatus: optionalText(ctx.status),
    contextUpdatedAt: optionalText(ctx.updated_at), fieldConflicts: textList(ctx.conflicts),
    commitmentId: optionalText(ctx.core_commitment_id), sourceWarnings: [
      'Legacy P1 context is available. Order lifecycle, immutable original deadline, original received time, information-completed time and pending-order assessment are not provided by this DTO.',
      'Context readiness and context version do not establish order acceptance, field VALID status or an order request version.',
    ] };
}

export function mapLegacyMessage(raw: unknown, id: string, tenant: string): RequestMessage {
  const message = record(raw); const envelope = record(message.raw);
  if (message.message_id !== id || envelope.tenant_id !== tenant) throw new Error('Message identity mismatch');
  return { id, text: optionalText(envelope.text), channel: optionalText(envelope.channel),
    receivedAt: optionalText(envelope.received_at),
    tier: envelope.adapter_mode === 'SYNTHETIC' ? 'DEMO-ONLY / SYNTHETIC' : 'Customer claim · source not independently verified' };
}

/** Real existing read endpoints only. Never calls proposed /v1/orders or assessment commands. */
export const legacyContextDetailSource: OrderDetailSource = {
  cacheKey: 'legacy-p1-context-read-v1',
  async load(id, auth, signal) {
    const read = (path: string) => apiRequest<unknown>(path, { headers: authHeaders(auth), signal });
    const raw = await read(`/v1/contexts/by-order/${encodeURIComponent(id)}`);
    return loadLegacyContextDetail(raw, id, auth, signal);
  },
};

/** Composite route reuses the context already read by P1, avoiding duplicate context reads. */
export async function loadLegacyContextDetail(raw: unknown, id: string, auth: RequestAuthHeaders, signal: AbortSignal) {
    const read = (path: string) => apiRequest<unknown>(path, { headers: authHeaders(auth), signal });
    const detail = mapLegacyContext(raw, id, auth.tenantId);
    const refs = textList(record(raw).source_message_ids);
    const messages = await Promise.all(refs.map(async messageId => {
      try { return mapLegacyMessage(await read(`/v1/messages/${encodeURIComponent(messageId)}`), messageId, auth.tenantId); }
      catch (error) {
        if (signal.aborted || !(error instanceof ApiError) || [401, 403].includes(error.status)) throw error;
        return { id: messageId, tier: 'Not verified', text: 'Source message unavailable' };
      }
    }));
    return { ...detail, messages };
}

/** Future verified v2.2 integration may inject a source; identity is checked again by the page. */
