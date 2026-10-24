import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { operationalApi } from '../context/operationalApi';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../../shared/auth';
import { OrderQueuePage } from './OrderQueuePage';

// Keep the real shared shell, auth and Developer B pages. Sentinels verify that
// unrelated route registrations still resolve to their original feature modules.
vi.mock('../overview/OverviewPage', () => ({ OverviewPage: () => <h2>Overview route sentinel</h2> }));
vi.mock('../activity/ActivityPage', () => ({ ActivityPage: () => <h2>Activity route sentinel</h2> }));
vi.mock('../context/DurableInbox', () => ({ DurableInbox: () => <h2>Inbox route sentinel</h2> }));
vi.mock('../context/HumanReviewPage', () => ({ HumanReviewPage: () => <h2>Human Review route sentinel</h2> }));
vi.mock('../communication/CommunicationCenterPage', () => ({ CommunicationCenterPage: () => <h2>Communications route sentinel</h2> }));
vi.mock('../communication/ConfirmationWorkspacePage', () => ({ ConfirmationWorkspacePage: () => <h2>Confirmation route sentinel</h2> }));
vi.mock('../communication/FollowUpQueuePage', () => ({ FollowUpQueuePage: () => <h2>Follow-up route sentinel</h2> }));
vi.mock('../recovery/RecoveryCaseRoutePage', () => ({ RecoveryCaseRoutePage: () => <h2>Recovery case route sentinel</h2> }));
vi.mock('../recovery/RecoveryPage', () => ({ RecoveryPage: () => <h2>Recovery plans route sentinel</h2> }));
vi.mock('../feasibility/CommitmentFeasibilityPage', () => ({ CommitmentFeasibilityPage: () => <h2>Commitment route sentinel</h2> }));
vi.mock('../feasibility/ImpactDetailPage', () => ({ ImpactDetailPage: () => <h2>Impact route sentinel</h2> }));

const mappings = [
  ['/orders', 'Order Decision Queue', 'All Orders'],
  ['/orders/pending', 'Order Decision Queue', 'All Orders'],
  ['/orders/portfolio', 'Portfolio Comparison', 'Portfolio Comparison'],
  ['/planning/portfolio', 'Portfolio Comparison', 'Portfolio Comparison'],
  ['/orders/calendar', 'Production & Delivery Calendar', 'Calendar'],
  ['/calendar', 'Production & Delivery Calendar', 'Calendar'],
  ['/orders/route-test-order', 'Order detail & feasibility', 'All Orders'],
] as const;

beforeEach(() => {
  window.localStorage.clear();
  vi.spyOn(operationalApi, 'getContextByOrder').mockRejectedValue(new Error('No test order source'));
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ code: 'TEST_UNAVAILABLE', message: 'Test source unavailable' }), { status: 503 })));
});
afterEach(() => {
  cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.localStorage.clear();
  window.history.replaceState({}, '', '/');
});
const main = () => within(screen.getByRole('main'));
const nav = () => within(screen.getByRole('navigation', { name: 'Primary navigation' }));
function openGroup(name: string) {
  const group = nav().getByRole('button', { name });
  if (group.getAttribute('aria-expanded') === 'false') fireEvent.click(group);
}

describe.each(['user_owner_01', 'user_manager_01', 'user_staff_01'])('direct routes for %s', actor => {
  it.each(mappings)('renders and remounts %s without optional route extensions', async (path, heading, active) => {
    window.history.replaceState({}, '', path);
    let view = render(<App initialActorId={actor} initialTenantId="tenant-routing" />);
    await main().findByRole('heading', { name: heading });
    expect(nav().getByRole('link', { name: active })).toHaveAttribute('aria-current', 'page');
    expect(nav().getAllByRole('link').filter(link => link.getAttribute('aria-current') === 'page')).toHaveLength(1);
    expect(nav().getByRole('combobox', { name: 'Demo role selector' })).toHaveValue(actor);
    expect(screen.getByTestId('shell-tenant-badge')).toHaveTextContent('tenant-routing');
    expect(main().queryByText(/This route is reserved/)).not.toBeInTheDocument();
    view.unmount();
    view = render(<App initialActorId={actor} initialTenantId="tenant-routing" />);
    await main().findByRole('heading', { name: heading });
    if (!path.endsWith('route-test-order')) expect(operationalApi.getContextByOrder).not.toHaveBeenCalled();
    else expect(operationalApi.getContextByOrder).toHaveBeenCalledWith('route-test-order', expect.objectContaining({ 'X-Tenant-ID': 'tenant-routing', 'X-Actor-ID': actor }));
  });
});

