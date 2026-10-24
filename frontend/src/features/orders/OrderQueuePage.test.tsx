import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, useAuth } from '../../shared/auth';
import { ApiError } from '../../shared/api';
import { OrderQueuePage } from './OrderQueuePage';
import { createOrderQueueHttpSource, type OrderQueueSource } from './api';
import { businessDate, initialFilters, profitText, selectOrders, timestamp } from './queue';
import type { OrderQueueItem, OrderQueueSnapshot } from './types';

// Synthetic data exists only in this test file; never imported by production.
const pending: OrderQueueItem = {
  id: 'order/one', status: 'PENDING_ACCEPTANCE', customer: 'Synthetic Alice',
  receivedAt: '2026-10-23T16:30:00Z', completedAt: '2026-10-24T01:00:00+08:00',
  lines: [{ product: 'Bread', quantity: '12', unit: 'pieces' }], deadline: null,
  channel: 'Telegram', priority: 'High', risk: 'Stock uncertain', size: 'Small',
  feasibility: 'UNKNOWN', profit: { amount: '100', costComplete: false }, evidenceTier: 'SYNTHETIC',
};
const items: OrderQueueItem[] = [pending,
  { ...pending, id: 'accepted', status: 'ACCEPTED', customer: 'Synthetic Bob', lines: [{ product: 'Cake' }], channel: 'Email', priority: 'Normal', risk: 'Unknown', size: 'Large' },
  { ...pending, id: 'rejected', status: 'REJECTED' },
  { ...pending, id: 'unknown', status: 'FUTURE_STATE' },
];
const snapshot: OrderQueueSnapshot = { items, coverage: 'partial' };
function setup(source?: OrderQueueSource, tenant = 'test-tenant', actor = 'user_owner_01') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><AuthProvider initialTenantId={tenant} initialActorId={actor}>
    <MemoryRouter><OrderQueuePage source={source} /></MemoryRouter></AuthProvider></QueryClientProvider>);
}
const sourceFor = (data = snapshot): OrderQueueSource => ({ cacheKey: 'test-only', load: vi.fn().mockResolvedValue(data) });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('Order Decision Queue', () => {
  it('defaults to All Statuses and removes only the Queue planning shortcuts', async () => {
    setup(sourceFor()); await screen.findByRole('table');
    expect(screen.getByRole('combobox', { name: 'Order Status' })).toHaveValue('ALL');
    expect(screen.getAllByRole('link', { name: /^View Details/ })).toHaveLength(items.length);
    expect(screen.queryByRole('link', { name: 'Portfolio Comparison' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Calendar/ })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search by Order ID or Customer...')).toHaveAccessibleDescription(/only to loaded orders/);
  });
  it('combines search, status and Analysis, clears search independently and resets every control', async () => {
    setup(sourceFor()); await screen.findByRole('table');
    fireEvent.change(screen.getByLabelText('Order Status'), { target: { value: 'ACCEPTED' } });
    fireEvent.change(screen.getByLabelText('Analysis view'), { target: { value: 'PROFIT' } });
    fireEvent.change(screen.getByLabelText('Search by Order ID or Customer'), { target: { value: 'BOB' } });
    expect(screen.getByRole('link', { name: 'View Details for accepted' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /^View Details/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(screen.getByLabelText('Search by Order ID or Customer')).toHaveValue('');
    expect(screen.getByLabelText('Order Status')).toHaveValue('ACCEPTED');
    expect(screen.getByLabelText('Analysis view')).toHaveValue('PROFIT');
    fireEvent.change(screen.getByLabelText('Search by Order ID or Customer'), { target: { value: 'not found' } });
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(screen.getByLabelText('Search by Order ID or Customer')).toHaveValue('');
    expect(screen.getByLabelText('Order Status')).toHaveValue('ALL');
    expect(screen.getByLabelText('Analysis view')).toHaveValue('QUEUE');
    expect(screen.getAllByRole('link', { name: /^View Details/ })).toHaveLength(items.length);
  });
  it('does not search product text through the Order ID/customer search', async () => {
    setup(sourceFor()); await screen.findByRole('table');
    fireEvent.change(screen.getByLabelText('Search by Order ID or Customer'), { target: { value: 'Bread' } });
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: 'Cake' } });
    expect(screen.getByRole('link', { name: 'View Details for accepted' })).toBeInTheDocument();
  });
  it('supports ID search when customer display text is absent', async () => {
    setup(sourceFor({ items: [{ ...pending, customer: null }], coverage: 'partial' }));
    await screen.findByRole('table');
    fireEvent.change(screen.getByLabelText('Search by Order ID or Customer'), { target: { value: 'ORDER/ONE' } });
    expect(screen.getByRole('link', { name: 'View Details for order/one' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search by Order ID or Customer'), { target: { value: 'Synthetic Alice' } });
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('keeps controls usable without fabricating results while the source is unavailable', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); setup();
    await screen.findByRole('alert');
    fireEvent.change(screen.getByLabelText('Search by Order ID or Customer'), { target: { value: 'demo' } });
    fireEvent.change(screen.getByLabelText('Order Status'), { target: { value: 'ACCEPTED' } });
    fireEvent.change(screen.getByLabelText('Analysis view'), { target: { value: 'FCFS' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Order queue unavailable');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(screen.getByLabelText('Search by Order ID or Customer')).toHaveValue('');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('shows loading before any data', () => {
    setup({ cacheKey: 'pending', load: () => new Promise(() => {}) });
    expect(screen.getByText('Loading order queue…')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('renders supplied pending data, uncertainty and separate MYT timestamps', async () => {
    setup(sourceFor({ items: [pending], coverage: 'partial' }));
    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(screen.getByText('Synthetic Alice')).toBeInTheDocument();
    expect(screen.getByText('24 Oct 2026, 00:30:00 (MYT)')).toBeInTheDocument();
    expect(screen.getByText('24 Oct 2026, 01:00:00 (MYT)')).toBeInTheDocument();
    expect(screen.getByText('UNKNOWN')).toBeInTheDocument();
    expect(screen.getByText('Cost incomplete — expected profit unavailable')).toBeInTheDocument();
    expect(screen.getByText('Request only · no reservation')).toBeInTheDocument();
    expect(screen.getByText('DEMO-ONLY / SYNTHETIC')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^accept$/i })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View Details for order/one' })).toHaveAttribute('href', '/orders/order%2Fone');
  });
  it('keeps accepted, rejected and unknown statuses distinct', async () => {
    setup(sourceFor()); await screen.findByRole('table');
    fireEvent.change(screen.getByRole('combobox', { name: 'Order Status' }), { target: { value: 'ACCEPTED' } });
    expect(screen.getByText('Synthetic Bob')).toBeInTheDocument();
    expect(screen.queryByText('Request only · no reservation')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Order Status' }), { target: { value: 'REJECTED' } });
    expect(screen.getByRole('link', { name: /^View Details/ })).toHaveAttribute('href', '/orders/rejected');
    fireEvent.change(screen.getByRole('combobox', { name: 'Order Status' }), { target: { value: 'OTHER' } });
    expect(screen.getByText('FUTURE_STATE')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Order Status' }), { target: { value: 'PENDING_ACCEPTANCE' } });
    expect(screen.getByRole('link', { name: /^View Details/ })).toHaveAttribute('href', '/orders/order%2Fone');
  });
  it('provides status-specific empty states', async () => {
    setup(sourceFor({ items: [], coverage: 'complete' }));
    expect(await screen.findByText('No orders match')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Order Status' }), { target: { value: 'REJECTED' } });
    expect(screen.getByText('No rejected orders match')).toBeInTheDocument();
  });
  it.each(['Synthetic Alice', 'ORDER/ONE'])('searches %s case-insensitively', async search => {
    setup(sourceFor({ items: [pending], coverage: 'partial' })); await screen.findByRole('table');
    fireEvent.change(screen.getByLabelText('Search by Order ID or Customer'), { target: { value: search } });
    expect(screen.getByRole('link', { name: /^View Details/ })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search by Order ID or Customer'), { target: { value: 'absent' } });
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it.each(['Origin channel', 'Priority', 'Risk', 'Order size'])('filters %s and resets', async label => {
    setup(sourceFor()); await screen.findByRole('table');
    fireEvent.change(screen.getByRole('combobox', { name: 'Order Status' }), { target: { value: 'ALL' } });
    const select = screen.getByLabelText(label);
    const second = within(select).getAllByRole('option')[1] as HTMLOptionElement;
    fireEvent.change(select, { target: { value: second.value } });
    expect(screen.getAllByRole('link', { name: /^View Details/ }).length).toBeLessThan(items.length);
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(select).toHaveValue('');
    expect(screen.getAllByRole('link', { name: /^View Details/ })).toHaveLength(items.length);
  });
  it('combines customer, product and inclusive original-received business dates', async () => {
    setup(sourceFor()); await screen.findByRole('table');
    for (const [label, value] of [['Customer', 'Alice'], ['Product', 'bread'], ['Received from (MYT)', '2026-10-24'], ['Received through (MYT)', '2026-10-24']])
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    expect(screen.getByRole('table')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Received through (MYT)'), { target: { value: '2026-10-23' } });
    expect(screen.getByRole('alert')).toHaveTextContent('must be on or before');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('reports partial coverage without tenant-wide counts', async () => {
    setup(sourceFor()); await screen.findByRole('table');
    expect(screen.getByText(/Partial snapshot: filters apply only to loaded orders/)).toBeInTheDocument();
  });
  it('does not calculate portfolio allocations', async () => {
    setup(sourceFor()); await screen.findByRole('table');
    for (const value of ['FCFS', 'PROFIT', 'EXPIRY']) {
      fireEvent.change(screen.getByLabelText('Analysis view'), { target: { value } });
      expect(screen.getByText(/analysis unavailable: requires a verified backend portfolio/)).toBeInTheDocument();
    }
  });
  it('retries a failed request and only then shows successful data', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(snapshot);
    setup({ cacheKey: 'retry', load });
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByRole('table'); expect(load).toHaveBeenCalledTimes(2);
  });
  it('hides previously loaded data on refresh failure', async () => {
    const load = vi.fn().mockResolvedValueOnce(snapshot).mockRejectedValue(new Error('offline'));
    setup({ cacheKey: 'refresh', load }); await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh queue' }));
    await screen.findByRole('alert'); expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('hides cached rows and source-derived filter options throughout refresh and revoked access', async () => {
    let reject!: (error: Error) => void;
    const load = vi.fn().mockResolvedValueOnce(snapshot).mockImplementation(() => new Promise((_, fail) => { reject = fail; }));
    setup({ cacheKey: 'privacy-refresh', load }); await screen.findByRole('table');
    expect(screen.getByRole('option', { name: 'Telegram' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh queue' }));
    await waitFor(() => expect(screen.queryByRole('table')).not.toBeInTheDocument());
    expect(screen.queryByRole('option', { name: 'Telegram' })).not.toBeInTheDocument();
    expect(screen.queryByText('Synthetic Alice')).not.toBeInTheDocument();
    await act(async () => reject(new ApiError(403, 'FORBIDDEN', 'private')));
    await screen.findByRole('alert'); expect(screen.queryByRole('option', { name: 'Telegram' })).not.toBeInTheDocument();
  });
  it('renders permission failures without leaking error bodies', async () => {
    setup({ cacheKey: 'forbidden', load: vi.fn().mockRejectedValue(new ApiError(403, 'FORBIDDEN', 'private server detail')) });
    expect(await screen.findByRole('alert')).toHaveTextContent('Order queue access unavailable');
    expect(screen.queryByText('private server detail')).not.toBeInTheDocument();
  });
  it('production default remains unavailable and never calls speculative APIs', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); setup();
    expect(await screen.findByRole('alert')).toHaveTextContent('Order queue unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled());
    expect(fetch).not.toHaveBeenCalled(); expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('exposes a labelled native keyboard status select', async () => {
    setup(sourceFor()); await screen.findByRole('table');
    const select = screen.getByRole('combobox', { name: 'Order Status' });
    select.focus(); expect(select).toHaveFocus(); expect(select).toHaveValue('ALL');
    expect(screen.getByRole('region', { name: /scroll horizontally/ })).toHaveAttribute('tabindex', '0');
  });
  it.each(['FEASIBLE', 'CONDITIONAL', 'INFEASIBLE', 'UNEXPECTED'])('safely displays feasibility %s', async value => {
    setup(sourceFor({ items: [{ ...pending, feasibility: value, status: null }], coverage: 'complete' }));
    await screen.findByRole('table');
    fireEvent.change(screen.getByRole('combobox', { name: 'Order Status' }), { target: { value: 'OTHER' } });
    const row = screen.getAllByRole('row')[1];
    expect(within(row).getAllByText(value === 'UNEXPECTED' ? 'UNKNOWN' : value).length).toBeGreaterThan(0);
    expect(within(row).getAllByText('UNKNOWN').length).toBeGreaterThan(0);
  });
  it('does not carry cached orders into a different tenant or actor', async () => {
    const load = vi.fn().mockResolvedValueOnce(snapshot).mockImplementation(() => new Promise(() => {}));
    const source = { cacheKey: 'isolation', load };
    function Harness() {
      const auth = useAuth();
      return <><button onClick={() => auth.setTenantId('tenant-b')}>Switch tenant</button>
        <button onClick={() => auth.setActorId('user_staff_01')}>Switch actor</button><OrderQueuePage source={source} /></>;
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={client}><AuthProvider initialTenantId="tenant-a"><MemoryRouter><Harness /></MemoryRouter></AuthProvider></QueryClientProvider>);
    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: 'Switch tenant' }));
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole('button', { name: 'Switch actor' }));
    await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
    expect(load.mock.calls[2][0]).toMatchObject({ tenantId: 'tenant-b', actorId: 'user_staff_01' });
    expect(screen.queryByText('Synthetic Alice')).not.toBeInTheDocument();
  });
});

describe('presentation boundary', () => {
  it('rejects impossible source dates instead of normalizing them into a valid-looking timestamp', () => {
    expect(timestamp('2026-02-30T01:00:00Z')).toBe('Not available');
    expect(businessDate('2026-02-30T01:00:00Z')).toBe('');
  });
  it('never substitutes zero for missing money or incomplete sources', () => {
    expect(profitText(undefined)).toMatch(/unavailable/);
    expect(profitText({ amount: '12', currency: 'MYR', costComplete: true })).toMatch(/Not verified/);
    expect(profitText({ amount: '0.00', currency: 'MYR', costComplete: true, priceSource: 'quote v1', costSource: 'cost v2' })).toBe('MYR 0.00');
  });
  it('sorts by received time, preserves input, uses stable ID ties and puts missing times last', () => {
    const data = [ { ...pending, id: 'z', receivedAt: null }, { ...pending, id: 'b' }, { ...pending, id: 'a' } ];
    expect(selectOrders(data, initialFilters).map(item => item.id)).toEqual(['a', 'b', 'z']);
    expect(data[0].id).toBe('z');
    expect(businessDate(pending.receivedAt)).toBe('2026-10-24');
    expect(timestamp('2026-10-24T01:00:00')).toBe('Not available');
    expect(selectOrders(data, { ...initialFilters, from: '2026-10-24' })).toHaveLength(2);
  });
  it('reuses shared HTTP headers and maps a DTO without prescribing its shape', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ records: [] }) });
    vi.stubGlobal('fetch', fetch);
    const source = createOrderQueueHttpSource('test-http', '/test-only-contract', (dto: { records: OrderQueueItem[] }) => ({ items: dto.records, coverage: 'complete' }));
    await source.load({ tenantId: 'tenant-x', actorId: 'actor-x' }, new AbortController().signal);
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/test-only-contract'), expect.objectContaining({
      headers: expect.objectContaining({ 'X-Tenant-ID': 'tenant-x', 'X-Actor-ID': 'actor-x' }), signal: expect.any(AbortSignal),
    }));
  });
  it('rejects duplicate IDs rather than silently overwriting rows', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
    const source = createOrderQueueHttpSource('bad-map', '/test-only', () => ({ items: [pending, pending], coverage: 'complete' }));
    await expect(source.load({ tenantId: 'x', actorId: 'y' }, new AbortController().signal)).rejects.toThrow('unique stable IDs');
  });
});
