import { afterEach, describe, expect, it, vi } from 'vitest';
import { createScopedOperationalApi, operationalApi } from './operationalApi';

describe('review API errors', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('shows the backend catalog reason from the deployed error envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        code: 'UNPROCESSABLE_ENTITY',
        message: 'Product mapping required',
        details: { reasons: ["Item #1: SKU/unit is not in this tenant's approved catalog; map the product or leave unresolved"] },
      }),
    }));

    await expect(operationalApi.reviewContext('ctx', {
      expected_context_version: 2,
      action: 'EDIT_FIELD',
      field_edits: { requested_items: [{ sku: 'BURGER', quantity: '20', unit: 'box' }] },
      note: 'Review',
    })).rejects.toThrow(/Product mapping required: Item #1: SKU\/unit is not in this tenant's approved catalog/);
  });
});


describe('tenant-scoped P1 transport', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends shared identity on config, listing, detail and catalog reads', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', fetchMock);
    const api = createScopedOperationalApi({ tenantId: 'tenant_a', actorId: 'actor_a' });
    // Each response is consumed only once.
    fetchMock.mockImplementation(async () => new Response('{}'));
    await api.config();
    await api.list({ channel: 'ALL', search: '', processing: 'ALL', offset: 0 });
    await api.detail('message/a');
    await api.getCatalog();
    for (const [, init] of fetchMock.mock.calls) {
      const headers = new Headers(init.headers);
      expect(headers.get('X-Tenant-ID')).toBe('tenant_a');
      expect(headers.get('X-Actor-ID')).toBe('actor_a');
      expect(headers.has('X-Actor-Role')).toBe(false);
    }
  });

  it('bound identity wins over optional headers and preserves JSON mutation headers', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}'));
    vi.stubGlobal('fetch', fetchMock);
    const api = createScopedOperationalApi({ tenantId: 'tenant_a', actorId: 'actor_a' });
    await api.reviewContext('ctx', { expected_context_version: 1, action: 'EDIT_FIELD', field_edits: {}, note: 'Test' },
      { 'x-tenant-id': 'other', 'X-Actor-ID': 'other' });
    const headers = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(headers.get('X-Tenant-ID')).toBe('tenant_a');
    expect(headers.get('X-Actor-ID')).toBe('actor_a');
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  it('does not share processing locks across identities', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}'));
    vi.stubGlobal('fetch', fetchMock);
    const a = createScopedOperationalApi({ tenantId: 'tenant_a', actorId: 'actor_a' });
    const b = createScopedOperationalApi({ tenantId: 'tenant_b', actorId: 'actor_b' });
    await Promise.all([a.process('same-id'), a.process('same-id'), b.process('same-id')]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([, init]) => new Headers(init.headers).get('X-Tenant-ID'))).toEqual(['tenant_a', 'tenant_b']);
  });
});


it('keeps explicit Review Drawer processing headers isolated on the legacy client', async () => {
  const fetchMock = vi.fn().mockImplementation(async () => new Response('{}'));
  vi.stubGlobal('fetch', fetchMock);
  try {
    await Promise.all([
      operationalApi.process('same-review-id', true, { 'X-Tenant-ID': 'a', 'X-Actor-ID': 'actor' }),
      operationalApi.process('same-review-id', true, { 'X-Tenant-ID': 'b', 'X-Actor-ID': 'actor' }),
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([, init]) => new Headers(init.headers).get('X-Tenant-ID'))).toEqual(['a', 'b']);
  } finally { vi.unstubAllGlobals(); }
});
