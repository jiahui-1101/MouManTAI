import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from '../../shared/auth';
import { ApiError } from '../../shared/api';
import { OrderDetailPage } from './OrderDetailPage';
import { OrderQueuePage } from './OrderQueuePage';
import type { OrderDetail } from './detailTypes';
import type { OrderDetailSource } from './detailApi';

// Isolate new panels from legacy API side effects. The existing real-App route suite and P1 suite test the real component.
vi.mock('../context/OrderContextDetail', () => ({ OrderContextDetail: ({ orderId }: { orderId: string }) => <p>Legacy P1 workflow for {orderId}</p> }));
const now = Date.parse('2026-10-24T02:00:00Z');
const fixture = (): OrderDetail => ({
  id: 'order-a', tenantId: 'tenant-test', customer: 'Synthetic Customer', version: '7', status: 'PENDING_ACCEPTANCE',
  receivedAt: '2026-10-23T16:30:00Z', completedAt: '2026-10-24T01:30:00+08:00', originalDeadline: '2026-10-25T04:00:00Z',
  channel: 'Telegram', fulfilment: 'Pickup', location: 'Synthetic location', instructions: 'Keep dry',
  lines: [{ sku: 'SKU-A', product: 'Bread', quantity: { amount: '20', unit: 'pieces' } }],
  messages: [{ id: 'msg-one', text: 'Please prepare 20 pieces', tier: 'DEMO-ONLY / SYNTHETIC', channel: 'Telegram' }],
  fields: ['VALID', 'MISSING', 'AMBIGUOUS', 'CONFLICTING', 'UNVERIFIED'].map(status => ({ name: `field-${status}`, status, value: `value-${status}`, evidence: [{ ref: 'ev-quote', quote: '20 pieces' }] })),
  materials: [{ material: 'Flour', bom: 'BOM v3', required: { amount: '5', unit: 'kg' }, onHand: { amount: '8', unit: 'kg' },
    effective: { amount: '4', unit: 'kg' }, shortage: { amount: '1', unit: 'kg' }, lot: 'LOT-A', location: 'Rack 2', expiresAt: '2026-10-25',
    incoming: [{ quantity: { amount: '2000', unit: 'g' }, status: 'UNCONFIRMED', evidence: ['supplier-claim'] }] }],
  reservations: [{ id: 'RES-ACCEPTED', orderId: 'accepted-order', orderStatus: 'ACCEPTED', verified: true, resource: 'Flour', quantity: { amount: '4', unit: 'kg' } },
    { id: 'PENDING-DEMAND', orderId: 'pending-order', orderStatus: 'PENDING_ACCEPTANCE' }],
  capacities: [{ resource: 'Oven', workload: { amount: '2', unit: 'hours' }, available: { amount: '1', unit: 'hours' },
    conflicts: ['Production window overlaps accepted workload'], bottlenecks: ['One oven'], assumptions: ['Setup time included'] }],
  assessment: { id: 'assessment-a', version: '2', orderVersion: '7', status: 'CONDITIONAL', snapshotId: 'snapshot-a',
    snapshotAt: '2026-10-24T01:00:00Z', freshness: 'CURRENT', sourceVerified: true, complete: true,
    recommendation: 'Review supply condition', conditions: ['Verify flour receipt'], blockers: ['Insufficient confirmed flour'],
    constraints: ['Do not use expired lots'], reasons: ['Shortage reported'], evidence: ['ev-bom'], missingEvidence: ['confirmed receipt'] },
  pricing: { access: 'AUTHORIZED', sourceVerified: true, currency: 'MYR', customerPrice: '120', quotedPrice: '125',
    quoteVersion: 'quote-v4', priceSource: 'Approved SKU list v2', disclosed: 'DISCLOSED', agreed: 'UNKNOWN',
    costComplete: false, profit: '100', costSource: 'valuation v2', costs: [{ component: 'Materials', amount: '20', source: 'BOM v3' }], missingCosts: ['Labour', 'Delivery'] },
});
const sourceFor = (data: OrderDetail | null = fixture()): OrderDetailSource => ({ cacheKey: 'test-fixture', load: vi.fn().mockResolvedValue(data) });
function setup(source: OrderDetailSource = sourceFor()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><AuthProvider initialTenantId="tenant-test"><MemoryRouter initialEntries={['/orders/order-a']}>
    <Routes><Route path="/orders/:id" element={<OrderDetailPage source={source} />} /></Routes>
  </MemoryRouter></AuthProvider></QueryClientProvider>);
}
beforeEach(() => vi.spyOn(Date, 'now').mockReturnValue(now));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function materialRow() { fireEvent.click(screen.getByRole('tab', { name: 'Feasibility' })); return screen.getByRole('row', { name: /Flour/ }); }
function assessmentPanel() { fireEvent.click(screen.getByRole('tab', { name: 'Feasibility' })); return screen.getByRole('region', { name: 'Feasibility assessment' }); }