it('opens remaining Sidebar destinations and restores hidden Pending and prior preferences on Back/Forward', async () => {
  window.history.replaceState({}, '', '/orders?oqStatus=ACCEPTED&oqAnalysis=PROFIT');
  render(<App />);
  expect(main().getByRole('combobox', { name: 'Order Status' })).toHaveValue('ACCEPTED');
  fireEvent.change(main().getByLabelText('Customer'), { target: { value: 'private test preference' } });
  // Legacy deep links remain reachable without a separate Sidebar item.
  window.history.pushState({}, '', '/orders/pending');
  await act(async () => { window.dispatchEvent(new PopStateEvent('popstate')); });
  await waitFor(() => expect(window.location.pathname).toBe('/orders/pending'));
  expect(main().getByRole('combobox', { name: 'Order Status' })).toHaveValue('PENDING_ACCEPTANCE');
  expect(main().getByLabelText('Analysis view')).toHaveValue('PROFIT');
  expect(main().getByLabelText('Customer')).toHaveValue('private test preference');
  expect(nav().getAllByRole('link').filter(link => link.getAttribute('aria-current') === 'page')).toHaveLength(1);
  openGroup('Planning');
  fireEvent.click(nav().getByRole('link', { name: 'Portfolio Comparison' }));
  await main().findByRole('heading', { name: 'Portfolio Comparison' });
  expect(window.location.pathname).toBe('/planning/portfolio');
  openGroup('Dashboard');
  fireEvent.click(nav().getByRole('link', { name: 'Calendar' }));
  await main().findByRole('heading', { name: 'Production & Delivery Calendar' });
  expect(window.location.pathname).toBe('/calendar');
  await act(async () => { window.history.back(); });
  await waitFor(() => expect(window.location.pathname).toBe('/planning/portfolio'), { timeout: 10000 });
  await main().findByRole('heading', { name: 'Portfolio Comparison' }, { timeout: 10000 });
  await act(async () => { window.history.back(); });
  await waitFor(() => expect(main().getByRole('combobox', { name: 'Order Status' })).toHaveValue('PENDING_ACCEPTANCE'), { timeout: 10000 });
  expect(window.location.pathname).toBe('/orders/pending');
  await act(async () => { window.history.back(); });
  await waitFor(() => expect(main().getByRole('combobox', { name: 'Order Status' })).toHaveValue('ACCEPTED'), { timeout: 10000 });
  expect(window.location.pathname).toBe('/orders');
  expect(main().getByLabelText('Customer')).toHaveValue('private test preference');
  await act(async () => { window.history.forward(); });
  await waitFor(() => expect(main().getByRole('combobox', { name: 'Order Status' })).toHaveValue('PENDING_ACCEPTANCE'), { timeout: 10000 });
  expect(window.location.pathname).toBe('/orders/pending');
  openGroup('Orders');
  fireEvent.click(nav().getByRole('link', { name: 'All Orders' }));
  await waitFor(() => expect(window.location.pathname).toBe('/orders'));
  expect(main().getByRole('heading', { name: 'Order Decision Queue' })).toBeInTheDocument();
});

it('forces Pending on direct access and allows another status to leave the Pending entry', async () => {
  window.history.replaceState({}, '', '/orders/pending?oqStatus=ACCEPTED&oqAnalysis=FCFS');
  render(<App />);
  expect(main().getByRole('combobox', { name: 'Order Status' })).toHaveValue('PENDING_ACCEPTANCE');
  expect(main().getByLabelText('Analysis view')).toHaveValue('FCFS');
  fireEvent.change(main().getByRole('combobox', { name: 'Order Status' }), { target: { value: 'REJECTED' } });
  await waitFor(() => expect(window.location.pathname).toBe('/orders'));
  expect(main().getByRole('combobox', { name: 'Order Status' })).toHaveValue('REJECTED');
});

it('uses the existing Queue filtering to display only pending source rows at the Pending route', async () => {
  const queue = <OrderQueuePage source={{ cacheKey: 'routing-test-only', load: async () => ({ coverage: 'complete', items: [
    { id: 'synthetic-pending-routing', status: 'PENDING_ACCEPTANCE', evidenceTier: 'SYNTHETIC' },
    { id: 'synthetic-accepted-routing', status: 'ACCEPTED', evidenceTier: 'SYNTHETIC' },
  ] }) }} />;
  render(<QueryClientProvider client={new QueryClient()}><AuthProvider>
    <MemoryRouter initialEntries={['/orders/pending?oqStatus=ACCEPTED']}><Routes>
      <Route path="/orders/pending" element={queue} /><Route path="/orders" element={queue} />
    </Routes></MemoryRouter>
  </AuthProvider></QueryClientProvider>);
  expect(await screen.findByRole('link', { name: 'View Details for synthetic-pending-routing' })).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'View Details for synthetic-accepted-routing' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox', { name: 'Order Status' }), { target: { value: 'ACCEPTED' } });
  expect(await screen.findByRole('link', { name: 'View Details for synthetic-accepted-routing' })).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'View Details for synthetic-pending-routing' })).not.toBeInTheDocument();
});

