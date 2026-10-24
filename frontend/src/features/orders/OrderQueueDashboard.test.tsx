import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, Link, RouterProvider } from 'react-router-dom';
import { AuthProvider, useAuth } from '../../shared/auth';
import { ApiError } from '../../shared/api';
import { OrderQueuePage } from './OrderQueuePage';
import type { OrderQueueSource } from './api';
import type { OrderQueueItem, OrderQueueSnapshot } from './types';
import { initialFilters, selectOrders } from './queue';

const orders: OrderQueueItem[] = [
  { id: 'source-order-late', customer: 'Synthetic buyer A', status: 'PENDING_ACCEPTANCE', receivedAt: '2026-10-21T01:00:00Z', deadline: '2026-10-30T01:00:00Z', risk: 'Source high concern', priority: 'Important', feasibility: 'CONDITIONAL', evidenceTier: 'SYNTHETIC' },
  { id: 'source-order-early', customer: 'Synthetic buyer B', status: 'ACCEPTED', receivedAt: '2026-10-22T01:00:00Z', deadline: '2026-10-25T01:00:00Z', risk: 'Source review required', feasibility: 'FEASIBLE', evidenceTier: 'SYNTHETIC' },
  { id: 'source-order-unknown', status: 'REJECTED', receivedAt: null, deadline: null, risk: null, feasibility: null, evidenceTier: 'SYNTHETIC' },
];
const complete: OrderQueueSnapshot = { items: orders, coverage: 'complete', asOf: '2026-10-24T00:00:00Z' };
const sourceFor = (data = complete): OrderQueueSource => ({ cacheKey: 'dashboard-test-only', load: vi.fn().mockResolvedValue(data) });
function IdentityControls() {
  const auth = useAuth();
  return <><button onClick={() => auth.setTenantId('other-tenant')}>Switch tenant</button><button onClick={() => auth.setActorId('user_staff_01')}>Switch actor</button></>;
}
function setup(source: OrderQueueSource = sourceFor(), url = '/orders') {
  const page = <><IdentityControls /><Link to="/away">Away</Link><OrderQueuePage source={source} /></>;
  const router = createMemoryRouter([
    { path: '/orders', element: page }, { path: '/orders/pending', element: page },
    { path: '/away', element: <Link to="/orders">Return to Queue</Link> },
  ], { initialEntries: [url] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><AuthProvider><RouterProvider router={router} /></AuthProvider></QueryClientProvider>);
  return router;
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const ids = () => screen.getAllByRole('link', { name: /^View Details for/ }).map(link => link.getAttribute('aria-label'));
const metric = (name: string) => screen.getByTestId(`oq-kpi-${name}`);

it('renders the Orders header, six source-derived cards and a real Refresh action', async () => {
  const source = sourceFor(); setup(source); await screen.findByRole('table');
  expect(screen.getByRole('heading', { level: 1, name: 'Orders' })).toBeInTheDocument();
  expect(screen.getByText('Manage, evaluate and prioritize customer orders.')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Order Decision Queue' })).toBeInTheDocument();
  expect(metric('total')).toHaveTextContent('3');
  for (const name of ['pending', 'accepted', 'rejected']) expect(metric(name)).toHaveTextContent('1');
  for (const name of ['risk', 'missing']) expect(metric(name)).toHaveTextContent('—');
  expect(screen.queryByRole('button', { name: 'Filter High Risk' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Filter Missing Information' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh queue' }));
  await screen.findByRole('table'); expect(source.load).toHaveBeenCalledTimes(2);
});

it.each([
  ['Pending Acceptance', 'PENDING_ACCEPTANCE', 'source-order-late'],
  ['Accepted', 'ACCEPTED', 'source-order-early'], ['Rejected', 'REJECTED', 'source-order-unknown'],
])('filters %s via the KPI without changing snapshot counts', async (label, status, id) => {
  setup(); await screen.findByRole('table');
  fireEvent.click(screen.getByRole('button', { name: `Filter ${label}` }));
  expect(screen.getByLabelText('Order Status')).toHaveValue(status);
  expect(ids()).toEqual([`View Details for ${id}`]);
  expect(metric('total')).toHaveTextContent('3');
  expect(screen.getByRole('button', { name: `Filter ${label}` })).toHaveAttribute('aria-pressed', 'true');
});

it('does not turn partial snapshot sizes into tenant KPIs', async () => {
  setup(sourceFor({ ...complete, coverage: 'partial' })); await screen.findByRole('table');
  for (const key of ['total', 'pending', 'accepted', 'rejected', 'risk', 'missing']) expect(metric(key)).toHaveTextContent('—');
  expect(screen.getByText('3 loaded · tenant total unavailable')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Filter / })).not.toBeInTheDocument();
});

it('does not count absent or future lifecycle states as confirmed zero', async () => {
  setup(sourceFor({ ...complete, items: [{ ...orders[0], status: null }, { ...orders[1], status: 'FUTURE' }] }));
  await screen.findByRole('table');
  expect(metric('total')).toHaveTextContent('2');
  for (const key of ['pending', 'accepted', 'rejected']) expect(metric(key)).toHaveTextContent('—');
});

it('shows zero only for a source-confirmed empty collection and distinguishes it from no matches', async () => {
  setup(sourceFor({ items: [], coverage: 'complete' }));
  await screen.findByRole('heading', { name: 'No orders yet' });
  for (const key of ['total', 'pending', 'accepted', 'rejected']) expect(metric(key)).toHaveTextContent('0');
  expect(screen.getByText('The source confirms this order snapshot is empty.')).toBeInTheDocument();
  expect(metric('missing')).toHaveTextContent('—');
});

it('distinguishes no matches from a confirmed empty source', async () => {
  setup(); await screen.findByRole('table'); change('Search by Order ID or Customer', 'no-such-id');
  expect(screen.getByRole('heading', { name: 'No orders match your filters.' })).toBeInTheDocument();
  expect(metric('total')).toHaveTextContent('3');
  expect(screen.queryByRole('heading', { name: 'No orders yet' })).not.toBeInTheDocument();
});

it('withholds rows and KPI numbers throughout loading and revoked authorization', async () => {
  let reject!: (value: Error) => void;
  const source = { cacheKey: 'loading-test-only', load: vi.fn().mockResolvedValueOnce(complete).mockImplementation(() => new Promise((_, fail) => { reject = fail; })) };
  setup(source); await screen.findByRole('table');
  fireEvent.click(screen.getByRole('button', { name: 'Refresh queue' }));
  expect(await screen.findByText('Loading order queue…')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Refresh queue' })).toBeDisabled();
  expect(metric('total')).toHaveTextContent('—');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  await act(async () => reject(new ApiError(403, 'FORBIDDEN', 'private response')));
  expect(await screen.findByRole('alert')).toHaveTextContent('Order queue access unavailable');
  expect(metric('total')).toHaveTextContent('—');
  expect(screen.queryByText('private response')).not.toBeInTheDocument();
});

it('has truthful default unavailable cards and no operational mutations or restored shortcuts', async () => {
  const { unavailableOrderQueueSource } = await import('./api'); setup(unavailableOrderQueueSource);
  expect(await screen.findByRole('alert')).toHaveTextContent('Order data is currently unavailable.');
  expect(metric('total')).toHaveTextContent('—');
  expect(screen.queryByRole('link', { name: /Portfolio|Calendar/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^(Accept|Reject|Add Order)$/i })).not.toBeInTheDocument();
  expect(screen.getByLabelText('Risk Level')).toBeDisabled();
});

it('sorts source deadlines without guessing priority, risk scores or hidden profit', async () => {
  setup(); await screen.findByRole('table');
  expect(ids()[0]).toBe('View Details for source-order-late');
  change('Sort By', 'DEADLINE');
  expect(ids()).toEqual(['View Details for source-order-early', 'View Details for source-order-late', 'View Details for source-order-unknown']);
  for (const name of [/Highest Priority/, /Highest Risk/, /Estimated Profit/]) expect(screen.getByRole('option', { name })).toBeDisabled();
  expect(screen.getByText(/Unknown times appear last. No allocation calculated/)).toBeInTheDocument();
});

it('uses stable ID ties and puts invalid or absent deadlines last without modifying input', () => {
  const rows = [{ ...orders[0], id: 'z', deadline: '2026-02-30T00:00:00Z' }, { ...orders[1], id: 'b' }, { ...orders[1], id: 'a' }];
  expect(selectOrders(rows, { ...initialFilters, sort: 'DEADLINE' }).map(row => row.id)).toEqual(['a', 'b', 'z']);
  expect(rows[0].id).toBe('z');
});

it('exposes advanced source-based filters and composes them with search, risk and Analysis', async () => {
  setup(); await screen.findByRole('table');
  const advanced = screen.getByText('Advanced Filters').closest('details')!;
  expect(advanced).not.toHaveAttribute('open'); fireEvent.click(screen.getByText('Advanced Filters'));
  change('Deadline from (MYT)', '2026-10-25'); change('Deadline through (MYT)', '2026-10-25');
  change('Feasibility Status', 'FEASIBLE'); change('Risk Level', 'Source review required');
  change('Search by Order ID or Customer', 'buyer b'); change('Analysis view', 'PROFIT');
  expect(ids()).toEqual(['View Details for source-order-early']);
  expect(screen.getByText(/Quantity range is unavailable/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
  expect(screen.getByLabelText('Deadline from (MYT)')).toHaveValue('');
  expect(screen.getByLabelText('Deadline through (MYT)')).toHaveValue('');
  expect(screen.getByLabelText('Feasibility Status')).toHaveValue('');
  expect(screen.getByLabelText('Risk Level')).toHaveValue('');
  expect(screen.getByLabelText('Sort By')).toHaveValue('FCFS');
  expect(screen.getByLabelText('Analysis view')).toHaveValue('QUEUE');
  expect(ids()).toHaveLength(3);
});

it('preserves sort and advanced URL preferences across navigation and resets them on identity changes', async () => {
  const router = setup(); await screen.findByRole('table');
  change('Sort By', 'DEADLINE');
  fireEvent.click(screen.getByText('Advanced Filters')); change('Deadline from (MYT)', '2026-10-24'); change('Feasibility Status', 'CONDITIONAL');
  const stale = `/orders${router.state.location.search}`;
  expect(stale).toContain('oqSort=DEADLINE'); expect(stale).toContain('oqDueFrom=2026-10-24');
  fireEvent.click(screen.getByRole('link', { name: 'Away' }));
  await act(() => router.navigate(-1));
  expect(screen.getByLabelText('Sort By')).toHaveValue('DEADLINE');
  expect(screen.getByLabelText('Deadline from (MYT)')).toHaveValue('2026-10-24');
  fireEvent.click(screen.getByRole('button', { name: 'Switch actor' }));
  expect(screen.getByLabelText('Sort By')).toHaveValue('FCFS');
  await act(() => router.navigate(stale));
  expect(screen.getByLabelText('Feasibility Status')).toHaveValue('');
  expect(screen.getByLabelText('Deadline from (MYT)')).toHaveValue('');
  fireEvent.click(screen.getByRole('button', { name: 'Switch tenant' }));
  expect(screen.getByLabelText('Sort By')).toHaveValue('FCFS');
});

it.each([
  ['oqSort=DEADLINE&oqDueFrom=2024-02-29&oqFeasibility=UNKNOWN', 'DEADLINE', '2024-02-29', 'UNKNOWN'],
  ['oqSort=PROFIT&oqDueFrom=2026-02-29&oqDueTo=2026-13-01&oqFeasibility=SAFE', 'FCFS', '', ''],
  ['oqSort=DEADLINE&oqSort=FCFS&oqDueFrom=2024-02-29&oqDueFrom=2024-03-01&oqFeasibility=FEASIBLE&oqFeasibility=UNKNOWN', 'FCFS', '', ''],
])('validates sort/date/feasibility deep links: %s', (search, sort, date, feasibility) => {
  setup(sourceFor(), `/orders?${search}`);
  expect(screen.getByLabelText('Sort By')).toHaveValue(sort);
  expect(screen.getByLabelText('Deadline from (MYT)')).toHaveValue(date);
  expect(screen.getByLabelText('Feasibility Status')).toHaveValue(feasibility);
});

it('withholds results for a reversed deadline range without silently broadening it', async () => {
  setup(sourceFor(), '/orders?oqDueFrom=2026-10-30&oqDueTo=2026-10-25');
  expect(await screen.findByRole('alert')).toHaveTextContent('Deadline from must be on or before');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

it('retains hidden Pending semantics and source order IDs with an accessible horizontal table region', async () => {
  setup(sourceFor(), '/orders/pending?oqStatus=ACCEPTED');
  await screen.findByRole('table');
  expect(ids()).toEqual(['View Details for source-order-late']);
  expect(screen.getByRole('link', { name: 'View Details for source-order-late' })).toHaveAttribute('href', '/orders/source-order-late');
  expect(screen.getByRole('region', { name: /scroll horizontally/ })).toHaveAttribute('tabindex', '0');
  expect(within(screen.getByRole('table')).getAllByRole('columnheader')).toHaveLength(7);
});
