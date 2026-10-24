import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { HumanReviewPage, validateDeliveryTimestamp } from './HumanReviewPage';
import { operationalApi } from './operationalApi';
import { AuthProvider } from '../../shared/auth';
import type {
  ExtractionAttemptRecord,
  MessageAssociationRecord,
  OrderContextRecord,
  StoredMessage,
} from './types';

vi.mock('./useScopedOperationalApi', () => ({ useScopedOperationalApi: () => operationalApi }));

const mockMessage: StoredMessage = {
  message_id: 'msg_hr_1',
  raw: {
    tenant_id: 'synthetic_tenant_a',
    channel: 'EMAIL',
    provider_message_id: 'email_101',
    sender_identity_id: 'alice@example.com',
    sender_alias: 'Alice Baker',
    received_at: '2026-10-24T10:00:00Z',
    text: 'Please send 20 boxes of croissants for tomorrow at 3pm.',
  },
  provider: 'GMAIL_API',
  source_label: 'Gmail',
  content_sha256: 'sha256_mock_hash_1234567890',
  processing_status: 'PROCESSED',
  extractor_version: 'p1-deterministic-v6',
  ingested_at: '2026-10-24T10:00:00Z',
  updated_at: '2026-10-24T10:00:00Z',
};

const mockContext: OrderContextRecord = {
  context_id: 'ctx_hr_1',
  tenant_id: 'synthetic_tenant_a',
  order_id: 'ORD-HR-1',
  customer_id: 'cust_hr_1',
  customer_identity_status: 'LINK_VERIFIED',
  status: 'INFORMATION_PARTIAL',
  requested_items: [{ sku: 'CROISSANT', quantity: '20', unit: 'box' }],
  requested_delivery_at: '2026-10-25T15:00:00+08:00',
  delivery_qualifier: 'DEADLINE',
  special_instructions: 'Pack in insulated boxes',
  missing_fields: ['unit'],
  conflicts: ['Delivery window outside standard hours'],
  source_message_ids: ['msg_hr_1'],
  field_evidence: {
    sku: [{ quote: 'croissants', normalized_value: 'CROISSANT', method: 'MODEL', start: 24, end: 34 }],
    quantity: [{ quote: '20', normalized_value: '20', method: 'MODEL', start: 12, end: 14 }],
    unit: [{ quote: 'boxes', normalized_value: 'box', method: 'MODEL' }],
    requested_delivery_at: [{ quote: 'tomorrow at 3pm', normalized_value: '2026-10-25T15:00:00+08:00', method: 'MODEL' }],
  },
  context_version: 1,
  created_at: '2026-10-24T10:00:00Z',
  updated_at: '2026-10-24T10:00:00Z',
};

const mockExtraction: ExtractionAttemptRecord = {
  attempt_id: 'att_hr_1',
  tenant_id: 'synthetic_tenant_a',
  message_id: 'msg_hr_1',
  extractor_version: 'p1-deterministic-v6',
  input_content_sha256: 'sha256_mock_input_1234567890',
  status: 'PROCESSED',
  fields: [
    {
      field_name: 'sku',
      value: 'CROISSANT',
      validation_status: 'VALID',
      evidence: [{
        evidence_id: 'ev_1',
        message_id: 'msg_hr_1',
        quote: 'croissants',
        method: 'MODEL',
        method_version: 'v1',
        start: 24,
        end: 34,
      }],
    },
    {
      field_name: 'quantity',
      value: '20',
      validation_status: 'VALID',
      evidence: [{
        evidence_id: 'ev_2',
        message_id: 'msg_hr_1',
        quote: '20',
        method: 'MODEL',
        method_version: 'v1',
        start: 12,
        end: 14,
      }],
    },
  ],
  diagnostic: JSON.stringify({ model_outcomes: { qwen: 'SUCCESS' } }),
  started_at: '2026-10-24T10:00:00Z',
};

const mockAssociation: MessageAssociationRecord = {
  association_id: 'asc_1',
  message_id: 'msg_hr_1',
  tenant_id: 'synthetic_tenant_a',
  status: 'LINK_VERIFIED',
  verified_order: {
    order_id: 'ORD-HR-1',
    customer_id: 'cust_1',
    tenant_id: 'synthetic_tenant_a',
    status: 'ACTIVE',
    description: 'Order 1',
  },
  version: 1,
  updated_at: '2026-10-24T10:00:00Z',
};

function renderPage(ui: React.ReactElement) {
  return render(
    <AuthProvider initialTenantId="synthetic_tenant_a" initialActorId="user_staff_01">
      {ui}
    </AuthProvider>
  );
}

