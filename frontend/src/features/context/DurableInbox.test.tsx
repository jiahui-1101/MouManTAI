import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DurableInbox } from './DurableInbox';
import { operationalApi } from './operationalApi';
import type { OperationalApi } from './operationalApi';
import type { DevelopmentContext, IngestResponse, MessagePage, RawMessageEnvelope, StoredMessage } from './types';

const timestamp = '2026-10-21T02:00:00Z';
const context: DevelopmentContext = { mode: 'LOCAL_SYNTHETIC_ONLY', tenant_id: 'server_tenant', implemented_channel: 'WHATSAPP', authentication: 'NOT_IMPLEMENTED' };
const raw: RawMessageEnvelope = { tenant_id: context.tenant_id, channel: 'WHATSAPP', adapter_mode: 'SYNTHETIC', provider_message_id: 'synthetic_fixed_1', sender_identity_id: 'sender_1', sender_alias: 'Synthetic buyer', received_at: timestamp, message_at: timestamp, text: '  Need 100 burgers tomorrow.  ', business_timezone: 'Asia/Kuala_Lumpur', attachments: [], thread_ref: 'thread_1' };
const message: StoredMessage = { message_id: 'stored_message_1', raw, synthetic_provider: 'SYNTHETIC_WHATSAPP', processing_status: 'RECEIVED', content_sha256: 'a'.repeat(64), ingested_at: timestamp, updated_at: timestamp };
const page = (items: StoredMessage[] = []): MessagePage => ({ items, total: items.length, limit: 25, offset: 0 });

