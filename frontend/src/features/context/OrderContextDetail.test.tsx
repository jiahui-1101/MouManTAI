import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OrderContextDetail } from './OrderContextDetail';
import { operationalApi } from './operationalApi';
import * as reviewApi from './operationalApi';
import type { ContextReviewRecord, OrderContextRecord, OrderContextVersionRecord } from './types';

const timestamp = '2026-10-21T02:00:00Z';

const mockContext: OrderContextRecord = {
  context_id: 'ctx_mock_1',
  tenant_id: 'test_tenant',
  order_id: 'ORD-5001',
  customer_id: 'cust_abc',
  customer_identity_status: 'LINK_VERIFIED',
  status: 'INFORMATION_PARTIAL',
  requested_items: [
    { sku: 'BURGER', quantity: '50', unit: 'pcs' },
  ],
  requested_delivery_at: '2026-10-22T15:00:00Z',
  delivery_qualifier: 'DEADLINE',
  special_instructions: 'Pack separately in boxes',
  missing_fields: ['delivery_address'],
  conflicts: ['Quantity conflict: requested 50, previous commitment 25'],
  source_message_ids: ['msg_001', 'msg_002'],
  field_evidence: {
    sku: [{ quote: 'burgers', start: 10, end: 17 }],
    quantity: [{ quote: '50', start: 7, end: 9 }],
  },
  context_version: 2,
  last_reviewed_by: 'staff_alice',
  last_reviewed_role: 'STAFF',
  created_at: timestamp,
  updated_at: timestamp,
};

const mockVersions: OrderContextVersionRecord[] = [
  {
    version_id: 'ver_1',
    tenant_id: 'test_tenant',
    context_id: 'ctx_mock_1',
    context_version: 1,
    change_type: 'INITIAL_CREATION',
    actor_id: 'system',
    actor_role: 'SYSTEM',
    reason: 'Created from message msg_001',
    snapshot: mockContext,
    created_at: '2026-10-21T01:00:00Z',
  },
  {
    version_id: 'ver_2',
    tenant_id: 'test_tenant',
    context_id: 'ctx_mock_1',
    context_version: 2,
    change_type: 'MESSAGE_MERGE',
    actor_id: 'system',
    actor_role: 'SYSTEM',
    reason: 'Follow-up message msg_002 merged with conflicts',
    snapshot: mockContext,
    created_at: '2026-10-21T02:00:00Z',
  },
];

const mockReviews: ContextReviewRecord[] = [
  {
    review_id: 'rev_1',
    tenant_id: 'test_tenant',
    context_id: 'ctx_mock_1',
    context_version_before: 1,
    context_version_after: 2,
    action: 'EDIT_FIELD',
    actor_id: 'staff_alice',
    actor_role: 'STAFF',
    note: 'Adjusted quantity based on customer clarification',
    field_changes: { quantity: { old: '25', new: '50' } },
    created_at: '2026-10-21T02:30:00Z',
  },
];

