import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { App } from '../../App';
import { operationalApi } from '../context/operationalApi';
import { orderPlanningRoutes } from './portfolioRoutes';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.history.replaceState({}, '', '/'); });
it.each(['user_owner_01', 'user_manager_01', 'user_staff_01'])('registers the exact static route without dynamic detail lookup for %s', async actor => {
  const getContext = vi.spyOn(operationalApi, 'getContextByOrder'); const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  window.history.replaceState({}, '', '/orders/portfolio'); render(<App initialActorId={actor} routeExtensions={orderPlanningRoutes} />);
  expect(await screen.findByRole('heading', { name: 'Portfolio Comparison' })).toBeInTheDocument();
  const nav = screen.getByRole('navigation', { name: 'Primary navigation' });
  expect(within(nav).getByRole('link', { name: 'Portfolio Comparison' })).toHaveAttribute('aria-current', 'page');
  expect(getContext).not.toHaveBeenCalled(); expect(fetch).toHaveBeenCalledWith('/v1/planning/portfolio/inputs', expect.any(Object));
  fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: 'Back to Order Decision Queue' }));
  expect(await screen.findByRole('heading', { name: 'Order Decision Queue' })).toBeInTheDocument();
  const planning = within(nav).getByRole('button', { name: 'Planning' });
  if (planning.getAttribute('aria-expanded') === 'false') fireEvent.click(planning);
  fireEvent.click(within(nav).getByRole('link', { name: 'Portfolio Comparison' }));
  expect(await screen.findByRole('heading', { name: 'Portfolio Comparison' })).toBeInTheDocument();
  expect(getContext).not.toHaveBeenCalled();
});