describe('Order detail and resource assessment', () => {
  it('withholds positive feasibility when a supposedly current source contains an impossible snapshot date', async () => {
    const detail = fixture(); detail.assessment!.status = 'FEASIBLE'; detail.assessment!.snapshotAt = '2026-02-30T01:00:00Z';
    setup(sourceFor(detail)); fireEvent.click(screen.getByRole('tab', { name: 'Feasibility' })); const panel = await screen.findByRole('region', { name: 'Feasibility assessment' });
    expect(within(panel).getByText('UNKNOWN')).toBeInTheDocument();
  });
  it('withholds cached identity, pricing, assessment and decisions during refresh and on permission failure', async () => {
    let reject!: (error: Error) => void;
    const source = sourceFor(); vi.mocked(source.load).mockResolvedValueOnce(fixture()).mockImplementation(() => new Promise((_, fail) => { reject = fail; }));
    setup(source); await screen.findByText('Synthetic Customer');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh order assessment view' }));
    await waitFor(() => expect(screen.queryByText('Synthetic Customer')).not.toBeInTheDocument());
    expect(screen.queryByText('Approved SKU list v2')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Order Decision workspace' })).not.toBeInTheDocument();
    expect(screen.getByText('Legacy P1 workflow for order-a')).toBeInTheDocument();
    await act(async () => reject(new ApiError(403, 'FORBIDDEN', 'private')));
    await screen.findByRole('heading', { name: 'Order detail access unavailable' });
    expect(screen.queryByText('Synthetic Customer')).not.toBeInTheDocument();
  });
  it('loads an injected source with identity, summary and distinct original timestamps', async () => {
    setup(); expect(await screen.findByText('Synthetic Customer')).toBeInTheDocument();
    expect(screen.getByText('24 Oct 2026, 00:30:00 (MYT)')).toBeInTheDocument();
    expect(screen.getByText('24 Oct 2026, 01:30:00 (MYT)')).toBeInTheDocument();
    expect(screen.getByText(/SKU: SKU-A/)).toHaveTextContent('20 pieces');
    expect(screen.getByText('Legacy P1 workflow for order-a')).toBeInTheDocument();
  });
  it('links original messages to escaped internal evidence anchors and preserves all source field statuses', async () => {
    setup(); const link = await screen.findByRole('link', { name: 'Read original message msg-one' });
    expect(link).toHaveAttribute('href', '#order-message-msg-one');
    expect(screen.getByText('Please prepare 20 pieces')).toBeInTheDocument();
    for (const state of ['VALID', 'MISSING', 'AMBIGUOUS', 'CONFLICTING', 'UNVERIFIED']) expect(screen.getByRole('row', { name: new RegExp(`field-${state}`) })).toHaveTextContent(state);
  });
  it('shows BOM, locations, expiry, incompatible units and unconfirmed incoming separately', async () => {
    setup(); await screen.findByText('Synthetic Customer');
    expect(materialRow()).toHaveTextContent('Required: 5 kg');
    expect(screen.getByText(/Location: Rack 2/)).toBeInTheDocument();
    expect(screen.getByText(/2026-10-25 \(date only; cutoff unknown\)/)).toBeInTheDocument();
    expect(screen.getByText(/2000 g · UNCONFIRMED/)).toBeInTheDocument();
    expect(screen.getByText(/Stock on hand: 8 kg/)).toBeInTheDocument();
  });
  it.each([
    '2026-02-30', '2026-02-29', '1900-02-29', '2026-04-31',
    '2026-00-10', '2026-13-10', '2026-01-00', '2026-01-32',
    '0000-01-01', '2026-2-03', '2026-10-25 ', 'not-a-date',
    '2026-02-30T01:00:00Z', '2026-10-25T01:00:00',
  ])('withholds invalid material expiry %s without normalizing it into a valid date', async expiresAt => {
    const data = fixture(); data.materials![0].expiresAt = expiresAt;
    const before = structuredClone(data); setup(sourceFor(data));
    await screen.findByText('Synthetic Customer');
    const row = materialRow();
    expect(within(row).getByText('Expiry: Not available')).toBeInTheDocument();
    expect(row).not.toHaveTextContent('date only; cutoff unknown');
    expect(row).not.toHaveTextContent(expiresAt);
    expect(row).toHaveTextContent('Required: 5 kg');
    expect(row).toHaveTextContent('Location: Rack 2');
    expect(row).toHaveTextContent('2000 g · UNCONFIRMED');
    expect(data).toEqual(before);
  });
  it.each(['2024-02-29', '2000-02-29', '2026-02-28', '2026-12-31'])('preserves valid date-only material expiry %s without assigning a timezone or cutoff', async expiresAt => {
    const data = fixture(); data.materials![0].expiresAt = expiresAt;
    const before = structuredClone(data); setup(sourceFor(data));
    await screen.findByText('Synthetic Customer');
    const row = materialRow();
    expect(within(row).getByText(`Expiry: ${expiresAt} (date only; cutoff unknown)`)).toBeInTheDocument();
    expect(data).toEqual(before);
  });
  it.each([undefined, null, ''])('keeps absent material expiry %s unavailable', async expiresAt => {
    const data = fixture(); data.materials![0].expiresAt = expiresAt; setup(sourceFor(data));
    await screen.findByText('Synthetic Customer');
    expect(within(materialRow()).getByText('Expiry: Not available')).toBeInTheDocument();
  });
  it.each([
    ['2026-10-24T16:30:00Z', '25 Oct 2026, 00:30:00 (MYT)'],
    ['2026-10-25T00:30:00+08:00', '25 Oct 2026, 00:30:00 (MYT)'],
    ['2024-02-29T23:30:00-05:00', '01 Mar 2024, 12:30:00 (MYT)'],
  ])('preserves offset-aware material expiry handling for %s', async (expiresAt, expected) => {
    const data = fixture(); data.materials![0].expiresAt = expiresAt;
    const before = structuredClone(data); setup(sourceFor(data));
    await screen.findByText('Synthetic Customer');
    expect(within(materialRow()).getByText(`Expiry: ${expected}`)).toBeInTheDocument();
    expect(data).toEqual(before);
  });
  it('distinguishes accepted reservations from pending demand and renders capacity conflicts', async () => {
    setup(); await screen.findByText('Synthetic Customer');
    expect(screen.getByText('Accepted reservation')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Feasibility' }));
    const pending = screen.getByRole('link', { name: 'pending-order' }).closest('li')!;
    expect(pending).toHaveTextContent('Reported demand — reservation not verified');
    expect(screen.getByText('Production window overlaps accepted workload')).toBeInTheDocument();
    expect(screen.getByText('One oven')).toBeInTheDocument();
  });
  it('never treats lifecycle acceptance alone or pending demand as verified reservation', async () => {
    const data = fixture(); data.reservations![0].verified = false; data.reservations![1].verified = true;
    setup(sourceFor(data)); await screen.findByText('Synthetic Customer');
    expect(screen.queryByText('Accepted reservation')).not.toBeInTheDocument();
    expect(screen.getAllByText('Reported demand — reservation not verified')).toHaveLength(2);
  });
  it.each(['FEASIBLE', 'CONDITIONAL', 'INFEASIBLE', 'UNKNOWN'])('renders backend %s with explicit evidence and no command', async status => {
    const data = fixture(); data.assessment!.status = status; setup(sourceFor(data)); await screen.findByText('Synthetic Customer');
    const section = assessmentPanel();
    expect(within(section).getAllByText(status).length).toBeGreaterThan(0);
    expect(screen.getByText('Verify flour receipt')).toBeInTheDocument();
    expect(screen.getByText('Do not use expired lots')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Accept|^Reject|^Reserve/ })).not.toBeInTheDocument();
  });
  it.each(['stale', 'unknown-freshness', 'unverified', 'incomplete', 'wrong-version', 'unknown-version', 'unknown-offset', 'future', 'missing-snapshot'])('suppresses positive badges when %s', async condition => {
    const data = fixture(); const a = data.assessment!; a.status = 'FEASIBLE';
    if (condition === 'stale') a.freshness = 'STALE';
    if (condition === 'unknown-freshness') a.freshness = 'UNKNOWN';
    if (condition === 'unverified') a.sourceVerified = false;
    if (condition === 'incomplete') a.complete = false;
    if (condition === 'wrong-version') a.orderVersion = '6';
    if (condition === 'unknown-version') data.version = null;
    if (condition === 'unknown-offset') a.snapshotAt = '2026-10-24T01:00:00';
    if (condition === 'future') a.snapshotAt = '2026-10-25T01:00:00Z';
    if (condition === 'missing-snapshot') a.snapshotId = null;
    setup(sourceFor(data)); await screen.findByText('Synthetic Customer');
    const section = assessmentPanel();
    expect(section.querySelector('.badge-success')).toBeNull();
    expect(section.querySelector('.badge-unknown')).toHaveTextContent('UNKNOWN');
  });
  it('shows snapshot age, evidence and stale recommendation limitations', async () => {
    const data = fixture(); data.assessment!.freshness = 'STALE'; setup(sourceFor(data));
    expect(await screen.findByText('60 minute(s) at last display refresh')).toBeInTheDocument();
    expect(screen.getByText('ev-bom')).toBeInTheDocument();
    expect(screen.getByText(/Do not treat this recommendation as approval/)).toBeInTheDocument();
  });
  it('shows price provenance and missing costs without displaying fabricated profit', async () => {
    setup(); await screen.findByText('Synthetic Customer');
    expect(screen.getByText('Approved SKU list v2')).toBeInTheDocument(); expect(screen.getByText('quote-v4')).toBeInTheDocument();
    expect(screen.getByText('Labour')).toBeInTheDocument(); expect(screen.getByText('Delivery')).toBeInTheDocument();
    expect(screen.getByText('Not verified / cost incomplete — expected profit unavailable')).toBeInTheDocument();
    expect(screen.queryByText('MYR 0')).not.toBeInTheDocument(); expect(screen.queryByText('MYR 100')).not.toBeInTheDocument();
  });
  it('hides all amounts and financial sources when redacted even if values are supplied', async () => {
    const data = fixture(); data.pricing!.access = 'REDACTED'; setup(sourceFor(data));
    expect(await screen.findByText('Financial data redacted by source authorization.')).toBeInTheDocument();
    expect(screen.queryByText('MYR 125')).not.toBeInTheDocument(); expect(screen.queryByText('quote-v4')).not.toBeInTheDocument();
  });
  it('handles missing resources, finances and assessment without a fake ready state', async () => {
    setup(sourceFor({ id: 'order-a', tenantId: 'tenant-test' }));
    expect(await screen.findByText(/Pending-order assessment API unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Material availability cannot be verified/)).toBeInTheDocument();
    expect(screen.getByText(/Expected profit unknown/)).toBeInTheDocument();
    expect(screen.getByText(/UNKNOWN — no authoritative lifecycle/)).toBeInTheDocument();
  });
  it('supports loading, empty and retry states', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(null);
    setup({ cacheKey: 'retry', load });
    expect(await screen.findByRole('status', { name: 'Order assessment source state' })).toHaveTextContent('Order detail unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry order detail' }));
    expect(await screen.findByText('No order detail available')).toBeInTheDocument(); expect(load).toHaveBeenCalledTimes(2);
  });
  it('retains legacy workflow while the new source is loading', () => {
    setup({ cacheKey: 'loading', load: () => new Promise(() => {}) });
    expect(screen.getByText('Loading order detail…')).toBeInTheDocument(); expect(screen.getByText(/Legacy P1 workflow/)).toBeInTheDocument();
  });
  it('handles permission errors without rendering supplied error bodies', async () => {
    setup({ cacheKey: 'denied', load: vi.fn().mockRejectedValue(new ApiError(403, 'FORBIDDEN', 'private debug')) });
    expect(await screen.findByRole('status', { name: 'Order assessment source state' })).toHaveTextContent('Order detail access unavailable');
    expect(screen.queryByText('private debug')).not.toBeInTheDocument();
  });
  it.each(['tenant', 'order'])('rejects mismatched %s identity', async kind => {
    const data = fixture(); if (kind === 'tenant') data.tenantId = 'other'; else data.id = 'other';
    setup(sourceFor(data)); expect(await screen.findByRole('status', { name: 'Order assessment source state' })).toBeInTheDocument();
    expect(screen.queryByText('Synthetic Customer')).not.toBeInTheDocument();
  });
  it('hides old assessment after refresh failure', async () => {
    const load = vi.fn().mockResolvedValueOnce(fixture()).mockRejectedValue(new Error('offline'));
    setup({ cacheKey: 'stale-cache', load }); await screen.findByText('Synthetic Customer');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh order assessment view' }));
    await screen.findByRole('status', { name: 'Order assessment source state' }); expect(screen.queryByText('Synthetic Customer')).not.toBeInTheDocument();
  });
  it('supports queue-to-detail navigation without changing the order ID', async () => {
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><AuthProvider initialTenantId="tenant-test"><MemoryRouter initialEntries={['/orders']}><Routes>
      <Route path="/orders" element={<OrderQueuePage source={{ cacheKey: 'queue-test', load: async () => ({ items: [{ id: 'order-a', status: 'PENDING_ACCEPTANCE', evidenceTier: 'SYNTHETIC' }], coverage: 'complete' }) }} />} />
      <Route path="/orders/:id" element={<OrderDetailPage source={sourceFor()} />} /></Routes></MemoryRouter></AuthProvider></QueryClientProvider>);
    fireEvent.click(await screen.findByRole('link', { name: 'View Details for order-a' }));
    expect(await screen.findByText('Synthetic Customer')).toBeInTheDocument();
  });
  it('isolates queries by actor, tenant and order and keeps controls keyboard-focusable', async () => {
    const load = vi.fn().mockResolvedValueOnce(fixture()).mockImplementation(() => new Promise(() => {}));
    function Harness() { const auth = useAuth(); return <><button onClick={() => auth.setTenantId('next-tenant')}>Switch tenant</button>
      <button onClick={() => auth.setActorId('user_staff_01')}>Switch actor</button><OrderDetailPage orderId="order-a" source={{ cacheKey: 'tenant-scope', load }} /></>; }
    render(<QueryClientProvider client={new QueryClient()}><AuthProvider initialTenantId="tenant-test"><MemoryRouter><Harness /></MemoryRouter></AuthProvider></QueryClientProvider>);
    await screen.findByText('Synthetic Customer'); const back = screen.getByRole('link', { name: 'Back to Order Queue' });
    back.focus(); expect(back).toHaveFocus(); fireEvent.click(screen.getByRole('button', { name: 'Switch tenant' }));
    expect(screen.queryByText('Synthetic Customer')).not.toBeInTheDocument();
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2)); fireEvent.click(screen.getByRole('button', { name: 'Switch actor' }));
    await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
    expect(load.mock.calls[2][1]).toMatchObject({ tenantId: 'next-tenant', actorId: 'user_staff_01' });
  });
});
