import { afterEach, describe, expect, it, vi } from 'vitest';
import { coreOrderDecisionSource, mapCoreDecision, mapCoreTimeline } from './decisionApi';
import coreFixture from './__fixtures__/core-decision.synthetic.json';
import type { OrderDetail } from './detailTypes';

const order = (): OrderDetail => ({ id: 'synthetic-order', tenantId: 'synthetic-decision-tenant', customer: 'synthetic-customer', commitmentId: 'synthetic-commitment' });
const auth = { tenantId: 'synthetic-decision-tenant', actorId: 'user_manager_01' };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
afterEach(() => vi.unstubAllGlobals());
describe('Verified Core decision read adapter', () => {
  it('maps actual FastAPI-serialized legacy confirmation without inventing request identity, price, assent or reservation', () => {
    const mapped = mapCoreDecision(coreFixture.commitment, order(), auth.tenantId);
    expect(mapped.currentAgreement?.version).toBe('3'); expect(mapped.currentAgreement?.terms.basis).toBe('LEGACY_CORE_TERMS');
    expect(mapped.currentAgreement?.terms.lines[0]).toMatchObject({ sku: 'BREAD', quantity: '20', unit: 'pieces' });
    expect(mapped.requestVersion).toBeUndefined(); expect(mapped.exactOriginal).toBeUndefined(); expect(mapped.receipts).toBeUndefined();
    expect(mapped.currentAgreement?.terms.hash).toBeUndefined(); expect(mapped.financialAccess).toBe('UNKNOWN');
  });
  it('does not label an offered/rejected commitment as confirmed agreement', () => {
    expect(mapCoreDecision({ ...coreFixture.commitment, agreement_state: 'OFFERED' }, order(), auth.tenantId).currentAgreement).toBeNull();
  });
  it.each(['tenant_id', 'order_id', 'commitment_id', 'customer_id'])('rejects mismatched %s before loading audit history', field => {
    expect(() => mapCoreDecision({ ...coreFixture.commitment, [field]: 'other' }, order(), auth.tenantId)).toThrow(/binding/);
  });
  it('maps the persisted timeline ID and does not extract imagined receipt/assent from state blobs', () => {
    const entries = mapCoreTimeline(coreFixture.timeline); expect(entries[0].id).toBe('entry_synthetic-audit');
    expect(entries[0].recordedState).toContain('agreement_state: CONFIRMED');
    expect(entries[0].receiptId).toBeUndefined(); expect(entries[0].reservationRef).toBeUndefined(); expect(entries[0].termsHash).toBeUndefined();
    expect(mapCoreTimeline([{ ...coreFixture.timeline[0], new_state: { private_cost: 'SECRET', terms: { price: 'SECRET' } } }])[0].recordedState).toBeNull();
  });
  it('rejects malformed Core data and duplicate timeline entries', () => {
    expect(() => mapCoreDecision({ ...coreFixture.commitment, terms: null }, order(), auth.tenantId)).toThrow();
    expect(() => mapCoreTimeline({})).toThrow();
    expect(() => mapCoreTimeline([coreFixture.timeline[0], coreFixture.timeline[0]])).toThrow(/Duplicate/);
  });
  it('reads only the explicit tenant-bound commitment and its timeline, using shared HTTP headers/cancellation', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(coreFixture.commitment)).mockResolvedValueOnce(response(coreFixture.timeline));
    vi.stubGlobal('fetch', fetch); const signal = new AbortController().signal;
    const data = await coreOrderDecisionSource.load(order(), auth, signal);
    expect(data.events).toHaveLength(1); expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch).toHaveBeenNthCalledWith(1, expect.stringContaining('/v1/commitments/synthetic-commitment'), expect.objectContaining({ signal,
      headers: expect.objectContaining({ 'X-Tenant-ID': auth.tenantId, 'X-Actor-ID': auth.actorId }) }));
    expect(fetch.mock.calls[1][0]).toContain('/synthetic-commitment/timeline');
    expect(fetch.mock.calls.every(([path, init]) => (!init.method || init.method === 'GET') && !path.includes('/backend-v2') && !path.includes('/v1/orders'))).toBe(true);
  });
  it('makes no speculative request if P1 has no explicit commitment link', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); const d = order(); d.commitmentId = null;
    const data = await coreOrderDecisionSource.load(d, auth, new AbortController().signal);
    expect(data.events).toEqual([]); expect(fetch).not.toHaveBeenCalled();
  });
  it('blocks an input from another tenant before transport', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    await expect(coreOrderDecisionSource.load({ ...order(), tenantId: 'other' }, auth, new AbortController().signal)).rejects.toThrow(/tenant/);
    expect(fetch).not.toHaveBeenCalled();
  });
  it.each([401, 403, 404, 409, 422, 503])('propagates HTTP %i without empty-history or synthetic success fallback', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({}, status)));
    await expect(coreOrderDecisionSource.load(order(), auth, new AbortController().signal)).rejects.toMatchObject({ status });
  });
  it('does not hide a failed timeline read behind valid-looking current agreement data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(coreFixture.commitment)).mockResolvedValueOnce(response({}, 503)));
    await expect(coreOrderDecisionSource.load(order(), auth, new AbortController().signal)).rejects.toMatchObject({ status: 503 });
  });
});

it('projects actual Core fulfilment separately without inventing order acceptance or delivery verification', () => {
  const mapped = mapCoreDecision({ ...coreFixture.commitment, fulfilment_state: 'FULFILLED' }, order(), auth.tenantId);
  expect(mapped.legacyFulfilment).toMatchObject({ state: 'FULFILLED', commitmentId: 'synthetic-commitment', commitmentVersion: '3', evidence: ['synthetic-core-evidence'] });
  expect(mapped.requestVersion).toBeUndefined(); expect(mapped.receipts).toBeUndefined();
});

it.each(['INVENTED', null])('rejects malformed Core fulfilment state %s', fulfilment => {
  expect(() => mapCoreDecision({ ...coreFixture.commitment, fulfilment_state: fulfilment }, order(), auth.tenantId)).toThrow();
});
