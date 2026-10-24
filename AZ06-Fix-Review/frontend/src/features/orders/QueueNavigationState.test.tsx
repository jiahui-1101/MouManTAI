import { afterEach, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, Link, Outlet, RouterProvider } from 'react-router-dom';
import { AuthProvider, useAuth } from '../../shared/auth';
import { operationalApi } from '../context/operationalApi';
import { OrderQueuePage } from './OrderQueuePage';
import { OrderDetailPage } from './OrderDetailPage';
import { PortfolioComparisonPage } from './PortfolioComparisonPage';
import { CalendarSchedulingPage } from './CalendarSchedulingPage';
import type { OrderQueueSource } from './api';
import { App } from '../../App';
import { orderPlanningRoutes } from './portfolioRoutes';

// Explicit test source only. Production queue availability/authorization is unchanged.
const source: OrderQueueSource = { cacheKey: 'az06-test', load: async () => ({ coverage: 'complete', items: [{
  id: 'synthetic-order', status: 'PENDING_ACCEPTANCE', customer: 'Synthetic customer',
  receivedAt: '2026-10-24T00:00:00Z', lines: [{ product: 'Synthetic bread' }],
  channel: 'Telegram', priority: 'High', risk: 'Unknown', size: 'Small', evidenceTier: 'SYNTHETIC',
}] }) };
function Controls() {
  const auth = useAuth();
  return <><button onClick={() => auth.setTenantId('tenant-b')}>Tenant B</button>
    <button onClick={() => auth.setTenantId('tenant-a')}>Tenant A</button>
    <button onClick={() => auth.setActorId('user_staff_01')}>Actor staff</button>
    <button onClick={() => auth.setActorId('user_owner_01')}>Actor owner</button>
    <Link to="/orders">Queue navigation</Link><Outlet /></>;
}
function setup(entries = ['/orders']) {
  const router = createMemoryRouter([{ element: <Controls />, children: [
    { path: '/orders', element: <OrderQueuePage source={source} /> },
    { path: '/orders/portfolio', element: <PortfolioComparisonPage /> },
    { path: '/orders/calendar', element: <CalendarSchedulingPage /> },
    { path: '/orders/:id', element: <OrderDetailPage /> },
    { path: '/sentinel', element: <p>Earlier history entry</p> },
  ] }], { initialEntries: entries, initialIndex: entries.length - 1 });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><AuthProvider initialTenantId="tenant-a" initialActorId="user_owner_01">
    <RouterProvider router={router} /></AuthProvider></QueryClientProvider>);
  return router;
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.history.replaceState({}, '', '/'); });
const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
function fillAll() {
  click('All statuses');
  for (const [label, value] of [
    ['Search order, customer or product', 'synthetic'], ['Customer', 'customer'], ['Product', 'bread'],
    ['Received from (MYT)', '2026-10-23'], ['Received through (MYT)', '2026-10-25'],
    ['Origin channel', 'Telegram'], ['Priority', 'High'], ['Risk', 'Unknown'], ['Order size', 'Small'],
    ['Analysis view', 'PROFIT'],
  ]) change(label, value);
}
function expectAll() {
  expect(screen.getByRole('button', { name: 'All statuses' })).toHaveAttribute('aria-pressed', 'true');
  for (const [label, value] of [
    ['Search order, customer or product', 'synthetic'], ['Customer', 'customer'], ['Product', 'bread'],
    ['Received from (MYT)', '2026-10-23'], ['Received through (MYT)', '2026-10-25'],
    ['Origin channel', 'Telegram'], ['Priority', 'High'], ['Risk', 'Unknown'], ['Order size', 'Small'],
    ['Analysis view', 'PROFIT'],
  ]) expect(screen.getByLabelText(label)).toHaveValue(value);
}
function expectDefaults(analysis = 'QUEUE') {
  expect(screen.getByRole('button', { name: 'Pending acceptance' })).toHaveAttribute('aria-pressed', 'true');
  for (const label of ['Search order, customer or product', 'Customer', 'Product', 'Received from (MYT)',
    'Received through (MYT)', 'Origin channel', 'Priority', 'Risk', 'Order size'])
    expect(screen.getByLabelText(label)).toHaveValue('');
  expect(screen.getByLabelText('Analysis view')).toHaveValue(analysis);
}

