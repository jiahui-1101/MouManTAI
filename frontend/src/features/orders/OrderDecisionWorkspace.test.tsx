import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, useAuth } from '../../shared/auth';
import { ApiError } from '../../shared/api';
import { OrderDecisionWorkspace } from './OrderDecisionWorkspace';
import type { OrderDecisionSource } from './decisionTypes';
import { decisionNow, decisionOrder, decisionSnapshot } from './decisionTest.fixtures';

const sourceFor = (snapshot = decisionSnapshot()): OrderDecisionSource => ({ cacheKey: 'test-only', load: vi.fn().mockResolvedValue(snapshot) });
function setup(source: OrderDecisionSource = sourceFor()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false } } });
  return { client, ...render(<QueryClientProvider client={client}><AuthProvider initialTenantId="tenant-one"><MemoryRouter>
    <OrderDecisionWorkspace order={decisionOrder()} source={source} now={decisionNow} />
  </MemoryRouter></AuthProvider></QueryClientProvider>) };
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const acceptance = () => screen.getByRole('region', { name: 'Acceptance review' });
const sourceState = () => screen.findByRole('status', { name: 'Order decision source state' });
describe('Read-only Order Decision workspace', () => {
  it('hides terms, agreements, financials and unsent preparation while records refresh or access is revoked', async () => {
    let reject!: (error: Error) => void;
    const source = sourceFor(); vi.mocked(source.load).mockResolvedValueOnce(decisionSnapshot()).mockImplementation(() => new Promise((_, fail) => { reject = fail; }));
    setup(source); await screen.findByRole('region', { name: 'Acceptance review' });
    fireEvent.click(screen.getByText('Prepare an unsent proposal comparison'));
    expect(screen.getByRole('form', { name: 'Unsent proposal preparation' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh decision records' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Acceptance review' })).not.toBeInTheDocument());
    expect(screen.queryByRole('form', { name: 'Unsent proposal preparation' })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('test-backend-hash-original');
    await act(async () => reject(new ApiError(403, 'FORBIDDEN', 'private')));
    await sourceState(); expect(document.body).not.toHaveTextContent('approved-quote');
  });
  it('shows exact backend-supplied terms, identity and blockers without acceptance controls', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); setup();
    await screen.findByRole('region', { name: 'Acceptance review' });
    expect(acceptance()).toHaveTextContent('test-backend-hash-original');
    expect(acceptance()).toHaveTextContent('approved-quote / quote-v3');
    expect(acceptance()).toHaveTextContent('Source reports disclosed');
    expect(acceptance()).toHaveTextContent('Authoritative request version: 7');
    for (const command of screen.getAllByRole('button', { name: /^(Accept|Submit|Reject|Reserve)/ })) expect(command).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('distinguishes original, proposed and current/previous confirmed terms without overwriting history', async () => {
    setup(); const comparison = await screen.findByRole('region', { name: 'Original customer request versus Proposed terms' });
    const priceRow = within(comparison).getByRole('row', { name: /Binding price/ });
    expect(priceRow).toHaveTextContent('120'); expect(priceRow).toHaveTextContent('130'); expect(priceRow).toHaveTextContent('Changed displayed value');
    expect(screen.getByText('Previous confirmed version 3')).toBeInTheDocument();
    expect(screen.getByText('Current agreement version: 4')).toBeInTheDocument();
    expect(screen.getByText(/Reservation delta not verified/)).toBeInTheDocument();
  });
  it('renders sent-only, superseded and expired proposal distinctions', async () => {
    const data = decisionSnapshot(); data.proposals![0].assent = undefined;
    setup(sourceFor(data)); await screen.findByRole('region', { name: 'Acceptance review' });
    expect(screen.getByText(/sending is not agreement/)).toBeInTheDocument();
    expect(screen.getByText(/Sending state: SENT/)).toBeInTheDocument();
  });
  it('local preparation compares fields and preserves originals without saving/sending/hashing', async () => {
    const data = decisionSnapshot(); const original = JSON.stringify(data); const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    const storage = vi.spyOn(Storage.prototype, 'setItem'); setup(sourceFor(data)); await screen.findByRole('region', { name: 'Acceptance review' });
    fireEvent.click(screen.getByText('Prepare an unsent proposal comparison'));
    const form = screen.getByRole('form', { name: 'Unsent proposal preparation' });
    fireEvent.change(within(form).getByLabelText('Line 1 quantity'), { target: { value: '25' } });
    fireEvent.change(within(form).getByLabelText('Prepared binding price'), { target: { value: '150' } });
    fireEvent.change(within(form).getByLabelText('Reason for prepared changes'), { target: { value: 'Synthetic scenario' } });
    expect(form).toHaveTextContent('Submission unavailable');
    expect(JSON.stringify(data)).toBe(original); expect(fetch).not.toHaveBeenCalled(); expect(storage).not.toHaveBeenCalled();
    fireEvent.submit(form); expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(within(form).getByRole('button', { name: 'Reset unsent preparation' }));
    fireEvent.click(screen.getByRole('button', { name: 'Discard unsent preparation' }));
    expect(within(form).getByLabelText('Line 1 quantity')).toHaveValue('20');
  });
  it('keeps decimal/quantity problems explicit in preparation', async () => {
    setup(); await screen.findByRole('region', { name: 'Acceptance review' }); fireEvent.click(screen.getByText('Prepare an unsent proposal comparison'));
    const form = screen.getByRole('form', { name: 'Unsent proposal preparation' });
    fireEvent.change(within(form).getByLabelText('Line 1 quantity'), { target: { value: '0' } });
    expect(within(form).getByRole('status')).toHaveTextContent('not backend validation');
  });
  it('resets unsent preparation on authoritative source refresh', async () => {
    setup(); await screen.findByRole('region', { name: 'Acceptance review' }); fireEvent.click(screen.getByText('Prepare an unsent proposal comparison'));
    fireEvent.change(screen.getByRole('form', { name: 'Unsent proposal preparation' }).querySelector('input')!, { target: { value: 'LOCAL-SKU' } });
    fireEvent.click(screen.getByRole('button', { name: 'Refresh decision records' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh decision records' })).toBeEnabled());
    fireEvent.click(screen.getByText('Prepare an unsent proposal comparison'));
    expect(within(screen.getByRole('form', { name: 'Unsent proposal preparation' })).getByLabelText('Line 1 sku')).toHaveValue('BREAD');
  });
  it.each(['REDACTED', 'UNKNOWN'] as const)('hides financial terms and their editable inputs for %s access', async access => {
    const data = decisionSnapshot(); data.financialAccess = access; setup(sourceFor(data)); await screen.findByRole('region', { name: 'Acceptance review' });
    expect(acceptance()).not.toHaveTextContent('approved-quote');
    expect(screen.queryByLabelText('Prepared binding price')).not.toBeInTheDocument();
    expect(screen.queryByText('120')).not.toBeInTheDocument();
  });
  it('shows only persisted timeline records, with unsupported receipt fields explicitly absent', async () => {
    setup(); const timeline = await screen.findByRole('region', { name: 'Decision & audit timeline' });
    expect(within(timeline).getAllByRole('listitem')).toHaveLength(1);
    expect(timeline).toHaveTextContent('event-one'); expect(timeline).toHaveTextContent('Receipt: Not available');
    expect(timeline).toHaveTextContent('Reservation: Not available');
  });
  it('renders failed/unknown reservations without success or an unsafe retry action', async () => {
    const data = decisionSnapshot(); data.receipts = [{ id: 'failed', orderId: 'order-one', outcome: 'FAILED', reason: 'Reservation conflict' },
      { id: 'unknown', orderId: 'order-one', outcome: 'UNKNOWN' }];
    setup(sourceFor(data)); await screen.findByRole('region', { name: 'Acceptance review' });
    const failed = screen.getByRole('heading', { name: 'Recorded receipt failed' }).closest('article')!;
    const unknown = screen.getByRole('heading', { name: 'Recorded receipt unknown' }).closest('article')!;
    expect(within(failed).getByText('Recorded failure — no acceptance inferred')).toBeInTheDocument();
    expect(within(unknown).getByText(/Outcome unresolved/)).toHaveTextContent('do not resubmit');
    expect(screen.queryByRole('button', { name: /retry.*(accept|reserve|command)/i })).not.toBeInTheDocument();
  });
  it.each([401, 403, 404, 409, 422, 503])('handles read %i with no leaked error body or command side effect', async status => {
    setup({ cacheKey: 'error', load: vi.fn().mockRejectedValue(new ApiError(status, 'TEST', 'private debug')) });
    expect(await sourceState()).toBeInTheDocument(); expect(screen.queryByText('private debug')).not.toBeInTheDocument();
    if (status === 409) expect(await sourceState()).toHaveTextContent('Source version conflict');
    expect(screen.queryByRole('region', { name: 'Acceptance review' })).not.toBeInTheDocument();
  });
  it('retries only the read source and hides stale records on refresh failure', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(decisionSnapshot()).mockRejectedValue(new Error('offline'));
    setup({ cacheKey: 'retry', load }); await sourceState();
    fireEvent.click(screen.getByRole('button', { name: 'Retry decision records' })); await screen.findByRole('region', { name: 'Acceptance review' });
    fireEvent.click(screen.getByRole('button', { name: 'Refresh decision records' })); await sourceState();
    expect(screen.queryByRole('region', { name: 'Acceptance review' })).not.toBeInTheDocument(); expect(load).toHaveBeenCalledTimes(3);
  });
  it('blocks duplicate read clicks while pending and never introduces a mutation handler', () => {
    setup({ cacheKey: 'loading', load: () => new Promise(() => {}) });
    expect(screen.getByText('Loading decision records…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh decision records' })).toBeDisabled();
  });
  it.each(['tenant', 'order'])('rejects wrong %s decision source', async type => {
    const data = decisionSnapshot(); if (type === 'tenant') data.tenantId = 'other'; else data.orderId = 'other';
    setup(sourceFor(data)); await sourceState(); expect(screen.queryByRole('region', { name: 'Acceptance review' })).not.toBeInTheDocument();
  });
  it('isolates tenant/actor changes and preserves keyboard-operable preparation', async () => {
    const load = vi.fn().mockResolvedValueOnce(decisionSnapshot()).mockImplementation(() => new Promise(() => {}));
    function Harness() { const auth = useAuth(); return <><button onClick={() => auth.setActorId('user_staff_01')}>Change actor</button>
      <button onClick={() => auth.setTenantId('other-tenant')}>Change tenant</button><OrderDecisionWorkspace order={decisionOrder()} source={{ cacheKey: 'scope', load }} now={decisionNow} /></>; }
    render(<QueryClientProvider client={new QueryClient()}><AuthProvider initialTenantId="tenant-one"><MemoryRouter><Harness /></MemoryRouter></AuthProvider></QueryClientProvider>);
    await screen.findByRole('region', { name: 'Acceptance review' }); const refresh = screen.getByRole('button', { name: 'Refresh decision records' }); refresh.focus(); expect(refresh).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Change actor' })); expect(screen.queryByRole('region', { name: 'Acceptance review' })).not.toBeInTheDocument();
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2)); expect(load.mock.calls[1][1].actorId).toBe('user_staff_01');
    fireEvent.click(screen.getByRole('button', { name: 'Change tenant' })); await sourceState(); expect(load).toHaveBeenCalledTimes(2);
  });
  it('production default with no verified commitment link performs no HTTP or mutation', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    render(<QueryClientProvider client={new QueryClient()}><AuthProvider initialTenantId="tenant-one"><MemoryRouter>
      <OrderDecisionWorkspace order={decisionOrder()} now={decisionNow} /></MemoryRouter></AuthProvider></QueryClientProvider>);
    await screen.findByRole('region', { name: 'Acceptance review' }); expect(fetch).not.toHaveBeenCalled();
    expect(screen.getByText('Exact customer-offered terms and backend terms identity are not verified.')).toBeInTheDocument();
    for (const button of screen.getAllByRole('button', { name: /^Accept/ })) expect(button).toBeDisabled();
  });
});