describe('OrderContextDetail component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(reviewApi, 'getReviewCatalog').mockResolvedValue([{ sku: 'BURGER', unit: 'pcs' }]);
    vi.spyOn(operationalApi, 'getContext').mockResolvedValue(mockContext);
    vi.spyOn(operationalApi, 'listContextVersions').mockResolvedValue(mockVersions);
    vi.spyOn(operationalApi, 'listContextReviews').mockResolvedValue(mockReviews);
    vi.spyOn(operationalApi, 'reviewContext').mockImplementation((_id, req) =>
      Promise.resolve({
        ...mockContext,
        context_version: req.expected_context_version + 1,
        status: 'INFORMATION_READY',
        conflicts: [],
        last_reviewed_by: 'user_staff_01',
        last_reviewed_role: 'STAFF',
      })
    );
  });

  it('renders order context details, status badges, dimensions, and evidence', async () => {
    render(<OrderContextDetail contextId="ctx_mock_1" />);

    await waitFor(() => {
      expect(screen.getByText('Order Context: ORD-5001')).toBeInTheDocument();
    });

    expect(screen.getByText('INFORMATION_PARTIAL')).toBeInTheDocument();
    expect(screen.getByText('v2')).toBeInTheDocument();
    expect(screen.getByText('LINK_VERIFIED')).toBeInTheDocument();
    expect(screen.getByText('cust_abc')).toBeInTheDocument();
    expect(screen.getByText('DEADLINE')).toBeInTheDocument();

    // Check requested items and evidence
    expect(screen.getByText('BURGER')).toBeInTheDocument();
    expect(screen.getByText('50')).toBeInTheDocument();
    expect(screen.getByText('"burgers"')).toBeInTheDocument();
    expect(screen.getByText('"50"')).toBeInTheDocument();
    expect(screen.getByText(/Pack separately in boxes/)).toBeInTheDocument();

    // Check source messages
    expect(screen.getByText('msg_001')).toBeInTheDocument();
    expect(screen.getByText('msg_002')).toBeInTheDocument();
  });

  it('displays conflicts banner when conflicts exist', async () => {
    render(<OrderContextDetail contextId="ctx_mock_1" />);

    await waitFor(() => {
      expect(screen.getByText(/Security \/ Term Conflicts Detected/)).toBeInTheDocument();
    });

    expect(screen.getByText(/Quantity conflict: requested 50, previous commitment 25/)).toBeInTheDocument();
  });

  it('displays missing information banner', async () => {
    render(<OrderContextDetail contextId="ctx_mock_1" />);

    await waitFor(() => {
      expect(screen.getByText(/Information Partial — Missing Fields/)).toBeInTheDocument();
      expect(screen.getByText('delivery_address')).toBeInTheDocument();
    });
  });

  it('toggles version history and shows previous versions and reviews', async () => {
    render(<OrderContextDetail contextId="ctx_mock_1" />);

    await waitFor(() => {
      expect(screen.getByText('Order Context: ORD-5001')).toBeInTheDocument();
    });

    // History is initially hidden
    expect(screen.queryByLabelText('Version History')).not.toBeInTheDocument();

    // Click toggle
    fireEvent.click(screen.getByRole('button', { name: /Version History/ }));

    expect(screen.getByLabelText('Version History')).toBeInTheDocument();
    expect(screen.getByText('INITIAL_CREATION')).toBeInTheDocument();
    expect(screen.getByText('MESSAGE_MERGE')).toBeInTheDocument();
    expect(screen.getByText(/Follow-up message msg_002 merged/)).toBeInTheDocument();

    // Check review audit entries
    expect(screen.getByText('Human Review History (1)')).toBeInTheDocument();
    expect(screen.getByText('EDIT_FIELD')).toBeInTheDocument();
    expect(screen.getByText(/Adjusted quantity based on customer clarification/)).toBeInTheDocument();
  });

  it('opens review drawer and submits field edits with optimistic locking', async () => {
    render(<OrderContextDetail contextId="ctx_mock_1" />);

    await waitFor(() => {
      expect(screen.getByText('Order Context: ORD-5001')).toBeInTheDocument();
    });

    // Open review drawer
    fireEvent.click(screen.getByRole('button', { name: /Review & Amend/ }));

    expect(screen.getByText('Context Review & Amendments')).toBeInTheDocument();
    expect(screen.getByDisplayValue('BURGER')).toBeInTheDocument();
    expect(screen.getByDisplayValue('50')).toBeInTheDocument();

    // Modify quantity and notes
    fireEvent.change(screen.getByLabelText(/^Quantity$/i), { target: { value: '60' } });
    fireEvent.change(screen.getByLabelText(/Reviewer Note/i), { target: { value: 'Customer increased to 60 via phone call' } });

    // Submit review
    fireEvent.click(screen.getByRole('button', { name: /Apply Field Edits/i }));

    await waitFor(() => {
      expect(operationalApi.reviewContext).toHaveBeenCalledWith(
        'ctx_mock_1',
        expect.objectContaining({
          expected_context_version: 2,
          action: 'EDIT_FIELD',
          note: 'Customer increased to 60 via phone call',
          field_edits: expect.objectContaining({
            requested_items: [{ sku: 'BURGER', quantity: '60', unit: 'pcs' }],
          }),
        }),
        expect.objectContaining({
          'X-Actor-ID': 'user_staff_01',
          'X-Actor-Role': 'STAFF',
        })
      );
    });
  });

  it('handles 409 stale version conflict error in review drawer', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockRejectedValue(
      new Error('Stale context version 2; current database version is 3')
    );

    render(<OrderContextDetail contextId="ctx_mock_1" />);

    await waitFor(() => {
      expect(screen.getByText('Order Context: ORD-5001')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Review & Amend/ }));
    fireEvent.click(screen.getByRole('button', { name: /Apply Field Edits/i }));

    await waitFor(() => {
      expect(screen.getByText(/Stale context version 2/)).toBeInTheDocument();
    });
  });

  it('publishes context to Core successfully and renders commitment badge', async () => {
    vi.spyOn(operationalApi, 'publishContext').mockResolvedValue({
      ...mockContext,
      core_commitment_id: 'com_pub_123',
      published_to_core_at: '2026-10-22T08:00:00Z',
    });

    render(<OrderContextDetail contextId="ctx_mock_1" />);

    await waitFor(() => {
      expect(screen.getByText('Order Context: ORD-5001')).toBeInTheDocument();
    });

    const publishBtn = screen.getByRole('button', { name: 'Publish to Core' });
    expect(publishBtn).toBeInTheDocument();

    fireEvent.click(publishBtn);

    await waitFor(() => {
      expect(operationalApi.publishContext).toHaveBeenCalledWith('ctx_mock_1');
      expect(screen.getByText('Core: com_pub_123')).toBeInTheDocument();
      expect(screen.getByText(/Successfully published to Core commitment com_pub_123/)).toBeInTheDocument();
    });
  });

  it('displays error alert when Core publication fails', async () => {
    vi.spyOn(operationalApi, 'publishContext').mockRejectedValue(
      new Error('Publishing rejected: Context status is not INFORMATION_READY')
    );

    render(<OrderContextDetail contextId="ctx_mock_1" />);

    await waitFor(() => {
      expect(screen.getByText('Order Context: ORD-5001')).toBeInTheDocument();
    });

    const publishBtn = screen.getByRole('button', { name: 'Publish to Core' });
    fireEvent.click(publishBtn);

    await waitFor(() => {
      expect(screen.getByText(/Publish to Core Ineligible \/ Failed/)).toBeInTheDocument();
      expect(screen.getByText(/Context status is not INFORMATION_READY/)).toBeInTheDocument();
    });
  });
});