it.each([
  ['Portfolio Comparison', 'Back to Order Decision Queue'],
  ['Production & Delivery Calendar', 'Order Decision Queue'],
  ['View Details for synthetic-order', 'Back to Order Queue'],
])('preserves all ten fields and Analysis through the actual %s page and its return link', async (destination, back) => {
  vi.spyOn(operationalApi, 'getContextByOrder').mockRejectedValue(new Error('test source unavailable'));
  const router = setup(); await screen.findByRole('table'); fillAll();
  const search = router.state.location.search;
  expect(search).not.toMatch(/synthetic|customer|bread|Telegram|High|Unknown|Small|tenant-a|user_owner/);
  fireEvent.click(screen.getByRole('link', { name: destination }));
  fireEvent.click(await screen.findByRole('link', { name: back }));
  await screen.findByRole('table'); expectAll();
  expect(router.state.location.search).toBe(search);
});

it('restores separate visits on browser Back/Forward without rewriting their private text snapshots', async () => {
  const router = setup(); await screen.findByRole('table');
  click('Accepted'); change('Customer', 'first private value'); change('Analysis view', 'FCFS');
  const first = router.state.location.search;
  fireEvent.click(screen.getByRole('link', { name: 'Portfolio Comparison' }));
  fireEvent.click(await screen.findByRole('link', { name: 'Back to Order Decision Queue' }));
  click('Rejected'); change('Customer', 'second private value'); change('Analysis view', 'EXPIRY');
  const second = router.state.location.search;
  fireEvent.click(screen.getByRole('link', { name: 'Portfolio Comparison' }));
  await act(() => router.navigate(-1));
  expect(screen.getByLabelText('Customer')).toHaveValue('second private value');
  expect(router.state.location.search).toBe(second);
  await act(() => router.navigate(-2));
  expect(screen.getByLabelText('Customer')).toHaveValue('first private value');
  expect(screen.getByLabelText('Analysis view')).toHaveValue('FCFS');
  expect(screen.getByRole('button', { name: 'Accepted' })).toHaveAttribute('aria-pressed', 'true');
  expect(router.state.location.search).toBe(first);
  await act(() => router.navigate(2));
  expect(screen.getByLabelText('Customer')).toHaveValue('second private value');
  expect(screen.getByLabelText('Analysis view')).toHaveValue('EXPIRY');
  expect(screen.getByRole('button', { name: 'Rejected' })).toHaveAttribute('aria-pressed', 'true');
});

it.each(['Tenant B', 'Actor staff'])('resets immediately on %s and refuses stale history and URLs, including after switching back', async identity => {
  const router = setup(); await screen.findByRole('table'); fillAll();
  const stale = `/orders${router.state.location.search}`;
  click(identity); expectDefaults();
  await waitFor(() => expect(router.state.location.search).not.toContain('oqAnalysis'));
  await act(() => router.navigate(stale)); expectDefaults();
  click(identity === 'Tenant B' ? 'Tenant A' : 'Actor owner'); expectDefaults();
  await act(() => router.navigate(-1)); expectDefaults();
  await act(() => router.navigate(1)); expectDefaults();
  await act(() => router.navigate(stale)); expectDefaults();
});

it.each(['Tenant B', 'Actor staff'])('detects %s and a return to the original identity while Queue is unmounted', async identity => {
  const router = setup(); await screen.findByRole('table'); fillAll();
  fireEvent.click(screen.getByRole('link', { name: 'Portfolio Comparison' }));
  click(identity); click(identity === 'Tenant B' ? 'Tenant A' : 'Actor owner');
  await act(() => router.navigate(-1)); expectDefaults();
  await waitFor(() => expect(router.state.location.search).not.toContain('oqAnalysis'));
});

