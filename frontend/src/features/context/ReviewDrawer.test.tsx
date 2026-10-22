import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ReviewDrawer } from './ReviewDrawer';
import { operationalApi } from './operationalApi';
import * as reviewApi from './operationalApi';
import type { OrderContextRecord } from './types';

const baseContext: OrderContextRecord = {
  context_id: 'ctx_drawer_test',
  tenant_id: 'tenant_test',
  order_id: 'ORD-9001',
  customer_id: 'cust_drawer_1',
  customer_identity_status: 'LINK_VERIFIED',
  status: 'INFORMATION_PARTIAL',
  requested_items: [
    { sku: 'SOURDOUGH', quantity: '50', unit: 'pcs' },
  ],
  requested_delivery_at: '2026-10-25T15:00:00+08:00',
  delivery_qualifier: 'DEADLINE',
  special_instructions: 'Handle with care',
  missing_fields: [],
  conflicts: [],
  source_message_ids: ['msg_1'],
  field_evidence: {
    sku: [{ quote: 'sourdough', normalized_value: 'SOURDOUGH', method: 'MODEL', normalization_metadata: { domain_supported: 'true' } }],
    quantity: [{ quote: '50', normalized_value: '50', method: 'MODEL' }],
    unit: [{ quote: 'pcs', normalized_value: 'pcs', method: 'MODEL' }],
    requested_delivery_at: [{ quote: 'tomorrow 3pm', normalized_value: '2026-10-25T15:00:00+08:00', method: 'MODEL', qualifier: 'DEADLINE' }],
  },
  context_version: 1,
  created_at: '2026-10-24T10:00:00Z',
  updated_at: '2026-10-24T10:00:00Z',
};

