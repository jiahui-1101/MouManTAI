import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ReviewDrawer, getSuggestedClarification } from './ReviewDrawer';
import { operationalApi } from './operationalApi';
import * as reviewApi from './operationalApi';
import type { OrderContextRecord, StoredMessage } from './types';

const context: OrderContextRecord = {
  context_id: 'ctx_drawer_test', tenant_id: 'tenant_test', order_id: 'ORD-9001', customer_id: 'cust_1',
  customer_identity_status: 'LINK_VERIFIED', status: 'INFORMATION_PARTIAL', context_version: 1,
  requested_items: [{ sku: 'SOURDOUGH', quantity: '50', unit: 'pcs' }],
  requested_delivery_at: '2026-10-25T15:00:00+08:00', delivery_qualifier: 'DEADLINE', special_instructions: 'Handle with care',
  missing_fields: [], conflicts: [], source_message_ids: ['msg_1'],
  field_evidence: {
    sku: [{ quote: 'SOURDOUGH', start: 8, end: 17, message_id: 'msg_1', method: 'MODEL', normalized_value: 'SOURDOUGH' }],
    quantity: [{ quote: '50', start: 5, end: 7, message_id: 'msg_1', method: 'MODEL', normalized_value: '50' }],
    unit: [{ quote: 'pcs', method: 'MODEL', normalized_value: 'pcs' }],
    requested_delivery_at: [{ quote: 'tomorrow 3pm', method: 'MODEL', normalized_value: '2026-10-25T15:00:00+08:00', qualifier: 'DEADLINE' }],
  },
  created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:00:00Z',
};
const message = { message_id: 'msg_1', processing_status: 'PROCESSED', raw: { text: 'Need 50 SOURDOUGH', channel: 'EMAIL', received_at: '2026-10-24T10:00:00Z' } } as StoredMessage;