it('accepts validated direct-link status, civil dates and Analysis and strips uncontracted parameters', () => {
  const router = setup(['/orders?oqStatus=ALL&oqFrom=2024-02-29&oqTo=2026-10-25&oqAnalysis=EXPIRY&customer=private&redirect=https://unsafe.example']);
  expect(screen.getByRole('button', { name: 'All statuses' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByLabelText('Received from (MYT)')).toHaveValue('2024-02-29');
  expect(screen.getByLabelText('Received through (MYT)')).toHaveValue('2026-10-25');
  expect(screen.getByLabelText('Analysis view')).toHaveValue('EXPIRY');
  expect(router.state.location.search).not.toMatch(/private|redirect|customer/);
});

it.each([
  'oqStatus=INVENTED&oqAnalysis=%E0%A4%A&oqFrom=2026-02-30&oqTo=2026-10-24T00:00:00Z',
  'oqStatus=ALL&oqStatus=ACCEPTED&oqAnalysis=FCFS&oqAnalysis=PROFIT&oqFrom=2026-01-01&oqFrom=2026-01-02&oqTo=0000-01-01',
  'oqState=unknown&oqStatus=ALL&oqAnalysis=PROFIT&oqFrom=2026-01-01',
  'oqState=a&oqState=b&oqStatus=ALL',
])('safely canonicalizes malformed/duplicated/expired direct URLs: %s', query => {
  const router = setup([`/orders?${query}`]); expectDefaults();
  expect([...new URLSearchParams(router.state.location.search).keys()]).toEqual(['oqState']);
});

it('preserves a valid but inverted date range as an explicit error rather than silently broadening results', () => {
  setup(['/orders?oqFrom=2026-10-25&oqTo=2026-10-24']);
  expect(screen.getByRole('alert')).toHaveTextContent('must be on or before');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

it('Reset filters clears all filter URL parameters and private fields while retaining Analysis across remount', async () => {
  const router = setup(); await screen.findByRole('table'); fillAll(); click('Reset filters');
  expectDefaults('PROFIT');
  expect([...new URLSearchParams(router.state.location.search).keys()]).toEqual(['oqState', 'oqAnalysis']);
  fireEvent.click(screen.getByRole('link', { name: 'Portfolio Comparison' }));
  fireEvent.click(await screen.findByRole('link', { name: 'Back to Order Decision Queue' }));
  await screen.findByRole('table'); expectDefaults('PROFIT');
});

it('replaces edits rather than adding a browser history entry for every search keystroke', async () => {
  const router = setup(['/sentinel', '/orders']);
  for (const text of ['a', 'ab', 'abc']) change('Search order, customer or product', text);
  click('All statuses'); change('Analysis view', 'FCFS');
  await act(() => router.navigate(-1));
  expect(screen.getByText('Earlier history entry')).toBeInTheDocument();
  await act(() => router.navigate(1));
  expect(screen.getByLabelText('Search order, customer or product')).toHaveValue('abc');
  expect(screen.getByLabelText('Analysis view')).toHaveValue('FCFS');
});

it('restores preferences with the real App, StrictMode, BrowserRouter and native history Back/Forward', async () => {
  window.history.replaceState({}, '', '/orders?oqStatus=ALL');
  render(<StrictMode><App routeExtensions={orderPlanningRoutes} /></StrictMode>);
  await screen.findByRole('heading', { name: 'Order Decision Queue' });
  change('Customer', 'private customer search'); change('Analysis view', 'EXPIRY');
  const first = window.location.search;
  fireEvent.click(screen.getByRole('link', { name: 'Portfolio Comparison' }));
  fireEvent.click(await screen.findByRole('link', { name: 'Back to Order Decision Queue' }));
  expect(screen.getByLabelText('Customer')).toHaveValue('private customer search');
  change('Customer', 'second visit'); change('Analysis view', 'FCFS');
  await act(async () => window.history.back());
  await waitFor(() => expect(window.location.pathname).toBe('/orders/portfolio'));
  await act(async () => window.history.back());
  await waitFor(() => expect(screen.getByLabelText('Customer')).toHaveValue('private customer search'));
  expect(window.location.search).toBe(first);
  expect(screen.getByLabelText('Analysis view')).toHaveValue('EXPIRY');
  await act(async () => window.history.forward());
  await waitFor(() => expect(window.location.pathname).toBe('/orders/portfolio'));
  await act(async () => window.history.forward());
  await waitFor(() => expect(screen.getByLabelText('Customer')).toHaveValue('second visit'));
  expect(screen.getByLabelText('Analysis view')).toHaveValue('FCFS');
  expect(window.location.search).not.toMatch(/private|customer|second/);
  expect(await screen.findByRole('alert')).toHaveTextContent('Order queue unavailable');
});
