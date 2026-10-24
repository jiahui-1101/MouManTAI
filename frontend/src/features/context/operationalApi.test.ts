import { afterEach, describe, expect, it, vi } from 'vitest';
import { operationalApi } from './operationalApi';

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