function fakeApi(): OperationalApi {
  return {
    config: vi.fn().mockResolvedValue(context),
    list: vi.fn().mockResolvedValue(page()),
    detail: vi.fn().mockResolvedValue(message),
    ingest: vi.fn().mockResolvedValue({ message, duplicate: false }),
    process: vi.fn().mockResolvedValue({
      message: { ...message, processing_status: 'PROCESSED' },
      attempt: {
        attempt_id: 'att_1',
        tenant_id: 'server_tenant',
        message_id: 'stored_message_1',
        extractor_version: 'p1-deterministic-v3',
        input_content_sha256: 'a'.repeat(64),
        status: 'PROCESSED',
        fields: [
          {
            field_name: 'sku',
            value: 'BURGER',
            validation_status: 'VALID',
            qualifier: null,
            metadata: {},
            evidence: [{ evidence_id: 'ev_1', message_id: 'stored_message_1', quote: 'burgers', start: 11, end: 18, method: 'RULE', method_version: 'p1-deterministic-v3' }],
          },
          {
            field_name: 'quantity',
            value: '100',
            validation_status: 'VALID',
            qualifier: null,
            metadata: {},
            evidence: [{ evidence_id: 'ev_2', message_id: 'stored_message_1', quote: '100', start: 7, end: 10, method: 'RULE', method_version: 'p1-deterministic-v3' }],
          },
        ],
        started_at: timestamp,
        completed_at: timestamp,
      },
      reprocessed: false,
    }),
    getExtraction: vi.fn().mockRejectedValue(new Error('No extraction')),
    listAttempts: vi.fn().mockResolvedValue({ items: [] }),
    getAssociation: vi.fn().mockResolvedValue({
      association_id: 'assoc_1',
      tenant_id: 'server_tenant',
      message_id: 'stored_message_1',
      status: 'LINK_CANDIDATE',
      verified_customer: null,
      verified_order: null,
      candidates: [
        {
          customer_id: 'cust_bk',
          customer_name: 'Burger King',
          order_id: 'ORD-1001',
          match_type: 'EXTRACTED_ORDER_REF',
          reasons: ['Explicit reference found'],
          evidence: ['Ref ORD-1001'],
          confidence: 0.8,
        },
      ],
      conflicts: [],
      last_decision: null,
      version: 1,
      updated_at: timestamp,
    }),
    decideAssociation: vi.fn().mockImplementation((_id, req) =>
      Promise.resolve({
        association_id: 'assoc_1',
        tenant_id: 'server_tenant',
        message_id: 'stored_message_1',
        status: req.decision === 'CONFIRMED' ? 'LINK_VERIFIED' : 'UNVERIFIED',
        verified_customer: req.decision === 'CONFIRMED' ? { customer_id: req.target_customer_id, display_name: 'Burger King' } : null,
        verified_order: req.decision === 'CONFIRMED' ? { order_id: req.target_order_id, status: 'ACTIVE' } : null,
        candidates: [],
        conflicts: [],
        last_decision: {
          decision: req.decision,
          target_customer_id: req.target_customer_id,
          target_order_id: req.target_order_id,
          actor_id: 'staff_01',
          actor_role: 'STAFF',
          reason: req.reason,
          decided_at: timestamp,
        },
        version: req.expected_version + 1,
        updated_at: timestamp,
      })
    ),
    getContext: vi.fn().mockResolvedValue({
      context_id: 'ctx_1',
      tenant_id: 'server_tenant',
      order_id: 'ORD-1001',
      customer_id: 'cust_bk',
      customer_identity_status: 'LINK_VERIFIED',
      status: 'INFORMATION_READY',
      requested_items: [{ sku: 'BURGER', quantity: '100', unit: 'pcs' }],
      requested_delivery_at: timestamp,
      delivery_qualifier: 'EXACT',
      special_instructions: null,
      missing_fields: [],
      conflicts: [],
      source_message_ids: ['stored_message_1'],
      field_evidence: {},
      context_version: 1,
      last_reviewed_by: null,
      last_reviewed_role: null,
      created_at: timestamp,
      updated_at: timestamp,
    }),
    getContextByOrder: vi.fn().mockResolvedValue({
      context_id: 'ctx_1',
      tenant_id: 'server_tenant',
      order_id: 'ORD-1001',
      customer_id: 'cust_bk',
      customer_identity_status: 'LINK_VERIFIED',
      status: 'INFORMATION_READY',
      requested_items: [{ sku: 'BURGER', quantity: '100', unit: 'pcs' }],
      requested_delivery_at: timestamp,
      delivery_qualifier: 'EXACT',
      special_instructions: null,
      missing_fields: [],
      conflicts: [],
      source_message_ids: ['stored_message_1'],
      field_evidence: {},
      context_version: 1,
      last_reviewed_by: null,
      last_reviewed_role: null,
      created_at: timestamp,
      updated_at: timestamp,
    }),
    createContextFromMessage: vi.fn().mockResolvedValue({
      context_id: 'ctx_1',
      tenant_id: 'server_tenant',
      order_id: 'ORD-1001',
      customer_id: 'cust_bk',
      customer_identity_status: 'LINK_VERIFIED',
      status: 'INFORMATION_READY',
      requested_items: [{ sku: 'BURGER', quantity: '100', unit: 'pcs' }],
      requested_delivery_at: timestamp,
      delivery_qualifier: 'EXACT',
      special_instructions: null,
      missing_fields: [],
      conflicts: [],
      source_message_ids: ['stored_message_1'],
      field_evidence: {},
      context_version: 1,
      last_reviewed_by: null,
      last_reviewed_role: null,
      created_at: timestamp,
      updated_at: timestamp,
    }),
    reviewContext: vi.fn().mockResolvedValue({
      context_id: 'ctx_1',
      tenant_id: 'server_tenant',
      order_id: 'ORD-1001',
      customer_id: 'cust_bk',
      customer_identity_status: 'LINK_VERIFIED',
      status: 'INFORMATION_READY',
      requested_items: [{ sku: 'BURGER', quantity: '100', unit: 'pcs' }],
      requested_delivery_at: timestamp,
      delivery_qualifier: 'EXACT',
      special_instructions: null,
      missing_fields: [],
      conflicts: [],
      source_message_ids: ['stored_message_1'],
      field_evidence: {},
      context_version: 2,
      last_reviewed_by: 'staff_01',
      last_reviewed_role: 'STAFF',
      created_at: timestamp,
      updated_at: timestamp,
    }),
    updateContext: vi.fn().mockResolvedValue({
      context_id: 'ctx_1',
      tenant_id: 'server_tenant',
      order_id: 'ORD-1001',
      customer_id: 'cust_bk',
      customer_identity_status: 'LINK_VERIFIED',
      status: 'INFORMATION_READY',
      requested_items: [{ sku: 'BURGER', quantity: '100', unit: 'pcs' }],
      requested_delivery_at: timestamp,
      delivery_qualifier: 'EXACT',
      special_instructions: null,
      missing_fields: [],
      conflicts: [],
      source_message_ids: ['stored_message_1'],
      field_evidence: {},
      context_version: 2,
      last_reviewed_by: 'staff_01',
      last_reviewed_role: 'STAFF',
      created_at: timestamp,
      updated_at: timestamp,
    }),
    listContextVersions: vi.fn().mockResolvedValue([]),
    listContextReviews: vi.fn().mockResolvedValue([]),
    publishContext: vi.fn().mockResolvedValue({
      context_id: 'ctx_1',
      tenant_id: 'server_tenant',
      order_id: 'ORD-1001',
      customer_id: 'cust_bk',
      customer_identity_status: 'LINK_VERIFIED',
      status: 'INFORMATION_READY',
      requested_items: [{ sku: 'BURGER', quantity: '100', unit: 'pcs' }],
      requested_delivery_at: timestamp,
      delivery_qualifier: 'EXACT',
      special_instructions: null,
      missing_fields: [],
      conflicts: [],
      source_message_ids: ['stored_message_1'],
      field_evidence: {},
      context_version: 2,
      last_reviewed_by: 'staff_01',
      last_reviewed_role: 'STAFF',
      core_commitment_id: 'com_test_123',
      published_to_core_at: timestamp,
      created_at: timestamp,
      updated_at: timestamp,
    }),
    uploadAttachment: vi.fn(),
    extractAttachment: vi.fn(),
    getAttachmentExtraction: vi.fn(),
    getAttachmentMetadata: vi.fn(),
    getAttachmentPageCount: vi.fn().mockResolvedValue({ total_pages: 1, media_type: 'application/pdf' }),
  };
}

