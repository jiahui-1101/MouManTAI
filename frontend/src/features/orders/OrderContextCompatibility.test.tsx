import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { OrderContextDetail } from '../context/OrderContextDetail';
import { operationalApi } from '../context/operationalApi';
import * as p1Api from '../context/operationalApi';
import type { OrderContextRecord } from '../context/types';

const headers = { 'X-Tenant-ID': 'tenant-scoped', 'X-Actor-ID': 'user_manager_01' };
const context: OrderContextRecord = { context_id: 'context-scoped', tenant_id: 'tenant-scoped', order_id: 'order-scoped',
  customer_identity_status: 'LINK_VERIFIED', status: 'INFORMATION_PARTIAL', context_version: 3,
  requested_items: [{ sku: 'BREAD', quantity: '20', unit: 'pieces' }], requested_delivery_at: '2026-10-25T00:00:00Z',
  missing_fields: [], conflicts: [], source_message_ids: [], field_evidence: {}, created_at: '2026-10-24T00:00:00Z', updated_at: '2026-10-24T00:00:00Z' };
beforeEach(() => {
  vi.spyOn(operationalApi, 'getContextByOrder').mockResolvedValue(context);
  vi.spyOn(operationalApi, 'listContextVersions').mockResolvedValue([]);
  vi.spyOn(operationalApi, 'listContextReviews').mockResolvedValue([]);
  vi.spyOn(p1Api, 'getReviewCatalog').mockResolvedValue([{ sku: 'BREAD', unit: 'pieces' }]);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe('P1 compatibility with explicitly scoped composite route', () => {
  it('passes current tenant and actor to all legacy context/history reads', async () => {
    render(<OrderContextDetail orderId="order-scoped" requestHeaders={headers} />);
    await screen.findByText('Order Context: order-scoped');
    expect(operationalApi.getContextByOrder).toHaveBeenCalledWith('order-scoped', headers);
    expect(operationalApi.listContextVersions).toHaveBeenCalledWith('context-scoped', headers);
    expect(operationalApi.listContextReviews).toHaveBeenCalledWith('context-scoped', headers);
    fireEvent.click(screen.getByRole('button', { name: 'Version History' }));
    expect(screen.getByLabelText('Version History')).toBeInTheDocument();
  });
  it('retains publishing and sends identity through the existing guarded API', async () => {
    const publish = vi.spyOn(operationalApi, 'publishContext').mockResolvedValue({ ...context, core_commitment_id: 'commitment-scoped' });
    render(<OrderContextDetail orderId="order-scoped" requestHeaders={headers} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Publish to Core' }));
    expect(await screen.findByText(/Successfully published to Core commitment commitment-scoped/)).toBeInTheDocument();
    expect(publish).toHaveBeenCalledWith('context-scoped', headers);
  });
  it('retains review and server-version guard with explicit current identity', async () => {
    const review = vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({ ...context, context_version: 4, status: 'UNRESOLVED' });
    render(<OrderContextDetail orderId="order-scoped" requestHeaders={headers} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Review & Amend' }));
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Synthetic verification pending' } });
    fireEvent.click(screen.getByRole('button', { name: /More actions/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Mark unresolved/i }));
    await waitFor(() => expect(review).toHaveBeenCalledWith('context-scoped', expect.objectContaining({
      action: 'MARK_UNRESOLVED', expected_context_version: 3,
    }), expect.objectContaining(headers)));
    expect(p1Api.getReviewCatalog).toHaveBeenCalledWith(headers);
  });
  it('fails closed when legacy context returns another tenant', async () => {
    vi.mocked(operationalApi.getContextByOrder).mockResolvedValue({ ...context, tenant_id: 'other-tenant' });
    render(<OrderContextDetail orderId="order-scoped" requestHeaders={headers} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('tenant does not match');
    expect(screen.queryByText('Order Context: order-scoped')).not.toBeInTheDocument();
  });
});
