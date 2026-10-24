import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { App } from '../../App';
import { operationalApi } from '../context/operationalApi';
import type { OrderContextRecord } from '../context/types';
import { OrderQueuePage } from './OrderQueuePage';
import { orderPlanningRoutes } from './portfolioRoutes';

const context = (orderId = 'uat-order'): OrderContextRecord => ({
  context_id: 'uat-context', tenant_id: 'tenant_demo_01', order_id: orderId, customer_id: 'uat-customer',
  customer_identity_status: 'LINK_VERIFIED', status: 'INFORMATION_PARTIAL', context_version: 1,
  requested_items: [{ sku: 'UAT-BREAD', quantity: '20', unit: 'pieces' }], requested_delivery_at: null,
  missing_fields: ['requested_delivery_at'], conflicts: [], source_message_ids: [], field_evidence: {},
  created_at: '2026-10-24T00:00:00Z', updated_at: '2026-10-24T00:00:00Z',
});
beforeEach(() => {
  vi.spyOn(operationalApi, 'getContextByOrder').mockResolvedValue(context());
  vi.spyOn(operationalApi, 'listContextVersions').mockResolvedValue([]);
  vi.spyOn(operationalApi, 'listContextReviews').mockResolvedValue([]);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.history.replaceState({}, '', '/'); });

it('navigates an explicitly injected test queue through the real detail/P1 workspace and existing planning routes', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  const publish = vi.spyOn(operationalApi, 'publishContext');
  window.history.replaceState({}, '', '/uat-queue');
  render(<App routeExtensions={[...orderPlanningRoutes, { path: '/uat-queue', element: <OrderQueuePage source={{
    cacheKey: 'uat-only-queue', load: async () => ({ items: [{ id: 'uat-order', status: 'PENDING_ACCEPTANCE', evidenceTier: 'SYNTHETIC' }], coverage: 'complete' }),
  }} /> }]} />);
  fireEvent.click(await screen.findByRole('link', { name: 'View Details for uat-order' }));
  expect(await screen.findByRole('heading', { name: 'Order Context: uat-order' })).toBeInTheDocument();
  expect(window.location.pathname).toBe('/orders/uat-order');
  const nav = within(screen.getByRole('navigation', { name: 'Primary navigation' }));
  expect(nav.getByRole('link', { name: 'All Orders' })).toHaveAttribute('aria-current', 'page');
  expect(nav.getAllByRole('link').filter(link => link.getAttribute('aria-current') === 'page')).toHaveLength(1);
  expect(await screen.findByRole('heading', { name: 'Order Decision workspace' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Version History' }));
  expect(screen.getByLabelText('Version History')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Review & Amend' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Publish to Core' })).toBeInTheDocument();
  fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: 'Back to Order Queue' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Order queue unavailable');
  if (screen.getByRole('button', { name: 'Planning' }).getAttribute('aria-expanded') === 'false')
    fireEvent.click(screen.getByRole('button', { name: 'Planning' }));
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Primary navigation' })).getByRole('link', { name: 'Portfolio Comparison' }));
  expect(await screen.findByRole('heading', { name: 'Portfolio API unavailable' })).toBeInTheDocument();
  fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: 'Production & Delivery Calendar' }));
  expect(await screen.findByRole('heading', { name: 'Scheduling API unavailable' })).toBeInTheDocument();
  if (screen.getByRole('button', { name: 'Planning' }).getAttribute('aria-expanded') === 'false')
    fireEvent.click(screen.getByRole('button', { name: 'Planning' }));
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Primary navigation' })).getByRole('link', { name: 'Portfolio Comparison' }));
  expect(await screen.findByRole('heading', { name: 'Portfolio API unavailable' })).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled(); expect(publish).not.toHaveBeenCalled();
  expect(operationalApi.getContextByOrder).toHaveBeenCalledWith('uat-order', expect.objectContaining({ 'X-Tenant-ID': 'tenant_demo_01', 'X-Actor-ID': 'user_owner_01' }));
});

it('withholds a wrong-order legacy context and recovers by re-reading without editing P1', async () => {
  vi.mocked(operationalApi.getContextByOrder).mockResolvedValueOnce({ ...context('foreign-order'), customer_id: 'foreign-customer' });
  window.history.replaceState({}, '', '/orders/uat-order'); render(<App routeExtensions={orderPlanningRoutes} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('legacy context does not match');
  expect(screen.queryByText('foreign-customer')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Order Context: foreign-order' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Publish to Core' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh order assessment view' }));
  expect(await screen.findByRole('heading', { name: 'Order Context: uat-order' })).toBeInTheDocument();
  expect(window.location.pathname).toBe('/orders/uat-order');
  const nav = within(screen.getByRole('navigation', { name: 'Primary navigation' }));
  expect(nav.getByRole('link', { name: 'All Orders' })).toHaveAttribute('aria-current', 'page');
  expect(nav.getAllByRole('link').filter(link => link.getAttribute('aria-current') === 'page')).toHaveLength(1);
});

it.each([
  ['/orders', 'Order Decision Queue'], ['/orders/portfolio', 'Portfolio Comparison'], ['/orders/calendar', 'Production & Delivery Calendar'],
])('preserves deep-link resolution after a full App remount at %s', async (path, heading) => {
  window.history.replaceState({}, '', path); const first = render(<App initialActorId="user_staff_01" routeExtensions={orderPlanningRoutes} />);
  await screen.findByRole('heading', { name: heading }); first.unmount();
  render(<App initialActorId="user_staff_01" routeExtensions={orderPlanningRoutes} />);
  expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
  expect(operationalApi.getContextByOrder).not.toHaveBeenCalled();
});