async function openComposer(api: OperationalApi) {
  render(<DurableInbox api={api} />);
  await screen.findByText('0 persisted messages');
  fireEvent.click(screen.getByRole('button', { name: '+ New synthetic message' }));
}

afterEach(() => vi.restoreAllMocks());

describe('durable synthetic Inbox', () => {
  it('submits to the API, refreshes the list and presents truthful awaiting-processing details', async () => {
    const api = fakeApi();
    vi.mocked(api.ingest).mockImplementation(async payload => {
      const stored = { ...message, raw: payload };
      vi.mocked(api.list).mockResolvedValue(page([stored]));
      vi.mocked(api.detail).mockResolvedValue(stored);
      return { message: stored, duplicate: false };
    });
    await openComposer(api);
    fireEvent.change(screen.getByLabelText('Original message text'), { target: { value: raw.text } });
    fireEvent.click(screen.getByRole('button', { name: 'Save synthetic message' }));
    expect(await screen.findByText('1 persisted messages')).toBeInTheDocument();
    expect(api.ingest).toHaveBeenCalledWith(expect.objectContaining({ tenant_id: 'server_tenant', text: raw.text, adapter_mode: 'SYNTHETIC', channel: 'WHATSAPP' }));
    fireEvent.click(screen.getByRole('button', { name: 'Synthetic buyer' }));
    const detail = screen.getByRole('region', { name: 'Persisted message details' });
    expect(await within(detail).findByText('synthetic_platform_sender')).toBeInTheDocument();
    expect(within(detail).getByText(/Awaiting processing. No extraction attempt has completed/)).toBeInTheDocument();
    expect(within(detail).queryByText('LINK_VERIFIED')).not.toBeInTheDocument();
    expect(within(detail).getByText('RECEIVED')).toBeInTheDocument();
    expect(api.detail).toHaveBeenCalledWith('stored_message_1');
  });

  it('validates missing original text without sending a request', async () => {
    const api = fakeApi();
    await openComposer(api);
    fireEvent.click(screen.getByRole('button', { name: 'Save synthetic message' }));
    expect(screen.getByRole('alert')).toHaveTextContent('original text are required');
    expect(api.ingest).not.toHaveBeenCalled();
  });

  it('retries the identical frozen payload after an uncertain response and prevents parallel submits', async () => {
    const api = fakeApi();
    let rejectFirst: (reason: Error) => void = () => {};
    vi.mocked(api.ingest).mockImplementationOnce(() => new Promise<IngestResponse>((_, reject) => { rejectFirst = reject; }))
      .mockResolvedValueOnce({ message, duplicate: true });
    await openComposer(api);
    fireEvent.change(screen.getByLabelText('Original message text'), { target: { value: 'Synthetic retry example' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save synthetic message' }));
    expect(screen.getByRole('button', { name: 'Saving message…' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Saving message…' }));
    expect(api.ingest).toHaveBeenCalledTimes(1);
    rejectFirst(new Error('Response lost after possible commit'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Response lost');
    expect(screen.getByLabelText('Provider message ID')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Retry same submission' }));
    expect(await screen.findByText(/Duplicate delivery — original message retrieved/)).toBeInTheDocument();
    expect(api.ingest).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.ingest).mock.calls[1][0]).toEqual(vi.mocked(api.ingest).mock.calls[0][0]);
  });

  it('keeps an uncertain submission stable while the Inbox refreshes', async () => {
    const api = fakeApi();
    vi.mocked(api.ingest).mockRejectedValue(new Error('Network unavailable'));
    await openComposer(api);
    fireEvent.change(screen.getByLabelText('Original message text'), { target: { value: 'Retry me' } });
    const providerId = (screen.getByLabelText('Provider message ID') as HTMLInputElement).value;
    fireEvent.click(screen.getByRole('button', { name: 'Save synthetic message' }));
    await screen.findByRole('button', { name: 'Retry same submission' });
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText('Provider message ID')).toHaveValue(providerId);
    fireEvent.click(screen.getByRole('button', { name: 'Retry same submission' }));
    await waitFor(() => expect(api.ingest).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.ingest).mock.calls[1][0]).toEqual(vi.mocked(api.ingest).mock.calls[0][0]);
  });

  it('handles loading, empty data, a failed fetch and retry', async () => {
    const api = fakeApi();
    vi.mocked(api.list).mockRejectedValueOnce(new Error('Storage unavailable')).mockResolvedValueOnce(page());
    render(<DurableInbox api={api} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading persisted');
    expect(await screen.findByRole('alert')).toHaveTextContent('Storage unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry Inbox' }));
    expect(await screen.findByText(/No persisted messages/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Fixture preview ↗' })).toHaveAttribute('href', '/inbox/fixtures');
  });

  it('fetches persisted metadata, retries detail errors and restores focus when closed', async () => {
    const api = fakeApi();
    vi.mocked(api.list).mockResolvedValue(page([message]));
    vi.mocked(api.detail).mockRejectedValueOnce(new Error('Detail failed')).mockResolvedValueOnce(message);
    render(<DurableInbox api={api} />);
    const button = await screen.findByRole('button', { name: 'View message synthetic_fixed_1' });
    fireEvent.click(button);
    expect(await screen.findByRole('alert')).toHaveTextContent('Detail failed');
    fireEvent.click(screen.getByRole('button', { name: 'Retry message' }));
    const detail = screen.getByRole('region', { name: 'Persisted message details' });
    expect(await within(detail).findByText('SYNTHETIC_WHATSAPP')).toBeInTheDocument();
    expect(within(detail).getByText('sender_1')).toBeInTheDocument();
    expect(within(detail).getByText('thread_1 / None')).toBeInTheDocument();
    fireEvent.keyDown(detail, { key: 'Escape' });
    expect(screen.queryByRole('region', { name: 'Persisted message details' })).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it('sends search/channel/processing and bounded pagination to the server', async () => {
    const api = fakeApi();
    vi.mocked(api.list).mockResolvedValue({ ...page([message]), total: 30 });
    render(<DurableInbox api={api} />);
    await screen.findByText('30 persisted messages');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 })));
    await screen.findByRole('button', { name: 'Previous' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Channel' }), { target: { value: 'EMAIL' } });
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ channel: 'EMAIL', offset: 0 })));
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search messages' }), { target: { value: 'burger' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Processing' }), { target: { value: 'RECEIVED' } });
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'burger', processing: 'RECEIVED' })));
  });

  it('triggers process extraction from detail panel and displays extracted fields and RULE method', async () => {
    const api = fakeApi();
    vi.mocked(api.list).mockResolvedValue(page([message]));
    vi.mocked(api.detail).mockResolvedValue(message);

    render(<DurableInbox api={api} />);
    expect(await screen.findByText('1 persisted messages')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Synthetic buyer' }));
    const detail = screen.getByRole('region', { name: 'Persisted message details' });

    const processBtn = await within(detail).findByRole('button', { name: 'Process extraction' });
    fireEvent.click(processBtn);

    await waitFor(() => expect(api.process).toHaveBeenCalledWith('stored_message_1', false));
    expect(await within(detail).findByText(/Pipeline version: p1-deterministic-v3/)).toBeInTheDocument();
    expect(within(detail).getByText('BURGER')).toBeInTheDocument();
    expect(within(detail).getAllByText('100').length).toBeGreaterThanOrEqual(2);
  });

  it('renders association candidates and allows manual confirmation', async () => {
    const api = fakeApi();
    api.list = vi.fn().mockResolvedValue(page([message]));
    render(<DurableInbox api={api} />);
    expect(await screen.findByText('1 persisted messages')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Synthetic buyer' }));
    const detail = screen.getByRole('region', { name: 'Persisted message details' });

    expect(await within(detail).findByText('Identity & Order Association')).toBeInTheDocument();
    expect(within(detail).getByText('LINK_CANDIDATE (v1)')).toBeInTheDocument();
    expect(within(detail).getByText('Suggested Association Candidates')).toBeInTheDocument();
    expect(within(detail).getByText('Burger King (cust_bk)')).toBeInTheDocument();

    // Confirm link
    fireEvent.click(within(detail).getByRole('button', { name: 'Confirm link' }));
    await waitFor(() => {
      expect(api.decideAssociation).toHaveBeenCalledWith(
        'stored_message_1',
        expect.objectContaining({
          decision: 'CONFIRMED',
          target_customer_id: 'cust_bk',
          target_order_id: 'ORD-1001',
          expected_version: 1,
        }),
      );
    });
    expect(await within(detail).findByText('LINK_VERIFIED (v2)')).toBeInTheDocument();
  });

  it('displays AI-ASSISTED badge and MODEL method in fields table when model candidates are present', async () => {
    const api = fakeApi();
    vi.mocked(api.list).mockResolvedValue(page([message]));
    vi.mocked(api.detail).mockResolvedValue(message);
    vi.mocked(api.getExtraction).mockResolvedValue({
      attempt_id: 'att_ai_1',
      tenant_id: 'server_tenant',
      message_id: 'stored_message_1',
      extractor_version: 'p1-ai-pipeline-v1',
      input_content_sha256: 'a'.repeat(64),
      status: 'PROCESSED',
      fields: [
        {
          field_name: 'sku',
          value: 'BURGER',
          validation_status: 'VALID',
          qualifier: null,
          metadata: {},
          evidence: [{ evidence_id: 'ev_1', message_id: 'stored_message_1', quote: 'burgers', start: 11, end: 18, method: 'RULE', method_version: 'p1-deterministic-v3' }],
        },
        {
          field_name: 'unit',
          value: 'pcs',
          validation_status: 'UNRESOLVED',
          qualifier: null,
          metadata: { reason: 'Model suggested unit', group_id: 'g1' },
          evidence: [{ evidence_id: 'ev_model_1', message_id: 'stored_message_1', quote: 'pcs', start: 0, end: 3, method: 'MODEL', method_version: 'Qwen2.5-7B-Instruct@main' }],
        },
      ],
      started_at: timestamp,
      completed_at: timestamp,
    });

    render(<DurableInbox api={api} />);
    expect(await screen.findByText('1 persisted messages')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Synthetic buyer' }));
    const detail = screen.getByRole('region', { name: 'Persisted message details' });

    expect(await within(detail).findByText(/RULES · NO ACCEPTED MODEL FIELDS/)).toBeInTheDocument();
    expect(within(detail).getByText('MODEL')).toBeInTheDocument();
    expect(within(detail).getByText('RULE')).toBeInTheDocument();
    expect(within(detail).getByText(/GPU unverified/)).toBeInTheDocument();
  });

  it('displays RULE (FALLBACK) badge when diagnostic indicates fallback to rules', async () => {
    const api = fakeApi();
    vi.mocked(api.list).mockResolvedValue(page([message]));
    vi.mocked(api.detail).mockResolvedValue(message);
    vi.mocked(api.getExtraction).mockResolvedValue({
      attempt_id: 'att_fallback_1',
      tenant_id: 'server_tenant',
      message_id: 'stored_message_1',
      extractor_version: 'p1-deterministic-v3',
      input_content_sha256: 'a'.repeat(64),
      status: 'PROCESSED',
      diagnostic: '{"fallback": "rules_only", "model_outcomes": {"qwen": "unavailable"}}',
      fields: [
        {
          field_name: 'sku',
          value: 'BURGER',
          validation_status: 'VALID',
          qualifier: null,
          metadata: {},
          evidence: [{ evidence_id: 'ev_1', message_id: 'stored_message_1', quote: 'burgers', start: 11, end: 18, method: 'RULE', method_version: 'p1-deterministic-v3' }],
        },
      ],
      started_at: timestamp,
      completed_at: timestamp,
    });

    render(<DurableInbox api={api} />);
    expect(await screen.findByText('1 persisted messages')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Synthetic buyer' }));
    const detail = screen.getByRole('region', { name: 'Persisted message details' });

    expect(await within(detail).findByText(/RULE \(FALLBACK\)/)).toBeInTheDocument();
    expect(within(detail).getByText(/deterministic results preserved/)).toBeInTheDocument();
  });

  it('opens review drawer side-by-side with original message panel and shifts message panel to the left', async () => {
    const api = fakeApi();
    const processedMessage = { ...message, processing_status: 'PROCESSED' as const };
    vi.mocked(api.list).mockResolvedValue(page([processedMessage]));
    vi.mocked(api.detail).mockResolvedValue(processedMessage);
    vi.mocked(api.createContextFromMessage).mockResolvedValue({
      context_id: 'ctx_sidebyside_1',
      tenant_id: 'server_tenant',
      order_id: null,
      customer_id: null,
      customer_identity_status: 'UNVERIFIED',
      status: 'INFORMATION_PARTIAL',
      requested_items: [{ sku: 'BURGER', quantity: '50', unit: 'pcs' }],
      requested_delivery_at: null,
      delivery_qualifier: null,
      special_instructions: null,
      missing_fields: [],
      conflicts: [],
      source_message_ids: ['stored_message_1'],
      field_evidence: {},
      context_version: 1,
      last_reviewed_by: null,
      last_reviewed_role: null,
      created_at: timestamp,
      updated_at: timestamp,
    });

    render(<DurableInbox api={api} />);
    expect(await screen.findByText('1 persisted messages')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Synthetic buyer' }));
    const detail = screen.getByRole('region', { name: 'Persisted message details' });
    expect(detail).toBeInTheDocument();
    expect(detail).not.toHaveClass('p1-detail-shifted');

    // Click Review & Amend
    const reviewBtn = await within(detail).findByRole('button', { name: 'Review & Amend' });
    fireEvent.click(reviewBtn);

    // Both panels are now open side by side!
    await waitFor(() => {
      expect(detail).toHaveClass('p1-detail-shifted');
      expect(screen.getByRole('dialog', { name: 'Context Review & Amendments' })).toBeInTheDocument();
    });

    // Original message is still visible and interactive
    expect(within(detail).getByText('PERSISTED SOURCE · SYNTHETIC')).toBeInTheDocument();
    expect(within(detail).getByText('Original message')).toBeInTheDocument();

    // Review drawer has the form fields on the right
    expect(screen.getByDisplayValue('BURGER')).toBeInTheDocument();
    expect(screen.getByDisplayValue('50')).toBeInTheDocument();

    // Close review drawer via its close button
    const closeReviewBtn = screen.getByRole('button', { name: 'Close drawer' });
    fireEvent.click(closeReviewBtn);

    // Review drawer is closed, but original message panel remains open and returns to unshifted state
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Context Review & Amendments' })).not.toBeInTheDocument();
      expect(detail).not.toHaveClass('p1-detail-shifted');
    });
    expect(detail).toBeInTheDocument();
  });
});

it('uses generated-envelope payloads and operational routes with useful server errors', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify(page([message]))));
  await operationalApi.list({ channel: 'WHATSAPP', processing: 'RECEIVED', search: '100%', offset: 0 });
  expect(fetcher).toHaveBeenLastCalledWith('/v1/messages?limit=25&offset=0&channel=WHATSAPP&search=100%25&processing_status=RECEIVED', undefined);
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ message, duplicate: false }), { status: 201 }));
  await operationalApi.ingest(raw);
  expect(fetcher).toHaveBeenLastCalledWith('/v1/messages/ingest', expect.objectContaining({ method: 'POST', body: JSON.stringify(raw) }));
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Immutable content conflict' }), { status: 409 }));
  await expect(operationalApi.ingest(raw)).rejects.toMatchObject({ status: 409, message: 'Immutable content conflict' });
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ detail: [{ msg: 'Invalid timestamp' }] }), { status: 422 }));
  await expect(operationalApi.ingest(raw)).rejects.toThrow('Invalid timestamp');
});
