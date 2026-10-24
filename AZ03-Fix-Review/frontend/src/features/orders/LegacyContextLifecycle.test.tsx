import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { operationalApi } from '../context/operationalApi';
import type { OrderContextRecord } from '../context/types';

const context: OrderContextRecord = {
  context_id: 'lifecycle-context', tenant_id: 'tenant_demo_01', order_id: 'lifecycle-order',
  customer_id: 'synthetic-current-customer', customer_identity_status: 'LINK_VERIFIED',
  status: 'INFORMATION_PARTIAL', context_version: 2, requested_items: [],
  requested_delivery_at: null, missing_fields: [], conflicts: [], source_message_ids: [], field_evidence: {},
  created_at: '2026-10-24T00:00:00Z', updated_at: '2026-10-24T00:00:00Z',
};
beforeEach(() => {
  window.history.replaceState({}, '', '/orders/lifecycle-order');
  vi.spyOn(operationalApi, 'listContextVersions').mockResolvedValue([]);
  vi.spyOn(operationalApi, 'listContextReviews').mockResolvedValue([]);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.history.replaceState({}, '', '/'); });
function deferredContext() {
  let resolve!: (value: OrderContextRecord) => void;
  const promise = new Promise<OrderContextRecord>(done => { resolve = done; });
  return { promise, resolve };
}
async function assertCurrentSummary() {
  const summary = await screen.findByRole('region', { name: 'Order summary' });
  expect(within(summary).getByText('synthetic-current-customer')).toBeInTheDocument();
  expect(within(summary).getByText('2')).toBeInTheDocument();
  expect(screen.queryByText('synthetic-obsolete-customer')).not.toBeInTheDocument();
}
it('ignores a former actor context callback after the current actor has loaded', async () => {
  const old = deferredContext();
  vi.spyOn(operationalApi, 'getContextByOrder').mockImplementation((_id, headers) =>
    headers?.['X-Actor-ID'] === 'user_owner_01' ? old.promise : Promise.resolve(context));
  render(<App />);
  fireEvent.change(screen.getByLabelText('Demo role selector'), { target: { value: 'user_staff_01' } });
  await assertCurrentSummary();
  await act(async () => { old.resolve({ ...context, context_version: 1, customer_id: 'synthetic-obsolete-customer' }); await old.promise; });
  await assertCurrentSummary();
});
it('ignores a pre-refresh context callback even when tenant, actor and order are unchanged', async () => {
  const old = deferredContext();
  vi.spyOn(operationalApi, 'getContextByOrder').mockImplementationOnce(() => old.promise).mockResolvedValue(context);
  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Refresh order assessment view' }));
  await assertCurrentSummary();
  await act(async () => { old.resolve({ ...context, context_version: 1, customer_id: 'synthetic-obsolete-customer' }); await old.promise; });
  await assertCurrentSummary();
});
