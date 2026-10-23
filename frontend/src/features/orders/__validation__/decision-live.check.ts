import { describe, expect, it } from 'vitest';
import { coreOrderDecisionSource } from '../decisionApi';

// Requires the task-local, read-only core_read_contract.py --serve fixture bridge.
// This explicit check is not included in the normal suite and is not a production source.
describe('Frontend adapter → real HTTP → FastAPI → synthetic in-memory SQLite', () => {
  const order = { id: 'synthetic-order', tenantId: 'synthetic-decision-tenant', customer: 'synthetic-customer', commitmentId: 'synthetic-commitment' };
  it('reads and maps actual persisted Core/timeline responses', async () => {
    const snapshot = await coreOrderDecisionSource.load(order, { tenantId: order.tenantId, actorId: 'user_manager_01' }, new AbortController().signal);
    expect(snapshot.currentAgreement?.version).toBe('3');
    expect(snapshot.events[0].id).toBe('entry_synthetic-audit');
    expect(snapshot.receipts).toBeUndefined(); expect(snapshot.exactOriginal).toBeUndefined(); expect(snapshot.requestVersion).toBeUndefined();
  });
  it('rejects wrong-tenant reads over HTTP', async () => {
    await expect(coreOrderDecisionSource.load({ ...order, tenantId: 'wrong-tenant' }, { tenantId: 'wrong-tenant', actorId: 'user_staff_01' }, new AbortController().signal)).rejects.toMatchObject({ status: 404 });
  });
});
