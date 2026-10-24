import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom';
import { AuthProvider, useAuth } from '../../shared/auth';
import { CalendarSchedulingPage } from './CalendarSchedulingPage';
import { PortfolioComparisonPage } from './PortfolioComparisonPage';
import { portfolioCalendarHref, readPortfolioCalendarRequest } from './portfolioCalendarContext';
import { calendarWindow } from './calendarDates';
import { calendarFixture } from './calendarTest.fixtures';
import { portfolioFixture, portfolioTestNow } from './portfolioTest.fixtures';
import type { PortfolioSource } from './portfolioTypes';
import { App } from '../../App';
import { orderPlanningRoutes } from './portfolioRoutes';

const context = { date: '2026-10-24', from: '2026-10-19', toExclusive: '2026-10-26', timeZone: 'Asia/Kuala_Lumpur' };
const href = portfolioCalendarHref(context.date, context);
beforeEach(() => vi.spyOn(Date, 'now').mockReturnValue(portfolioTestNow));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.history.replaceState({}, '', '/'); });
function Controls() { const auth = useAuth(); return <>
  <button onClick={() => auth.setTenantId('other-tenant')}>Change context tenant</button>
  <button onClick={() => auth.setActorId('user_staff_01')}>Change context actor</button><Outlet /></>; }