describe('Review & Amend workspace', () => {
  const onClose = vi.fn();
  const onUpdated = vi.fn();
  const props = { context, message, sourceMessage: message.raw.text, isOpen: true, onClose, onUpdated };
  beforeEach(() => {
    vi.restoreAllMocks(); onClose.mockReset(); onUpdated.mockReset();
    vi.spyOn(reviewApi, 'getReviewCatalog').mockResolvedValue([{ sku: 'SOURDOUGH', unit: 'pcs' }, { sku: 'CROISSANT', unit: 'box' }, { sku: 'BAGEL', unit: 'pcs' }]);
    vi.spyOn(operationalApi, 'getContext').mockResolvedValue({ ...context, context_version: 2 });
  });

  it('shows a single split workspace, source highlights and three footer actions', () => {
    render(<ReviewDrawer {...props} />);
    const dialog = screen.getByTestId('review-drawer');
    expect(within(dialog).getByText('Original message')).toBeInTheDocument();
    expect(within(dialog).getByText('Extracted fields')).toBeInTheDocument();
    expect(within(dialog).queryByRole('tablist')).not.toBeInTheDocument();
    expect(within(dialog).getByText('SOURDOUGH', { selector: 'mark' })).toHaveAttribute('data-evidence-field', 'sku');
    expect(within(dialog).getByText('Technical details and provenance').closest('details')).not.toHaveAttribute('open');
    expect(within(dialog).getByText('AI candidates & evidence (4)').closest('details')).not.toHaveAttribute('open');
    const footer = within(dialog).getByRole('contentinfo');
    expect(within(footer).getAllByRole('button').map(button => button.textContent)).toEqual(['Cancel', 'Save changes', 'Save & Accept']);
  });

  it('requires an audit reason for changes and warns before discarding edits', () => {
    render(<ReviewDrawer {...props} />);
    fireEvent.change(screen.getByLabelText('SKU / Product'), { target: { value: 'CROISSANT' } });
    expect(screen.getByText('Unsaved changes · reviewer note required')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByText('Unsaved review changes will be lost.')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    expect(screen.getByLabelText('SKU / Product')).toHaveValue('CROISSANT');
  });

  it('saves audited field edits with the current actor and version', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({ ...context, context_version: 2 });
    render(<ReviewDrawer {...props} actorId="user_manager_01" actorRole="MANAGER" />);
    await screen.findByText(/Approved SKU\/unit pairs: SOURDOUGH \/ pcs/);
    fireEvent.change(screen.getByLabelText('SKU / Product'), { target: { value: 'CROISSANT' } });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '25' } });
    fireEvent.change(screen.getByLabelText('Unit'), { target: { value: 'box' } });
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Customer corrected item' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /confirm the change to a major field/i }));
    vi.mocked(operationalApi.getContext).mockResolvedValue({ ...context, context_version: 2, requested_items: [{ sku: 'CROISSANT', quantity: '25', unit: 'box' }] });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(operationalApi.reviewContext).toHaveBeenCalledWith('ctx_drawer_test', expect.objectContaining({
      action: 'EDIT_FIELD', expected_context_version: 1, note: 'Customer corrected item',
      field_edits: expect.objectContaining({ requested_items: [{ sku: 'CROISSANT', quantity: '25', unit: 'box' }] }),
    }), { 'X-Actor-ID': 'user_manager_01', 'X-Actor-Role': 'MANAGER' }));
    expect(onUpdated).toHaveBeenCalled(); expect(onClose).toHaveBeenCalled();
  });

  it('saves then accepts through two audited commands with the returned version', async () => {
    const review = vi.spyOn(operationalApi, 'reviewContext')
      .mockResolvedValueOnce({ ...context, context_version: 2, requested_items: [{ sku: 'CROISSANT', quantity: '25', unit: 'box' }] })
      .mockResolvedValueOnce({ ...context, context_version: 3, status: 'INFORMATION_READY' });
    render(<ReviewDrawer {...props} />);
    await screen.findByText(/Approved SKU\/unit pairs: SOURDOUGH \/ pcs/);
    fireEvent.change(screen.getByLabelText('SKU / Product'), { target: { value: 'CROISSANT' } });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '25' } });
    fireEvent.change(screen.getByLabelText('Unit'), { target: { value: 'box' } });
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Verified with buyer' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /confirm the change to a major field/i }));
    vi.mocked(operationalApi.getContext).mockResolvedValueOnce({ ...context, context_version: 2, requested_items: [{ sku: 'CROISSANT', quantity: '25', unit: 'box' }] }).mockResolvedValueOnce({ ...context, context_version: 3, status: 'INFORMATION_READY' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save & Accept' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Save & Accept' }));
    await waitFor(() => expect(review).toHaveBeenCalledTimes(2));
    expect(review.mock.calls[0][1]).toMatchObject({ action: 'EDIT_FIELD', expected_context_version: 1 });
    expect(review.mock.calls[1][1]).toMatchObject({ action: 'ACCEPT_EXTRACTION', expected_context_version: 2 });
    expect(onClose).toHaveBeenCalled();
  });

  it('records more information without claiming a customer message was sent', async () => {
    const review = vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({ ...context, context_version: 2 });
    render(<ReviewDrawer {...props} />);
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Need delivery gate code' } });
    fireEvent.click(screen.getByRole('button', { name: /More actions/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Record need for more info/i }));
    await waitFor(() => expect(review).toHaveBeenCalledWith('ctx_drawer_test', expect.objectContaining({ action: 'REQUEST_MORE_INFO', field_edits: {}, note: 'Need delivery gate code' }), expect.anything()));
    expect(screen.queryByText(/Waiting for customer/i)).not.toBeInTheDocument();
  });

  it('validates catalog mappings and offset aware dates before saving', async () => {
    const review = vi.spyOn(operationalApi, 'reviewContext');
    render(<ReviewDrawer {...props} />);
    fireEvent.change(screen.getByLabelText('SKU / Product'), { target: { value: 'UNKNOWN' } });
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Review' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /confirm the change to a major field/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/approved SKU/i);
    expect(review).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled();
  });

  it('saves an instructions-only correction while SKU and identity remain unresolved', async () => {
    const partial = { ...context, customer_id: null, customer_identity_status: 'UNVERIFIED', requested_items: [], missing_fields: ['sku_mapping', 'customer_identity'] } as OrderContextRecord;
    const saved = { ...partial, context_version: 2, special_instructions: 'Keep refrigerated' };
    const review = vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue(saved);
    vi.mocked(operationalApi.getContext).mockResolvedValue(saved);
    render(<ReviewDrawer {...props} context={partial} />);
    fireEvent.change(screen.getByLabelText('Special instructions'), { target: { value: 'Keep refrigerated' } });
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Customer specified refrigeration' } });
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Save & Accept' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(review).toHaveBeenCalledWith(partial.context_id, expect.objectContaining({ action: 'EDIT_FIELD', field_edits: { special_instructions: 'Keep refrigerated' } }), expect.anything()));
    expect(onUpdated).toHaveBeenCalledWith(saved);
  });

  it.each([400, 403, 409, 422, 503])('keeps a %i backend error visible and preserves the open edit', async status => {
    vi.spyOn(operationalApi, 'reviewContext').mockRejectedValue(new Error(`Backend rejected (${status})`));
    render(<ReviewDrawer {...props} />);
    fireEvent.change(screen.getByLabelText('Special instructions'), { target: { value: 'Keep refrigerated' } });
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Customer instruction' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(`Backend rejected (${status})`);
    expect(onClose).not.toHaveBeenCalled();
    expect(onUpdated).not.toHaveBeenCalled();
  });

  it('does not report success when the write response is ahead of the persisted context', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({ ...context, context_version: 2, special_instructions: 'Keep refrigerated' });
    vi.mocked(operationalApi.getContext).mockResolvedValue(context);
    render(<ReviewDrawer {...props} />);
    fireEvent.change(screen.getByLabelText('Special instructions'), { target: { value: 'Keep refrigerated' } });
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Customer instruction' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/saved values are not visible/i);
    expect(onUpdated).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('keeps backend errors visible without closing or inventing success', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockRejectedValue(new Error('Context version mismatch: expected 1, got 2'));
    render(<ReviewDrawer {...props} />);
    await screen.findByText(/Approved SKU\/unit pairs: SOURDOUGH \/ pcs/);
    fireEvent.change(screen.getByLabelText(/Reviewer note/i), { target: { value: 'Verified evidence' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save & Accept' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/version mismatch/i);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('keeps suggestion as an unsent note and hides closed workspace', () => {
    const missing = { ...context, requested_items: [], missing_fields: ['unit'], field_evidence: { sku: [{ quote: 'burgers', normalized_value: 'BURGER', method: 'RULE' }], quantity: [{ quote: '50', normalized_value: '50', method: 'RULE' }] } } as OrderContextRecord;
    expect(getSuggestedClarification(missing)).toContain('confirm the unit');
    const view = render(<ReviewDrawer {...props} context={missing} />);
    fireEvent.click(screen.getByRole('button', { name: 'Use as clarification note' }));
    expect(screen.getByLabelText(/Reviewer note/i)).toHaveValue(getSuggestedClarification(missing));
    expect(screen.getByText(/not sent to the customer/i)).toBeInTheDocument();
    view.rerender(<ReviewDrawer {...props} context={missing} isOpen={false} />);
    expect(screen.queryByTestId('review-drawer')).not.toBeInTheDocument();
  });
});
