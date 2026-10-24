import { afterEach, describe, expect, it, vi } from 'vitest';
import { legacyContextDetailSource, mapLegacyContext, mapLegacyMessage } from './detailApi';
import serializedContract from './__fixtures__/legacy-context.synthetic.json';

// DTO-shaped synthetic test records, not production defaults.
const context = () => ({ context_id: 'context-1', tenant_id: 'tenant-1', order_id: 'order-1', context_version: 3,
  status: 'INFORMATION_READY', customer_id: 'customer-1', requested_items: [{ sku: 'BREAD', quantity: '20', unit: 'pieces' }],
  requested_delivery_at: '2026-10-24T02:00:00Z', created_at: '2026-10-23T00:00:00Z', updated_at: '2026-10-24T01:00:00Z',
  source_message_ids: ['message-1'], field_evidence: { requested_items: [{ quote: '20 pieces', start: 0, end: 9 }] },
  missing_fields: ['location'], conflicts: ['Source conflict'], core_commitment_id: 'commitment-1' });
const message = () => ({ message_id: 'message-1', raw: { tenant_id: 'tenant-1', text: '20 pieces please', channel: 'WHATSAPP',
  received_at: '2026-10-23T00:00:00Z', adapter_mode: 'SYNTHETIC' } });
const auth = { tenantId: 'tenant-1', actorId: 'user_staff_01' };
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
afterEach(() => vi.unstubAllGlobals());

describe('Verified legacy DTO mapping', () => {
  it('maps responses emitted by the actual FastAPI/Pydantic read contract check', () => {
    const ctx = serializedContract.context;
    const mapped = mapLegacyContext(ctx, 'synthetic_detail_order', 'synthetic_detail_tenant');
    const source = mapLegacyMessage(serializedContract.message, serializedContract.message.message_id, mapped.tenantId);
    expect(mapped.contextId).toBe('synthetic_detail_context');
    expect(mapped.lines?.[0]).toMatchObject({ sku: 'BREAD', quantity: { amount: '20', unit: 'pieces' } });
    expect(source.tier).toBe('DEMO-ONLY / SYNTHETIC'); expect(mapped.status).toBeUndefined();
    expect(mapped.assessment).toBeUndefined();
  });
  it('preserves context identity without inventing lifecycle, original time or immutable original terms', () => {
    const d = mapLegacyContext(context(), 'order-1', 'tenant-1');
    expect(d.contextId).toBe('context-1'); expect(d.contextStatus).toBe('INFORMATION_READY');
    expect(d.status).toBeUndefined(); expect(d.version).toBeUndefined(); expect(d.receivedAt).toBeUndefined();
    expect(d.completedAt).toBeUndefined(); expect(d.originalDeadline).toBeUndefined();
    expect(d.currentDeadline).toBe('2026-10-24T02:00:00Z'); expect(d.commitmentId).toBe('commitment-1');
    expect(d.fields?.find(f => f.name === 'location')?.status).toBe('MISSING');
    expect(d.fields?.find(f => f.name === 'requested_items')?.status).toBe('UNVERIFIED');
    expect(d.assessment).toBeUndefined(); expect(d.pricing).toBeUndefined();
  });
  it.each(['tenant', 'order', 'schema'])('rejects wrong %s rather than guessing ID mappings', kind => {
    const raw = context(); if (kind === 'tenant') raw.tenant_id = 'other';
    if (kind === 'order') raw.order_id = 'other'; if (kind === 'schema') raw.context_version = NaN;
    expect(() => mapLegacyContext(raw, 'order-1', 'tenant-1')).toThrow();
  });
  it('preserves source-message claims and rejects cross-tenant messages', () => {
    expect(mapLegacyMessage(message(), 'message-1', 'tenant-1')).toMatchObject({ tier: 'DEMO-ONLY / SYNTHETIC', text: '20 pieces please' });
    expect(() => mapLegacyMessage(message(), 'message-1', 'other')).toThrow();
  });
  it('uses shared HTTP with tenant/actor headers, encoded order IDs and cancellation', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(context())).mockResolvedValueOnce(response(message()));
    vi.stubGlobal('fetch', fetch); const controller = new AbortController();
    const d = await legacyContextDetailSource.load('order-1', auth, controller.signal);
    expect(d?.messages?.[0].id).toBe('message-1');
    expect(fetch).toHaveBeenNthCalledWith(1, expect.stringContaining('/v1/contexts/by-order/order-1'), expect.objectContaining({
      headers: expect.objectContaining({ 'X-Tenant-ID': 'tenant-1', 'X-Actor-ID': 'user_staff_01' }), signal: controller.signal,
    }));
    expect(fetch.mock.calls.every(([url]) => !url.includes('/v1/orders') && !url.includes('/backend-v2'))).toBe(true);
  });
  it('uses a safe per-message unavailable state for missing references', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(context())).mockResolvedValueOnce(response({}, 404)));
    const d = await legacyContextDetailSource.load('order-1', auth, new AbortController().signal);
    expect(d?.messages?.[0]).toMatchObject({ id: 'message-1', text: 'Source message unavailable', tier: 'Not verified' });
  });
  it('propagates message permission failure instead of exposing data or showing a successful source', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(context())).mockResolvedValueOnce(response({}, 403)));
    await expect(legacyContextDetailSource.load('order-1', auth, new AbortController().signal)).rejects.toMatchObject({ status: 403 });
  });
  it('propagates API unavailability without synthetic fallback', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({}, 503)));
    await expect(legacyContextDetailSource.load('order-1', auth, new AbortController().signal)).rejects.toMatchObject({ status: 503 });
  });
  it('rejects malformed records and items', () => {
    expect(() => mapLegacyContext(null, 'order-1', 'tenant-1')).toThrow();
    expect(() => mapLegacyContext({ ...context(), requested_items: [{}] }, 'order-1', 'tenant-1')).toThrow();
  });
});