function setup(path = '/orders/calendar', source?: PortfolioSource) {
  const router = createMemoryRouter([{ element: <Controls />, children: [
    { path: '/orders/calendar', element: <CalendarSchedulingPage initialDate="2026-10-24" source={{ cacheKey: 'calendar-context-test', load: async () => calendarFixture() }} /> },
    { path: '/orders/portfolio', element: <PortfolioComparisonPage source={source} /> },
  ] }], { initialEntries: [path] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><AuthProvider initialTenantId="test-tenant" initialActorId="user_owner_01">
    <RouterProvider router={router} /></AuthProvider></QueryClientProvider>);
  return router;
}
const panel = () => screen.getByRole('region', { name: 'Requested Calendar comparison context' });

describe('Strict feature-local requested date context', () => {
  it('round-trips the existing Calendar window and contains only date/range/timezone metadata', () => {
    expect(readPortfolioCalendarRequest(new URL(href, 'http://test').search)).toEqual(context);
    expect([...new URL(href, 'http://test').searchParams.keys()]).toEqual(['calDate', 'calFrom', 'calTo', 'calZone']);
  });
  it.each([
    '', '?calDate=2026-10-24', '?calDate=2026-10-24&calDate=2026-10-25&calFrom=2026-10-19&calTo=2026-10-26&calZone=UTC',
    '?calDate=2026-02-29&calFrom=2026-02-01&calTo=2026-03-01&calZone=UTC',
    '?calDate=2026-10-24&calFrom=2026-13-01&calTo=2027-01-01&calZone=UTC',
    '?calDate=2026-10-24&calFrom=2026-10-26&calTo=2026-10-19&calZone=UTC',
    '?calDate=2026-10-24&calFrom=2026-10-24&calTo=2026-10-24&calZone=UTC',
    '?calDate=2026-10-26&calFrom=2026-10-19&calTo=2026-10-26&calZone=UTC',
    '?calDate=2026-10-18&calFrom=2026-10-19&calTo=2026-10-26&calZone=UTC',
    '?calDate=2026-10-24T00:00:00Z&calFrom=2026-10-19&calTo=2026-10-26&calZone=UTC',
    '?calDate=2026-10-24&calFrom=2026-10-19&calTo=2026-10-26&calZone=Not/AZone',
    '?calDate=2026-10-24&calFrom=2026-10-19&calTo=2026-10-26&calZone=%E0%A4%A',
  ])('ignores absent, malformed or stale/inconsistent requested context: %s', search => {
    expect(readPortfolioCalendarRequest(search)).toBeNull();
  });
  it('accepts real leap dates and historical requests without calling them current source coverage', () => {
    const leap = { date: '2024-02-29', from: '2024-02-01', toExclusive: '2024-03-01', timeZone: 'UTC' };
    expect(readPortfolioCalendarRequest(new URL(portfolioCalendarHref(leap.date, leap), 'http://test').search)).toEqual(leap);
    expect(portfolioCalendarHref('2026-02-30', context)).toBe('/orders/portfolio');
  });
  it.each(['calDate', 'calFrom', 'calTo', 'calZone'])('rejects duplicated %s rather than choosing a stale value', key => {
    const url = new URL(href, 'http://test'); url.searchParams.append(key, url.searchParams.get(key)!);
    expect(readPortfolioCalendarRequest(url.search)).toBeNull();
  });
  it.each(['Month', 'Week', 'Day'])('navigates the current %s view and selected date into Portfolio without sending date arguments to its source', async view => {
    const load = vi.fn<PortfolioSource['load']>().mockResolvedValue(portfolioFixture());
    const router = setup('/orders/calendar', { cacheKey: 'context-portfolio', load });
    await screen.findByRole('group', { name: 'Schedule filters' });
    fireEvent.click(screen.getByRole('button', { name: view }));
    fireEvent.change(screen.getByLabelText('Chosen date'), { target: { value: '2026-10-25' } });
    const expected = { date: '2026-10-25', ...calendarWindow('2026-10-25', view.toUpperCase() as 'MONTH' | 'WEEK' | 'DAY', 'Asia/Kuala_Lumpur', 1)! };
    const link = screen.getByRole('link', { name: 'Portfolio Comparison' });
    expect(readPortfolioCalendarRequest(new URL(link.getAttribute('href')!, 'http://test').search)).toEqual(expected);
    fireEvent.click(link);
    await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    expect(panel()).toHaveTextContent(expected.date); expect(panel()).toHaveTextContent(expected.from); expect(panel()).toHaveTextContent(expected.toExclusive);
    expect(panel()).toHaveTextContent('Results are not filtered by these dates');
    expect(router.state.location.pathname).toBe('/orders/portfolio');
    expect(load).toHaveBeenCalledWith({ tenantId: 'test-tenant', actorId: 'user_owner_01' }, expect.any(AbortSignal));
    expect(load.mock.calls[0]).toHaveLength(2);
  });
  it('reflects week start and Month-to-Day drill-down in each newly generated navigation link', async () => {
    setup(); await screen.findByRole('group', { name: 'Schedule filters' });
    fireEvent.click(screen.getByRole('button', { name: 'Week' }));
    fireEvent.change(screen.getByLabelText('Week begins'), { target: { value: '0' } });
    let link = screen.getByRole('link', { name: 'Portfolio Comparison' });
    expect(readPortfolioCalendarRequest(new URL(link.getAttribute('href')!, 'http://test').search)?.from).toBe('2026-10-18');
    fireEvent.click(screen.getByRole('button', { name: 'Month' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open day 2026-10-24' }));
    link = screen.getByRole('link', { name: 'Portfolio Comparison' });
    expect(readPortfolioCalendarRequest(new URL(link.getAttribute('href')!, 'http://test').search)).toEqual({
      date: '2026-10-24', from: '2026-10-24', toExclusive: '2026-10-25', timeZone: 'Asia/Kuala_Lumpur',
    });
  });
  it('supports deep links and a full App remount while keeping source coverage honest', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    window.history.replaceState({}, '', href);
    const first = render(<App routeExtensions={orderPlanningRoutes} />);
    await screen.findByRole('heading', { name: 'Portfolio Comparison' });
    expect(panel()).toHaveTextContent('2026-10-24'); first.unmount();
    render(<App routeExtensions={orderPlanningRoutes} />);
    await screen.findByRole('heading', { name: 'Portfolio Comparison' });
    expect(panel()).toHaveTextContent('Portfolio date coverage is not supplied'); expect(fetch).toHaveBeenCalledWith('/v1/planning/portfolio/inputs', expect.any(Object));
  });
  it('uses current URL context on Back/Forward instead of retaining an obsolete requested date', async () => {
    const router = setup(href);
    const next = portfolioCalendarHref('2026-10-25', { ...context, from: '2026-10-25', toExclusive: '2026-10-26' });
    await act(() => router.navigate(next)); expect(panel()).toHaveTextContent('Requested Calendar date: 2026-10-25');
    await act(() => router.navigate(-1)); expect(panel()).toHaveTextContent('Requested Calendar date: 2026-10-24');
    await act(() => router.navigate(1)); expect(panel()).toHaveTextContent('Requested Calendar date: 2026-10-25');
    await act(() => router.navigate('/orders/portfolio')); expect(screen.queryByRole('region', { name: 'Requested Calendar comparison context' })).not.toBeInTheDocument();
  });
  it('does not refetch, date-filter or reset source scenario selection when only the requested date context changes', async () => {
    const load = vi.fn<PortfolioSource['load']>().mockResolvedValue(portfolioFixture());
    const router = setup(href, { cacheKey: 'context-only-change', load });
    await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    fireEvent.click(screen.getByRole('checkbox', { name: /Profit candidate/ }));
    await act(() => router.navigate(portfolioCalendarHref('2026-10-25', { ...context, from: '2026-10-25', toExclusive: '2026-10-26' })));
    expect(panel()).toHaveTextContent('Requested Calendar date: 2026-10-25');
    expect(screen.getByRole('checkbox', { name: /Profit candidate/ })).not.toBeChecked();
    expect(screen.getByRole('article', { name: 'Summary: First come first served' })).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(1);
  });
  it('does not echo malformed values or pass any requested URL context into API adapters', async () => {
    const load = vi.fn<PortfolioSource['load']>().mockResolvedValue(portfolioFixture());
    setup('/orders/portfolio?calDate=private-invalid&calFrom=bad&calTo=bad&calZone=bad', { cacheKey: 'invalid-context', load });
    await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    expect(within(panel()).getByRole('status')).toHaveTextContent('Calendar date context ignored');
    expect(document.body).not.toHaveTextContent('private-invalid'); expect(load.mock.calls[0]).toHaveLength(2);
  });
  it.each(['tenant', 'actor'])('keeps public requested dates separate from current %s authorization and query isolation', async identity => {
    const source: PortfolioSource = { cacheKey: 'identity-context', load: vi.fn(async () => portfolioFixture()) };
    setup(href, source); await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    fireEvent.click(screen.getByRole('button', { name: `Change context ${identity}` }));
    await screen.findByRole('alert');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(panel()).toHaveTextContent('Request context only');
    await waitFor(() => expect(source.load).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('region', { name: 'Strategy availability' })).not.toHaveTextContent('Returned by source');
  });
});
