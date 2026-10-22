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
    sku: [{ quote: 'cookies', normalized_value: 'cookies', method: 'MODEL',
      evidence_id: 'p1', message_id: 'm1', start: 12, end: 19,
      normalization_metadata: { domain_supported: 'false', group_id: 'g2' } }],
    quantity: [{ quote: '25', normalized_value: '25', method: 'MODEL', start: 0, end: 2 }],
    unit: [{ quote: 'boxes', normalized_value: 'box', method: 'MODEL', start: 3, end: 8 }],
  },
};
const props = { isOpen: true, onClose: vi.fn(), onUpdated: vi.fn() };

describe('Review Drawer candidate safety', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'getReviewCatalog').mockResolvedValue([{ sku: 'BURGER', unit: 'pcs' }]);
  });

  it('preserves unknown product, quantity, unit and source without pretending it is an approved SKU', async () => {
    render(<ReviewDrawer {...props} context={context} />);
    expect(screen.getByLabelText('SKU / Product')).toHaveValue('');
    expect(screen.getByRole('button', { name: /Unverified product: cookies/ })).toBeDisabled();
    expect(screen.getByText(/Source: m1 \[12:19\]/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Apply Quantity: 25/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Apply Unit: box/ })).toBeInTheDocument();
    await screen.findByText(/Approved SKU\/unit pairs: BURGER \/ pcs/);
  });

  it('blocks an unknown product or incompatible unit from being submitted as a mapping', async () => {
    const review = vi.spyOn(api.operationalApi, 'reviewContext');
    render(<ReviewDrawer {...props} context={context} />);
    fireEvent.change(screen.getByLabelText('SKU / Product'), { target: { value: 'cookies' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Field Edits' }));
    await screen.findByText(/Map to an approved SKU/);
    expect(review).not.toHaveBeenCalled();
  });

  it('requires staff to choose an item instead of overwriting the first item with a candidate', () => {
    const mixed = { ...context, requested_items: [
      { sku: 'BURGER', quantity: '12', unit: 'pcs' }, { sku: 'BURGER', quantity: '8', unit: 'pcs' },
    ] };
    render(<ReviewDrawer {...props} context={mixed} />);
    const proposal = screen.getByRole('button', { name: /Apply Quantity: 25/ });
    expect(proposal).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Apply candidates to item'), { target: { value: '1' } });
    fireEvent.click(proposal);
    const quantities = screen.getAllByLabelText('Quantity');
    expect(quantities[0]).toHaveValue('12');
    expect(quantities[1]).toHaveValue('25');
  });

  it('keeps identical observations from distinct item groups visible', () => {
    const mixed = { ...context, field_evidence: { sku: [
      ...context.field_evidence!.sku!,
      { quote: 'cookies', normalized_value: 'cookies', method: 'MODEL',
        normalization_metadata: { group_id: 'g3', domain_supported: 'false' } },
    ] } };
    render(<ReviewDrawer {...props} context={mixed} />);
    expect(screen.getAllByRole('button', { name: /Unverified product: cookies/ })).toHaveLength(2);
  });

  it('does not copy a raw delivery expression into a timestamp or invent its qualifier', () => {
    render(<ReviewDrawer {...props} context={{ ...context, field_evidence: {
      requested_delivery_at: [{ quote: 'tomorrow before 4pm', method: 'MODEL' }],
    } }} />);
    expect(screen.getByRole('button', { name: /Apply Delivery: tomorrow before 4pm/ })).toBeDisabled();
    expect(screen.getByLabelText(/Qualifier/i)).toHaveValue('');
  });

  it('does not default a newly added item to pieces', () => {
    render(<ReviewDrawer {...props} context={context} />);
    fireEvent.click(screen.getByRole('button', { name: '+ Add Item' }));
    expect(screen.getAllByLabelText('Unit')[1]).toHaveValue('');
  });

  it('resets form state when closed and reopened, without changing hook order', () => {
    const view = render(<ReviewDrawer {...props} context={context} />);
    fireEvent.change(screen.getByLabelText('SKU / Product'), { target: { value: 'unsaved' } });
    view.rerender(<ReviewDrawer {...props} context={context} isOpen={false} />);
    view.rerender(<ReviewDrawer {...props} context={context} />);
    expect(screen.getByLabelText('SKU / Product')).toHaveValue('');
  });

  it('does not silently accept extraction while field edits are unsaved', () => {
    render(<ReviewDrawer {...props} context={context} />);
    fireEvent.change(screen.getByLabelText('SKU / Product'), { target: { value: 'BURGER' } });
    expect(screen.getByRole('button', { name: 'Accept Extraction' })).toBeDisabled();
    expect(screen.getByText(/Use Apply Field Edits to save/)).toBeInTheDocument();
  });

  it('keeps existing conflicts unless staff explicitly resolves them', async () => {
    const conflicted = { ...context, conflicts: ['Delivery still disputed'], requested_items: [
      { sku: 'BURGER', quantity: '12', unit: 'pcs' },
    ] };
    const review = vi.spyOn(api.operationalApi, 'reviewContext').mockResolvedValue(conflicted);
    render(<ReviewDrawer {...props} context={conflicted} />);
    fireEvent.click(screen.getByRole('button', { name: 'Apply Field Edits' }));
    await waitFor(() => expect(review).toHaveBeenCalled());
    expect(review.mock.calls[0][1].field_edits).not.toHaveProperty('conflicts');
  });

  it('leaves unresolved action available when the catalog cannot be loaded', async () => {
    vi.mocked(api.getReviewCatalog).mockRejectedValue(new Error('Catalog unavailable'));
    const review = vi.spyOn(api.operationalApi, 'reviewContext').mockResolvedValue(context);
    render(<ReviewDrawer {...props} context={context} />);
    await screen.findByText(/Approved catalog unavailable/);
    fireEvent.click(screen.getByRole('button', { name: 'Mark Unresolved' }));
    await waitFor(() => expect(review).toHaveBeenCalledWith('judge', expect.objectContaining({
      action: 'MARK_UNRESOLVED', field_edits: {},
    }), expect.anything()));
  });
});