describe('ReviewDrawer component', () => {
  const onClose = vi.fn();
  const onUpdated = vi.fn();

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(reviewApi, 'getReviewCatalog').mockResolvedValue([
      { sku: 'SOURDOUGH', unit: 'pcs' }, { sku: 'CROISSANT', unit: 'box' }, { sku: 'BAGEL', unit: 'pcs' },
    ]);
    onClose.mockReset();
    onUpdated.mockReset();
  });

  it('renders nothing when isOpen is false', () => {
    const { container } = render(
      <ReviewDrawer context={baseContext} isOpen={false} onClose={onClose} onUpdated={onUpdated} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders initial form values and candidate proposal chips', () => {
    render(
      <ReviewDrawer context={baseContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    expect(screen.getByTestId('review-drawer')).toBeInTheDocument();
    expect(screen.getByText('Context Review & Amendments')).toBeInTheDocument();
    expect(screen.getByDisplayValue('SOURDOUGH')).toBeInTheDocument();
    expect(screen.getByDisplayValue('50')).toBeInTheDocument();
    expect(screen.getByDisplayValue('pcs')).toBeInTheDocument();
    expect(screen.getByDisplayValue('2026-10-25T15:00:00+08:00')).toBeInTheDocument();
    expect(screen.getByDisplayValue('DEADLINE')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Handle with care')).toBeInTheDocument();

    // Check candidate proposal chips
    expect(screen.getByRole('button', { name: /Apply SKU: SOURDOUGH/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Apply Quantity: 50/i })).toBeInTheDocument();
  });

  it('handles EDIT_FIELD submission for single item', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({
      ...baseContext,
      context_version: 2,
      requested_items: [{ sku: 'CROISSANT', quantity: '25', unit: 'box' }],
    });

    render(
      <ReviewDrawer context={baseContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    fireEvent.change(screen.getByLabelText(/SKU \/ Product/i), { target: { value: 'CROISSANT' } });
    fireEvent.change(screen.getByLabelText(/^Quantity$/i), { target: { value: '25' } });
    fireEvent.change(screen.getByLabelText(/^Unit$/i), { target: { value: 'box' } });
    fireEvent.change(screen.getByLabelText(/Reviewer Note/i), { target: { value: 'Customer swapped item' } });

    fireEvent.click(screen.getByRole('button', { name: /Apply Field Edits/i }));

    await waitFor(() => {
      expect(operationalApi.reviewContext).toHaveBeenCalledWith(
        'ctx_drawer_test',
        {
          expected_context_version: 1,
          action: 'EDIT_FIELD',
          field_edits: {
            requested_items: [{ sku: 'CROISSANT', quantity: '25', unit: 'box' }],
            delivery_qualifier: 'DEADLINE',
            requested_delivery_at: new Date('2026-10-25T15:00:00+08:00').toISOString(),
            special_instructions: 'Handle with care',
            conflicts: [],
          },
          note: 'Customer swapped item',
        },
        {
          'X-Actor-ID': 'user_staff_01',
          'X-Actor-Role': 'STAFF',
        }
      );
      expect(onUpdated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('handles multi-item editing: adding, editing, and submitting multiple items', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({
      ...baseContext,
      context_version: 2,
      requested_items: [
        { sku: 'SOURDOUGH', quantity: '50', unit: 'pcs' },
        { sku: 'BAGEL', quantity: '30', unit: 'pcs' },
      ],
    });

    render(
      <ReviewDrawer context={baseContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    // Click Add Item
    fireEvent.click(screen.getByRole('button', { name: /\+ Add Item/i }));

    // Item #2 fields should appear
    expect(screen.getByText('Item #2')).toBeInTheDocument();

    const skuInputs = screen.getAllByLabelText(/SKU \/ Product/i);
    expect(skuInputs).toHaveLength(2);
    fireEvent.change(skuInputs[1], { target: { value: 'BAGEL' } });

    const qtyInputs = screen.getAllByLabelText(/^Quantity/i);
    expect(qtyInputs).toHaveLength(2);
    fireEvent.change(qtyInputs[1], { target: { value: '30' } });

    const unitInputs = screen.getAllByLabelText(/^Unit/i);
    expect(unitInputs).toHaveLength(2);
    fireEvent.change(unitInputs[1], { target: { value: 'pcs' } });

    fireEvent.click(screen.getByRole('button', { name: /Apply Field Edits/i }));

    await waitFor(() => {
      expect(operationalApi.reviewContext).toHaveBeenCalledWith(
        'ctx_drawer_test',
        expect.objectContaining({
          expected_context_version: 1,
          action: 'EDIT_FIELD',
          field_edits: expect.objectContaining({
            requested_items: [
              { sku: 'SOURDOUGH', quantity: '50', unit: 'pcs' },
              { sku: 'BAGEL', quantity: '30', unit: 'pcs' },
            ],
          }),
        }),
        expect.anything()
      );
      expect(onUpdated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('handles item removal when multiple items exist', async () => {
    const multiItemContext: OrderContextRecord = {
      ...baseContext,
      requested_items: [
        { sku: 'SOURDOUGH', quantity: '50', unit: 'pcs' },
        { sku: 'BAGEL', quantity: '30', unit: 'pcs' },
      ],
    };

    render(
      <ReviewDrawer context={multiItemContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    expect(screen.getByText('Order Items (2)')).toBeInTheDocument();
    const removeButtons = screen.getAllByRole('button', { name: /Remove/i });
    expect(removeButtons).toHaveLength(2);

    // Remove the second item
    fireEvent.click(removeButtons[1]);

    // Now only 1 item remains, remove buttons disappear
    expect(screen.queryByText('Item #2')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Remove/i })).not.toBeInTheDocument();
  });

  it('handles ACCEPT_EXTRACTION submission', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({
      ...baseContext,
      context_version: 2,
      status: 'INFORMATION_READY',
    });

    render(
      <ReviewDrawer context={baseContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    fireEvent.change(screen.getByLabelText(/Reviewer Note/i), { target: { value: 'All fields verified with buyer' } });
    fireEvent.click(screen.getByRole('button', { name: /Accept Extraction/i }));

    await waitFor(() => {
      expect(operationalApi.reviewContext).toHaveBeenCalledWith(
        'ctx_drawer_test',
        {
          expected_context_version: 1,
          action: 'ACCEPT_EXTRACTION',
          field_edits: {},
          note: 'All fields verified with buyer',
        },
        expect.anything()
      );
      expect(onUpdated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('handles REQUEST_MORE_INFO submission', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({
      ...baseContext,
      context_version: 2,
      status: 'INFORMATION_PARTIAL',
    });

    render(
      <ReviewDrawer context={baseContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    fireEvent.change(screen.getByLabelText(/Reviewer Note/i), { target: { value: 'Need delivery gate code' } });
    fireEvent.click(screen.getByRole('button', { name: /Request More Info/i }));

    await waitFor(() => {
      expect(operationalApi.reviewContext).toHaveBeenCalledWith(
        'ctx_drawer_test',
        {
          expected_context_version: 1,
          action: 'REQUEST_MORE_INFO',
          field_edits: {},
          note: 'Need delivery gate code',
        },
        expect.anything()
      );
      expect(onUpdated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('handles MARK_UNRESOLVED submission', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({
      ...baseContext,
      context_version: 2,
      status: 'UNRESOLVED',
    });

    render(
      <ReviewDrawer context={baseContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    fireEvent.change(screen.getByLabelText(/Reviewer Note/i), { target: { value: 'Inquiry only, not an order' } });
    fireEvent.click(screen.getByRole('button', { name: /Mark Unresolved/i }));

    await waitFor(() => {
      expect(operationalApi.reviewContext).toHaveBeenCalledWith(
        'ctx_drawer_test',
        {
          expected_context_version: 1,
          action: 'MARK_UNRESOLVED',
          field_edits: {},
          note: 'Inquiry only, not an order',
        },
        expect.anything()
      );
      expect(onUpdated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('validates invalid quantities and blocks submission', async () => {
    render(
      <ReviewDrawer context={baseContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    fireEvent.change(screen.getByLabelText(/^Quantity$/i), { target: { value: '-10' } });
    fireEvent.click(screen.getByRole('button', { name: /Apply Field Edits/i }));

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/positive quantity/i)).toBeInTheDocument();
  });

  it('validates invalid delivery ISO timestamps and blocks submission', async () => {
    render(
      <ReviewDrawer context={baseContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    fireEvent.change(screen.getByLabelText(/Date & Time/i), { target: { value: 'tomorrow at 3' } });
    fireEvent.click(screen.getByRole('button', { name: /Apply Field Edits/i }));

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/explicit UTC offset/i)).toBeInTheDocument();
  });

  it('displays API error banner when reviewContext rejects (e.g. stale version 409)', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockRejectedValue(
      new Error('Context version mismatch: expected 1, got 2')
    );

    render(
      <ReviewDrawer context={baseContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    fireEvent.click(screen.getByRole('button', { name: /Accept Extraction/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText(/Context version mismatch: expected 1, got 2/i)).toBeInTheDocument();
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape key press and Close button click', () => {
    render(
      <ReviewDrawer context={baseContext} isOpen={true} onClose={onClose} onUpdated={onUpdated} />
    );

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByLabelText(/Close drawer/i));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
