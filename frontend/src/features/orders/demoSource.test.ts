import { afterEach, describe, expect, it, vi } from 'vitest';
import { mapDemoDetail, mapDemoQueue, ordersDemoEnabled, type DemoDetailDto, type DemoQueueDto } from './demoSource';
import { initialFilters, selectOrders } from './queue';

const auth = { tenantId: 'tenant_demo_01', actorId: 'user_owner_01' };
export function demoDto(): DemoQueueDto {
  return { schema_version: 'orders-demo-v1', tenant_id: auth.tenantId, actor_id: auth.actorId,
    read_authorized: true, integration_mode: 'SYNTHETIC', evidence_tier: 'DEMO-ONLY',
    source: 'synthetic://orders-demo-v1', source_at: '2026-10-24T08:00:00Z', coverage: 'partial',
    orders: [{ order_id: 'ord_hero_001', commitment_id: 'com_001', customer_display_name: 'Demo customer',
      requested_items: [{ sku: 'BURGER', quantity: '100', unit: 'pcs' }],
      requested_delivery_at: '2026-10-26T08:00:00Z', received_at: '2026-10-23T01:00:00Z',
      lifecycle_status: 'UNKNOWN', source_channel: 'SYNTHETIC', evidence_refs: ['synthetic://request'] }] };
}
afterEach(() => vi.unstubAllEnvs());
describe('synthetic queue boundary', () => {
  it('keeps partial coverage, source time and unknown lifecycle with working search', () => {
    const mapped = mapDemoQueue(demoDto(), auth);
    expect(mapped.coverage).toBe('partial');
    expect(mapped.asOf).toBe('2026-10-24T08:00:00Z');
    expect(mapped.items[0].status).toBe('UNKNOWN');
    expect(selectOrders(mapped.items, { ...initialFilters, search: 'hero' })).toHaveLength(1);
    expect(selectOrders(mapped.items, { ...initialFilters, product: 'burger' })).toHaveLength(1);
    expect(selectOrders(mapped.items, { ...initialFilters, status: 'ACCEPTED' })).toHaveLength(0);
  });
  it('rejects cross-tenant, cross-actor, duplicate and fabricated acceptance', () => {
    expect(() => mapDemoQueue(demoDto(), { ...auth, tenantId: 'other' })).toThrow();
    expect(() => mapDemoQueue(demoDto(), { ...auth, actorId: 'user_staff_01' })).toThrow();
    const dto = demoDto(); dto.orders.push(dto.orders[0]);
    expect(() => mapDemoQueue(dto, auth)).toThrow();
    const wrong = demoDto(); Object.assign(wrong.orders[0], { lifecycle_status: 'ACCEPTED' });
    expect(() => mapDemoQueue(wrong, auth)).toThrow();
  });
  it('requires explicit demo mode and flag, including during production builds', () => {
    vi.stubEnv('VITE_ORDERS_DEMO', '1'); vi.stubEnv('MODE', 'production');
    expect(ordersDemoEnabled()).toBe(false);
    vi.stubEnv('MODE', 'demo'); expect(ordersDemoEnabled()).toBe(true);
    vi.stubEnv('VITE_ORDERS_DEMO', '0'); expect(ordersDemoEnabled()).toBe(false);
  });
});

it('maps detail without accepting Core state or missing assessment provenance', () => {
  const q = demoDto();
  const dto: DemoDetailDto = { ...q, order: q.orders[0], related_commitment: { tenant_id: auth.tenantId,
    order_id: 'ord_hero_001', commitment_id: 'com_001', version: 5, agreement_state: 'CONFIRMED',
    risk_state: 'AT_RISK', recovery_state: 'RECOVERY_REQUIRED', evidence_refs: ['synthetic://core'] },
    assessment_availability: 'UNVERIFIABLE', assessment_reason: 'Missing provenance', assessments: [] };
  const mapped = mapDemoDetail(dto, 'ord_hero_001', auth);
  expect(mapped.status).toBe('UNKNOWN');
  expect(mapped.assessment?.sourceVerified).toBe(false);
  expect(mapped.currentDeadline).toBe(q.orders[0].requested_delivery_at);
  expect(mapped.commitmentId).toBe('com_001');
  expect(() => mapDemoDetail(dto, 'com_001', auth)).toThrow();
  Object.assign(dto.related_commitment!, { tenant_id: 'other' });
  expect(() => mapDemoDetail(dto, 'ord_hero_001', auth)).toThrow();
});
