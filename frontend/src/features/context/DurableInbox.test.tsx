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
    expect(within(detail).getByText(/Awaiting processing. Extraction is not implemented/)).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: '↻ Refresh' }));
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
    expect(await within(detail).findByText(/RULE \(p1-deterministic-v3\)/)).toBeInTheDocument();
    expect(within(detail).getByText('BURGER')).toBeInTheDocument();
    expect(within(detail).getAllByText('100').length).toBeGreaterThanOrEqual(2);
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
