import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ReviewDrawer } from './ReviewDrawer';
import * as api from './operationalApi';
import type { OrderContextRecord } from './types';

const context: OrderContextRecord = {
  context_id: 'judge', tenant_id: 'judge-a', context_version: 1, status: 'UNRESOLVED',
  customer_identity_status: 'UNVERIFIED', requested_items: [], source_message_ids: ['m1'],
  requested_delivery_at: null, missing_fields: ['sku'], conflicts: [],
  created_at: '2026-10-23T10:00:00+08:00', updated_at: '2026-10-23T10:00:00+08:00',
  field_evidence: {
    sku: [{ quote: 'cookies', normalized_value: 'cookies', method: 'MODEL', evidence_id: 'p1', message_id: 'm1', start: 12, end: 19, normalization_metadata: { domain_supported: 'false', group_id: 'g2' } }],
    quantity: [{ quote: '25', normalized_value: '25', method: 'MODEL', start: 0, end: 2 }],
    unit: [{ quote: 'boxes', normalized_value: 'box', method: 'MODEL', start: 3, end: 8 }],
  },
};
const props = { isOpen: true, onClose: vi.fn(), onUpdated: vi.fn() };

describe('Review & Amend candidate safety', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'getReviewCatalog').mockResolvedValue([{ sku: 'BURGER', unit: 'pcs' }]);
  });

  it('preserves unknown product and source evidence without approving the mapping', async () => {
    render(<ReviewDrawer {...props} context={context} />);
    expect(screen.getByLabelText('SKU / Product')).toHaveValue('');
    const candidate = screen.getByRole('button', { name: /Unverified product: cookies/ });
    expect(candidate).toBeDisabled();
    expect(screen.getByText(/Source: m1 \[12:19\]/)).toBeInTheDocument();
    await screen.findByText(/Approved SKU\/unit pairs: BURGER \/ pcs/);
  });

  it('blocks an unknown product and does not silently accept unverified identity', async () => {
    const review = vi.spyOn(api.operationalApi, 'reviewContext');
    render(<ReviewDrawer {...props} context={context} />);
    fireEvent.change(screen.getByLabelText('SKU / Product'), { target: { value: 'cookies' } });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '25' } });
    fireEvent.change(screen.getByLabelText('Unit'), { target: { value: 'box' } });
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Review candidate' } });
    expect(screen.getByRole('button', { name: 'Save & Accept' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/approved SKU/i);
    expect(review).not.toHaveBeenCalled();
  });

  it('requires a chosen item before applying a multi item candidate', () => {
    const multi = { ...context, requested_items: [{ sku: 'BURGER', quantity: '12', unit: 'pcs' }, { sku: 'BURGER', quantity: '8', unit: 'pcs' }] };
    render(<ReviewDrawer {...props} context={multi} />);
    const proposal = screen.getByRole('button', { name: /Apply Quantity: 25/ });
    expect(proposal).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Apply candidates to item'), { target: { value: '1' } });
    fireEvent.click(proposal);
    expect(screen.getAllByLabelText('Quantity')[0]).toHaveValue('12');
    expect(screen.getAllByLabelText('Quantity')[1]).toHaveValue('25');
  });

  it('does not copy a raw delivery expression into a timestamp', () => {
    render(<ReviewDrawer {...props} context={{ ...context, field_evidence: { requested_delivery_at: [{ quote: 'tomorrow before 4pm', method: 'MODEL' }] } }} />);
    expect(screen.getByRole('button', { name: /Apply Delivery: tomorrow before 4pm/ })).toBeDisabled();
    expect(screen.getByLabelText(/Timing qualifier/i)).toHaveValue('');
  });

  it('keeps conflicts unless explicitly reviewed and unresolved remains available without catalog', async () => {
    vi.mocked(api.getReviewCatalog).mockRejectedValue(new Error('Catalog unavailable'));
    const conflicted = { ...context, conflicts: ['Delivery disputed'], requested_items: [{ sku: 'BURGER', quantity: '12', unit: 'pcs' }] };
    const review = vi.spyOn(api.operationalApi, 'reviewContext').mockResolvedValue(conflicted);
    render(<ReviewDrawer {...props} context={conflicted} />);
    await screen.findByText(/Approved catalog unavailable/);
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Needs manual follow-up' } });
    fireEvent.click(screen.getByRole('button', { name: /More actions/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Mark unresolved/i }));
    await waitFor(() => expect(review).toHaveBeenCalledWith('judge', expect.objectContaining({ action: 'MARK_UNRESOLVED', field_edits: {} }), expect.anything()));
  });
});