it('keeps Pending Reset and actor changes within the existing preference safety boundary', async () => {
  window.history.replaceState({}, '', '/orders/pending?oqAnalysis=EXPIRY');
  render(<App />);
  fireEvent.change(main().getByLabelText('Customer'), { target: { value: 'private filter' } });
  const old = window.location.href;
  fireEvent.click(main().getByRole('button', { name: 'Reset filters' }));
  expect(main().getByLabelText('Customer')).toHaveValue('');
  expect(main().getByLabelText('Analysis view')).toHaveValue('QUEUE');
  fireEvent.change(nav().getByRole('combobox', { name: 'Demo role selector' }), { target: { value: 'user_staff_01' } });
  expect(main().getByLabelText('Analysis view')).toHaveValue('QUEUE');
  window.history.pushState({}, '', old);
  await act(async () => { window.dispatchEvent(new PopStateEvent('popstate')); });
  expect(main().getByLabelText('Customer')).toHaveValue('');
  expect(main().getByLabelText('Analysis view')).toHaveValue('QUEUE');
});

it.each([
  ['/', 'Overview'], ['/overview', 'Overview'], ['/activity', 'Activity'], ['/inbox', 'Inbox'],
  ['/human-review', 'Human Review'], ['/communications', 'Communications'],
  ['/communications/follow-ups', 'Follow-up'], ['/confirmations/conf-test', 'Confirmation'],
  ['/commitments/commitment-test', 'Commitment'], ['/impact/impact-test', 'Impact'],
  ['/recovery/case-test', 'Recovery case'], ['/recovery/case-test/plans', 'Recovery plans'],
])('preserves the existing feature registration at %s', async (path, heading) => {
  window.history.replaceState({}, '', path); render(<App />);
  expect(await main().findByRole('heading', { name: `${heading} route sentinel` })).toBeInTheDocument();
});

it.each([
  ['/planning', 'Planning'], ['/planning/forecasts', 'Forecasts'],
  ['/suppliers/sourcing', 'Sourcing'], ['/recovery', 'Emergency Cases'], ['/recovery/plans', 'Recovery Plans'],
  ['/insights', 'Insights'], ['/insights/performance', 'Performance'], ['/insights/history', 'Decision History'],
  ['/settings', 'Settings'],
])('preserves the legitimate placeholder at %s', (path, heading) => {
  window.history.replaceState({}, '', path); render(<App />);
  expect(main().getByRole('heading', { name: heading })).toBeInTheDocument();
  expect(main().getByText(/This route is reserved/)).toBeInTheDocument();
});

it.each([
  ['/suppliers', 'Supplier directory'], ['/suppliers/compare', 'Offer comparison'], ['/suppliers/demo-packaging', 'Supplier details unavailable'],
])('preserves the implemented supplier route %s', (path, heading) => {
  window.history.replaceState({}, '', path); render(<App />);
  expect(main().getByRole('heading', { name: heading })).toBeInTheDocument();
});

it('replaces the legacy feasibility placeholder with the Queue without a Back redirect loop', async () => {
  window.history.replaceState({}, '', '/calendar');
  render(<App />);
  await main().findByRole('heading', { name: 'Production & Delivery Calendar' });
  window.history.pushState({}, '', '/planning/feasibility?uncontracted=discarded');
  await act(async () => { window.dispatchEvent(new PopStateEvent('popstate')); });
  await main().findByRole('heading', { name: 'Order Decision Queue' });
  expect(window.location.pathname).toBe('/orders');
  expect(new URLSearchParams(window.location.search).has('uncontracted')).toBe(false);
  expect(nav().getByRole('link', { name: 'All Orders' })).toHaveAttribute('aria-current', 'page');
  await act(async () => { window.history.back(); });
  await main().findByRole('heading', { name: 'Production & Delivery Calendar' }, { timeout: 10000 });
  await act(async () => { window.history.forward(); });
  await main().findByRole('heading', { name: 'Order Decision Queue' }, { timeout: 10000 });
  expect(window.location.pathname).toBe('/orders');
});