describe('HumanReviewPage component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(operationalApi, 'getCatalog').mockResolvedValue([
      { sku: 'CROISSANT', unit: 'box' },
      { sku: 'SOURDOUGH', unit: 'pcs' },
    ]);
    vi.spyOn(operationalApi, 'list').mockResolvedValue({
      items: [mockMessage],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.spyOn(operationalApi, 'detail').mockResolvedValue(mockMessage);
    vi.spyOn(operationalApi, 'getExtraction').mockResolvedValue(mockExtraction);
    vi.spyOn(operationalApi, 'getAssociation').mockResolvedValue(mockAssociation);
    vi.spyOn(operationalApi, 'getContextByOrder').mockResolvedValue(mockContext);
    vi.spyOn(operationalApi, 'getContext').mockResolvedValue({ ...mockContext, context_version: 2 });
    vi.spyOn(operationalApi, 'createContextFromMessage').mockResolvedValue(mockContext);
    vi.spyOn(operationalApi, 'listContextReviews').mockResolvedValue([
      {
        review_id: 'rev_1',
        tenant_id: 'synthetic_tenant_a',
        context_id: 'ctx_hr_1',
        context_version_before: 1,
        context_version_after: 2,
        action: 'EDIT_FIELD',
        actor_id: 'user_staff_01',
        actor_role: 'STAFF',
        note: 'Initial verified amendment',
        created_at: '2026-10-24T10:05:00Z',
      },
    ]);
    vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({
      ...mockContext,
      context_version: 2,
      status: 'INFORMATION_READY',
    });
  });

  /* -------------------------------------------------------------------------
     Page 1: Queue View
     ------------------------------------------------------------------------- */
  describe('Page 1: Human Review Queue (/inbox/human-review)', () => {
    it('renders header, circular icon, subtitle, and refresh button', async () => {
      renderPage(<HumanReviewPage />);

      expect(screen.getByRole('heading', { level: 1, name: 'Human Review' })).toBeInTheDocument();
      expect(screen.getByText(/Review customer inquiries, unverified model candidates and context conflicts with full audit protection/i)).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
        expect(screen.getByText('Alice Baker')).toBeInTheDocument();
        expect(screen.getByText('Gmail')).toBeInTheDocument();
        expect(screen.getByText(/Please send 20 boxes of croissants/i)).toBeInTheDocument();
      });
    });

    it('renders 4 KPI cards and filter pills', async () => {
      renderPage(<HumanReviewPage />);

      expect(screen.getByText('Total Reviews')).toBeInTheDocument();
      expect(screen.getByText('Pending Review')).toBeInTheDocument();
      expect(screen.getByText('Resolved')).toBeInTheDocument();
      expect(screen.getByText('Urgent Reviews')).toBeInTheDocument();

      expect(screen.getByRole('button', { name: /All inquiries/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Failed extractions/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Pending \/ unprocessed/i })).toBeInTheDocument();
    });

    it('renders filter card with Search, Task type dropdown (12 canonical types), Channel, Assigned to, Reset', async () => {
      renderPage(<HumanReviewPage />);

      expect(screen.getByLabelText('Search review tasks')).toBeInTheDocument();
      const taskTypeSelect = screen.getByLabelText('Filter by task type');
      expect(taskTypeSelect).toBeInTheDocument();

      // Check some of the 12 canonical options
      expect(within(taskTypeSelect).getByText('No progress after 2 follow-ups')).toBeInTheDocument();
      expect(within(taskTypeSelect).getByText('Low-confidence extraction')).toBeInTheDocument();
      expect(within(taskTypeSelect).getByText('Field conflict')).toBeInTheDocument();

      expect(screen.getByLabelText('Filter by channel')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Everyone' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Reset' })).toBeInTheDocument();
    });

    it('renders full-width table with required columns and Review button', async () => {
      renderPage(<HumanReviewPage />);

      await waitFor(() => {
        expect(screen.getByRole('columnheader', { name: /Received/i })).toBeInTheDocument();
        expect(screen.getByRole('columnheader', { name: 'Customer and message' })).toBeInTheDocument();
        expect(screen.getByRole('columnheader', { name: 'Task type' })).toBeInTheDocument();
        expect(screen.getByRole('columnheader', { name: 'Status' })).toBeInTheDocument();
        expect(screen.getByRole('columnheader', { name: /Priority/i })).toBeInTheDocument();
        expect(screen.getByRole('columnheader', { name: 'Assigned' })).toBeInTheDocument();
        expect(screen.getByRole('columnheader', { name: 'Action' })).toBeInTheDocument();

        expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument();
      });
    });

    it('allows clicking Review button and entire row is keyboard accessible (Enter / Space)', async () => {
      renderPage(<HumanReviewPage />);

      await waitFor(() => {
        const reviewBtn = screen.getByRole('button', { name: 'Review' });
        expect(reviewBtn).toBeInTheDocument();
      });

      const row = screen.getByRole('row', { name: /Alice Baker/i });
      expect(row).toHaveAttribute('tabindex', '0');
    });

    it('accurately distinguishes PROCESSED messages from Resolved human reviews and assigns sticky/assigned column classes', async () => {
      localStorage.clear();
      renderPage(<HumanReviewPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument();
      });

      // Before human review, Resolved is 0 even though messages are PROCESSED
      const resolvedCard = screen.getByText('Resolved').closest('.hr-kpi-card');
      expect(resolvedCard).toHaveTextContent('0');

      // Verify sticky Action column and assigned column classes exist
      const actionHeader = screen.getByRole('columnheader', { name: 'Action' });
      expect(actionHeader).toHaveClass('hr-col-action');

      const assignedHeader = screen.getByRole('columnheader', { name: 'Assigned' });
      expect(assignedHeader).toHaveClass('hr-col-assigned');
    });
  });

  /* -------------------------------------------------------------------------
     Page 2: Review & Amend Detail View (/inbox/human-review/:taskId)
     ------------------------------------------------------------------------- */
  describe('Page 2: Review & Amend Full Page (/inbox/human-review/:taskId)', () => {
    it('renders full page without drawer or modal backdrop', async () => {
      renderPage(<HumanReviewPage selectedTaskId="msg_hr_1" />);

      await waitFor(() => {
        expect(screen.getByRole('heading', { level: 1, name: /Review & Amend/i })).toBeInTheDocument();
      });

      // No drawer or modal backdrop on page mount
      expect(screen.queryByTestId('review-drawer')).not.toBeInTheDocument();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument();
    });

    it('renders header chips, subtitle, and More actions menu with required items', async () => {
      renderPage(<HumanReviewPage selectedTaskId="msg_hr_1" />);

      await waitFor(() => {
        expect(screen.getByText('INFORMATION_PARTIAL')).toBeInTheDocument();
        expect(screen.getByText('v1')).toBeInTheDocument();
        expect(screen.getByText(/Context ID: ctx_hr_1/i)).toBeInTheDocument();
      });

      const moreBtn = screen.getByRole('button', { name: /More actions ⋯/i });
      expect(moreBtn).toBeInTheDocument();
      fireEvent.click(moreBtn);

      expect(screen.getByText(/↻ Reprocess extraction/i)).toBeInTheDocument();
      expect(screen.getByText(/Forward for manager review/i)).toBeInTheDocument();
      expect(screen.getByText(/Mark unresolved/i)).toBeInTheDocument();
      expect(screen.getByText(/Open customer message/i)).toBeInTheDocument();
    });

    it('renders 4 status boxes (StatusStrip)', async () => {
      renderPage(<HumanReviewPage selectedTaskId="msg_hr_1" />);

      await waitFor(() => {
        expect(screen.getByText('Processing')).toBeInTheDocument();
        expect(screen.getByText('Information')).toBeInTheDocument();
        expect(screen.getByText('Identity')).toBeInTheDocument();
        expect(screen.getByText('Review')).toBeInTheDocument();
      });
    });

    it('renders Task Banner with task type, reason, and What you can do guidance', async () => {
      renderPage(<HumanReviewPage selectedTaskId="msg_hr_1" />);

      await waitFor(() => {
        expect(screen.getByText(/What you can do:/i)).toBeInTheDocument();
      });
    });

    it('renders Red Alert Bar when missing fields or conflicts exist', async () => {
      renderPage(<HumanReviewPage selectedTaskId="msg_hr_1" />);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(/Information needs review/i);
      });
    });

    it('renders 4 underline tabs and switches tabs correctly', async () => {
      renderPage(<HumanReviewPage selectedTaskId="msg_hr_1" />);

      await waitFor(() => {
        expect(screen.getByRole('tab', { name: 'Review & Amend' })).toBeInTheDocument();
        expect(screen.getByRole('tab', { name: 'Customer reply' })).toBeInTheDocument();
        expect(screen.getByRole('tab', { name: 'Identity & order' })).toBeInTheDocument();
        expect(screen.getByRole('tab', { name: 'History & audit' })).toBeInTheDocument();
      });

      // Switch to Customer reply
      fireEvent.click(screen.getByRole('tab', { name: 'Customer reply' }));
      expect(screen.getByText('Conversation with customer')).toBeInTheDocument();
      expect(screen.getByText('Customer update')).toBeInTheDocument();

      // Switch to Identity & order
      fireEvent.click(screen.getByRole('tab', { name: 'Identity & order' }));
      expect(screen.getByText('Identity & Order Association')).toBeInTheDocument();
      expect(screen.getByText(/Accepting or rejecting an order happens only on the order page/i)).toBeInTheDocument();

      // Switch to History & audit
      fireEvent.click(screen.getByRole('tab', { name: 'History & audit' }));
      expect(screen.getByRole('heading', { level: 2, name: 'History & audit' })).toBeInTheDocument();
      expect(screen.getByText(/Initial verified amendment/i)).toBeInTheDocument();
    });

    it('validates ISO8601 delivery offset correctly without false positives for +08:00', async () => {
      // Direct unit test of offset validator
      const validOffsetResult = validateDeliveryTimestamp('2026-10-28T10:00:00+08:00');
      expect(validOffsetResult.isValid).toBe(true);
      expect(validOffsetResult.hasOffset).toBe(true);
      expect(validOffsetResult.error).toBeUndefined();

      const naiveResult = validateDeliveryTimestamp('2026-10-28T10:00:00');
      expect(naiveResult.isValid).toBe(false);
      expect(naiveResult.hasOffset).toBe(false);
      expect(naiveResult.error).toContain('Missing or invalid offset');

      const resolvedWithTz = validateDeliveryTimestamp('2026-10-28T10:00:00', 'SGT');
      expect(resolvedWithTz.isValid).toBe(true);
      expect(resolvedWithTz.normalized).toContain('+08:00');
    });

    it('adopts AI clarification note and enables Save changes', async () => {
      renderPage(<HumanReviewPage selectedTaskId="msg_hr_1" />);

      await waitFor(() => {
        expect(screen.getByText(/AI suggested clarification/i)).toBeInTheDocument();
      });

      const useAIBtn = screen.getByRole('button', { name: 'Use as clarification note' });
      fireEvent.click(useAIBtn);

      const noteTextarea = screen.getByPlaceholderText(/State reason for changes, confirmation evidence, or clarification details…/i);
      expect(noteTextarea).toHaveValue('Could you please confirm the unit for the 20 croissant (e.g., pcs or boxes)?');
    });

    it('submits amendments with Reason modal and major field confirmation', async () => {
      const onUpdated = vi.fn();
      vi.mocked(operationalApi.getContext).mockResolvedValue({ ...mockContext, context_version: 2, requested_items: [{ ...(mockContext.requested_items || [])[0], sku: 'SOURDOUGH' }] });
      renderPage(<HumanReviewPage selectedTaskId="msg_hr_1" onContextUpdated={onUpdated} />);

      await waitFor(() => {
        expect(screen.getByDisplayValue('CROISSANT')).toBeInTheDocument();
      });

      // Edit SKU (major field)
      fireEvent.change(screen.getByLabelText('SKU / Product'), { target: { value: 'SOURDOUGH' } });

      // Fill reviewer note
      const noteTextarea = screen.getByPlaceholderText(/State reason for changes, confirmation evidence, or clarification details…/i);
      fireEvent.change(noteTextarea, { target: { value: 'Customer requested sourdough substitution' } });

      // Click Save changes -> opens confirmation modal
      const saveBtn = screen.getByRole('button', { name: 'Save changes' });
      expect(saveBtn).not.toBeDisabled();
      fireEvent.click(saveBtn);

      // Verify Modal is opened
      const modal = screen.getByRole('dialog', { name: 'Confirm Save Changes' });
      expect(modal).toBeInTheDocument();

      // Major field checkbox must be checked
      const confirmCheckbox = within(modal).getByRole('checkbox');
      expect(confirmCheckbox).toBeInTheDocument();
      fireEvent.click(confirmCheckbox);

      // Submit modal
      const modalSubmitBtn = within(modal).getByRole('button', { name: 'Save Changes' });
      fireEvent.click(modalSubmitBtn);

      await waitFor(() => {
        expect(operationalApi.reviewContext).toHaveBeenCalledWith(
          'ctx_hr_1',
          expect.objectContaining({
            action: 'EDIT_FIELD',
            expected_context_version: 1,
            note: 'Customer requested sourdough substitution',
          }),
          expect.any(Object)
        );
        expect(screen.getByText(/Saved. Audit entry recorded./i)).toBeInTheDocument();
        expect(onUpdated).toHaveBeenCalled();
      });
    });

    it('shows unsaved changes alert bar if dirty when Back is clicked', async () => {
      renderPage(<HumanReviewPage selectedTaskId="msg_hr_1" />);

      await waitFor(() => {
        expect(screen.getByDisplayValue('CROISSANT')).toBeInTheDocument();
      });

      fireEvent.change(screen.getByLabelText('SKU / Product'), { target: { value: 'SOURDOUGH' } });

      const backBtn = screen.getByRole('button', { name: 'Back' });
      fireEvent.click(backBtn);

      expect(screen.getByText('Unsaved review changes will be lost.')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Keep editing' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Discard and close' })).toBeInTheDocument();
    });
  });
});
