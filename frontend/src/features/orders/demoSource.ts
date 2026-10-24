import { apiRequest, authHeaders, type RequestAuthHeaders } from '../../shared/api';
import type { OrderQueueSource } from './api';
import type { OrderQueueSnapshot } from './types';
import type { OrderDetailSource } from './detailApi';
import type { OrderDetail } from './detailTypes';

/** Both explicit mode and flag are required; no automatic fallback on API errors. */
export const ordersDemoEnabled = () => import.meta.env.MODE === 'demo' && import.meta.env.VITE_ORDERS_DEMO === '1';

export interface DemoOrderDto {
  order_id: string; commitment_id: string; customer_display_name: string;
  requested_items: { sku: string; quantity: string; unit: string }[];
  requested_delivery_at: string; received_at: string; lifecycle_status: 'UNKNOWN';
  source_channel: 'SYNTHETIC'; evidence_refs: string[];
}
export interface DemoQueueDto {
  schema_version: 'orders-demo-v1'; tenant_id: string; actor_id: string; read_authorized: true;
  integration_mode: 'SYNTHETIC'; evidence_tier: 'DEMO-ONLY'; source: string;
  source_at: string; coverage: 'partial'; orders: DemoOrderDto[];
}
const nonempty = (v: unknown): v is string => typeof v === 'string' && !!v.trim();
const date = (v: unknown) => nonempty(v) && /(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
export function validateDemoQueue(dto: DemoQueueDto, auth: RequestAuthHeaders): DemoQueueDto {
  if (!dto || dto.tenant_id !== auth.tenantId || dto.actor_id !== auth.actorId || dto.read_authorized !== true ||
      dto.schema_version !== 'orders-demo-v1' || dto.integration_mode !== 'SYNTHETIC' || dto.evidence_tier !== 'DEMO-ONLY' ||
      dto.coverage !== 'partial' || !nonempty(dto.source) || !date(dto.source_at) || !Array.isArray(dto.orders) ||
      new Set(dto.orders.map(o => o.order_id)).size !== dto.orders.length || dto.orders.some(o =>
        ![o.order_id, o.commitment_id, o.customer_display_name].every(nonempty) || o.lifecycle_status !== 'UNKNOWN' ||
        o.source_channel !== 'SYNTHETIC' || !date(o.received_at) || !date(o.requested_delivery_at) ||
        !Array.isArray(o.evidence_refs) || !o.evidence_refs.length || !o.evidence_refs.every(nonempty) ||
        !Array.isArray(o.requested_items) || !o.requested_items.length || o.requested_items.some(l =>
          ![l.sku, l.unit].every(nonempty) || !/^[1-9][0-9]*$/.test(l.quantity))))
    throw new Error('Synthetic order source identity or contract mismatch');
  return dto;
}
export function mapDemoQueue(dto: DemoQueueDto, auth: RequestAuthHeaders): OrderQueueSnapshot {
  validateDemoQueue(dto, auth);
  return { coverage: dto.coverage, asOf: dto.source_at, items: dto.orders.map(o => ({
    id: o.order_id, customer: o.customer_display_name, status: o.lifecycle_status,
    deadline: o.requested_delivery_at, receivedAt: o.received_at, channel: o.source_channel,
    lines: o.requested_items.map(l => ({ product: l.sku, quantity: l.quantity, unit: l.unit })),
    evidenceTier: 'SYNTHETIC',
  })) };
}
export const demoOrderQueueSource: OrderQueueSource = {
  cacheKey: 'synthetic-orders-demo-v1',
  async load(auth, signal) {
    return mapDemoQueue(await apiRequest<DemoQueueDto>('/v1/demo/orders', { headers: authHeaders(auth), signal }), auth);
  },
};

export interface DemoDetailDto {
  tenant_id: string; actor_id: string; integration_mode: 'SYNTHETIC'; evidence_tier: 'DEMO-ONLY';
  source_at: string; source: string; order: DemoOrderDto;
  related_commitment: { commitment_id: string; order_id: string; tenant_id: string; version: number;
    agreement_state: string; risk_state: string; recovery_state: string; evidence_refs: string[] } | null;
  assessment_availability: 'UNAVAILABLE' | 'UNVERIFIABLE' | 'HISTORICAL_ONLY';
  assessment_reason: string; assessments: unknown[];
}
export function mapDemoDetail(dto: DemoDetailDto, id: string, auth: RequestAuthHeaders): OrderDetail {
  validateDemoQueue({ ...dto, schema_version: 'orders-demo-v1', coverage: 'partial', read_authorized: true, orders: [dto.order] }, auth);
  const o = dto.order; const c = dto.related_commitment;
  if (o.order_id !== id || (c && (c.tenant_id !== auth.tenantId || c.order_id !== id || c.commitment_id !== o.commitment_id)) ||
      !['UNAVAILABLE', 'UNVERIFIABLE', 'HISTORICAL_ONLY'].includes(dto.assessment_availability) ||
      !nonempty(dto.assessment_reason) || !Array.isArray(dto.assessments)) throw new Error('Synthetic detail association mismatch');
  return { id, tenantId: dto.tenant_id, customer: o.customer_display_name, channel: o.source_channel,
    receivedAt: o.received_at, originalDeadline: o.requested_delivery_at, currentDeadline: o.requested_delivery_at,
    status: o.lifecycle_status, commitmentId: c?.commitment_id,
    lines: o.requested_items.map(l => ({ sku: l.sku, product: l.sku, quantity: { amount: l.quantity, unit: l.unit } })),
    fields: [{ name: 'Synthetic original request', value: dto.source, status: 'SYNTHETIC', evidence: o.evidence_refs.map(ref => ({ ref })) }],
    assessment: { freshness: 'UNKNOWN', sourceVerified: false, complete: false, status: 'UNKNOWN',
      reasons: [dto.assessment_reason], missingEvidence: ['Verified request version and current P2 operational snapshot'] },
    pricing: { access: auth.actorId.includes('staff') ? 'REDACTED' : 'UNKNOWN' },
    sourceWarnings: ['SYNTHETIC / DEMO-ONLY request. Lifecycle Unknown; no acceptance, delivery or reservation evidence is inferred.',
      `Source timestamp: ${dto.source_at}. Inventory/BOM, capacity and expiry assessment unavailable.`,
      `${dto.assessment_availability}: ${dto.assessment_reason}`,
      ...(c ? [`Related synthetic Core commitment ${c.commitment_id} v${c.version}: agreement ${c.agreement_state}; risk ${c.risk_state}; recovery ${c.recovery_state}. These are separate from order lifecycle.`] : ['Core association unavailable.'])],
  };
}
export const demoOrderDetailSource: OrderDetailSource = {
  cacheKey: 'synthetic-order-detail-v1',
  async load(id, auth, signal) {
    const dto = await apiRequest<DemoDetailDto>(`/v1/demo/orders/${encodeURIComponent(id)}`, { headers: authHeaders(auth), signal });
    return mapDemoDetail(dto, id, auth);
  },
};
