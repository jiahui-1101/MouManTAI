import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { HumanReviewPage } from './HumanReviewPage';
import { operationalApi } from './operationalApi';
import { AuthProvider } from '../../shared/auth';
import type {
  ExtractionAttemptRecord,
  MessageAssociationRecord,
  OrderContextRecord,
  StoredMessage,
} from './types';

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
  processing_status: 'RECEIVED',
  extractor_version: 'p1-deterministic-v6',
  ingested_at: '2026-10-24T10:00:00Z',
  updated_at: '2026-10-24T10:00:00Z',
};

const mockContext: OrderContextRecord = {
  context_id: 'ctx_hr_1',
  tenant_id: 'synthetic_tenant_a',
  order_id: 'ORD-HR-1',
  customer_id: 'cust_hr_1',
  customer_identity_status: 'LINK_CANDIDATE',
  status: 'INFORMATION_PARTIAL',
  requested_items: [{ sku: 'CROISSANT', quantity: '20', unit: 'box' }],
  requested_delivery_at: '2026-10-25T15:00:00+08:00',
  delivery_qualifier: 'DEADLINE',
  special_instructions: 'Pack in insulated boxes',
  missing_fields: ['unit'],
  conflicts: ['Delivery window outside standard hours'],
  source_message_ids: ['msg_hr_1'],
  field_evidence: {
    sku: [{ quote: 'croissants', normalized_value: 'CROISSANT', method: 'MODEL' }],
    quantity: [{ quote: '20', normalized_value: '20', method: 'MODEL' }],
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
  status: 'LINK_CANDIDATE',
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
    vi.spyOn(operationalApi, 'getExtraction').mockResolvedValue(mockExtraction);
    vi.spyOn(operationalApi, 'getAssociation').mockResolvedValue(mockAssociation);
    vi.spyOn(operationalApi, 'getContextByOrder').mockResolvedValue(mockContext);
    vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({
      ...mockContext,
      context_version: 2,
      status: 'INFORMATION_READY',
    });
  });

  it('renders workspace with header, architecture banner, and queue items', async () => {
    renderPage(<HumanReviewPage />);

    expect(screen.getByText('Human Review Workspace')).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent(/Inquiry Review Workspace · Evidenced & Audited/i);
    await waitFor(() => {
      expect(screen.getByText('Alice Baker')).toBeInTheDocument();
      expect(screen.getByText(/Please send 20 boxes of croissants/i)).toBeInTheDocument();
    });
  });

  it('displays original evidence, extracted fields, and context form upon selection', async () => {
    renderPage(<HumanReviewPage />);

    await waitFor(() => {
      expect(screen.getByText('Original Evidence')).toBeInTheDocument();
      expect(screen.getByDisplayValue('CROISSANT')).toBeInTheDocument();
      expect(screen.getByDisplayValue('20')).toBeInTheDocument();
      expect(screen.getByDisplayValue('box')).toBeInTheDocument();
    });
  });

  it('keeps amendment values while moving between review activities', async () => {
    renderPage(<HumanReviewPage />);
    await waitFor(() => expect(screen.getByDisplayValue('CROISSANT')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('tab', { name: 'Amendments' }));
    fireEvent.change(screen.getByDisplayValue('CROISSANT'), { target: { value: 'SOURDOUGH' } });
    fireEvent.click(screen.getByRole('tab', { name: 'Inquiry & Evidence' }));
    expect(screen.getByRole('tab', { name: 'Inquiry & Evidence' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByRole('tab', { name: 'Amendments' }));
    expect(screen.getByDisplayValue('SOURDOUGH')).toBeInTheDocument();
  });

  it('adopts suggested clarification preview into the reviewer note', async () => {
    renderPage(<HumanReviewPage />);

    await waitFor(() => {
      expect(screen.getByText(/AI Suggested Clarification/i)).toBeInTheDocument();
    });

    const adoptBtn = screen.getByRole('button', { name: /Adopt as Clarification Note/i });
    fireEvent.click(adoptBtn);

    const noteTextarea = screen.getByPlaceholderText(/State reason for changes or clarification details/i);
    expect(noteTextarea).toHaveValue('Could you please confirm the unit for the 20 croissant (e.g., pcs or boxes)?');
  });

  it('submits field edits with expected_context_version and optimistic protection', async () => {
    const onUpdated = vi.fn();
    renderPage(<HumanReviewPage onContextUpdated={onUpdated} />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('CROISSANT')).toBeInTheDocument();
    });

    // Mark conflicts resolved
    const conflictCheckbox = screen.getByRole('checkbox', { name: /I reviewed and resolved all policy conflicts/i });
    fireEvent.click(conflictCheckbox);

    const applyBtn = screen.getByRole('button', { name: 'Apply Field Edits' });
    fireEvent.click(applyBtn);

    await waitFor(() => {
      expect(operationalApi.reviewContext).toHaveBeenCalledWith(
        'ctx_hr_1',
        expect.objectContaining({
          action: 'EDIT_FIELD',
          expected_context_version: 1,
        }),
        expect.any(Object)
      );
      expect(screen.getByText(/successfully recorded/i)).toBeInTheDocument();
      expect(onUpdated).toHaveBeenCalled();
    });
  });

  it('displays version conflict banner when server returns 409 stale version', async () => {
    vi.spyOn(operationalApi, 'reviewContext').mockRejectedValue(new Error('Context version mismatch: expected 1, got 2'));
    renderPage(<HumanReviewPage />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('CROISSANT')).toBeInTheDocument();
    });

    const conflictCheckbox = screen.getByRole('checkbox', { name: /I reviewed and resolved all policy conflicts/i });
    fireEvent.click(conflictCheckbox);

    const applyBtn = screen.getByRole('button', { name: 'Apply Field Edits' });
    fireEvent.click(applyBtn);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/Version Conflict: The context was updated by another process/i);
      expect(screen.getByRole('button', { name: /Reload Latest Context/i })).toBeInTheDocument();
    });
  });

  it('renders backend operational capability pill and clarification issues timeline', async () => {
    renderPage(<HumanReviewPage />);

    await waitFor(() => {
      expect(screen.getByText(/Direct Review \(v2\.1\)/i)).toBeInTheDocument();
      expect(screen.getByText(/Clarification Issues/i)).toBeInTheDocument();
      expect(screen.getByText(/Turns: 0 \/ 2 max/i)).toBeInTheDocument();
    });
  });

  it('handles dispatch clarification draft with safe preview non-simulation feedback', async () => {
    renderPage(<HumanReviewPage />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Dispatch Clarification Draft/i })).toBeInTheDocument();
    });

    const dispatchBtn = screen.getByRole('button', { name: /Dispatch Clarification Draft/i });
    fireEvent.click(dispatchBtn);

    await waitFor(() => {
      expect(screen.getByText(/Preview Retained: Outbound endpoint is pending backend release/i)).toBeInTheDocument();
    });
  });
});
