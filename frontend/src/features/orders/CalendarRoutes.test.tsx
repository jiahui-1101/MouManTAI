import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { App } from '../../App';
import { operationalApi } from '../context/operationalApi';
import { orderPlanningRoutes } from './portfolioRoutes';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.history.replaceState({}, '', '/'); });
it.each(['user_owner_01', 'user_manager_01', 'user_staff_01'])('preserves Portfolio and routes Calendar statically with active Orders for %s', async actor => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); const detail = vi.spyOn(operationalApi, 'getContextByOrder');
  expect(orderPlanningRoutes.map(r => r.path)).toEqual(['/orders/portfolio', '/orders/calendar']);
  window.history.replaceState({}, '', '/orders/calendar'); render(<App initialActorId={actor} routeExtensions={orderPlanningRoutes} />);
  expect(await screen.findByRole('heading', { name: 'Scheduling API unavailable' })).toBeInTheDocument();
  const nav = screen.getByRole('navigation', { name: 'Primary navigation' });
  expect(within(nav).getByRole('link', { name: /^(Orders|All Orders)$/ })).toHaveAttribute('aria-current', 'page');
  expect(within(nav).getAllByRole('link').map(l => l.getAttribute('href'))).toEqual(within(nav).queryByRole('link', { name: 'All Orders' }) ? ['/overview', '/orders', '/orders/pending', '/communications', '/settings'] : ['/overview', '/activity', '/inbox', '/orders', '/commitments/demo', '/recovery/demo', '/communications']);
  fireEvent.click(screen.getByRole('link', { name: 'Portfolio Comparison' }));
  expect(await screen.findByRole('heading', { name: 'Portfolio API unavailable' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Production & Delivery Calendar' }));
  expect(await screen.findByRole('heading', { name: 'Scheduling API unavailable' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Order Decision Queue' }));
  expect(await screen.findByRole('heading', { name: 'Order Decision Queue' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Production & Delivery Calendar' }));
  expect(await screen.findByRole('heading', { name: 'Scheduling API unavailable' })).toBeInTheDocument();
  expect(detail).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
});
