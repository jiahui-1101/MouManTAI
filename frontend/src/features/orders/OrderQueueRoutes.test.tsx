import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { App } from '../../App';
import { operationalApi } from '../context/operationalApi';
import type { OrderContextRecord } from '../context/types';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.history.replaceState({}, '', '/'); });

describe('Orders integration through the real application router and Sidebar', () => {
  it.each(['user_owner_01', 'user_manager_01', 'user_staff_01'])('routes /orders for existing actor %s without speculative HTTP', async actor => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    window.history.replaceState({}, '', '/orders');
    render(<App initialActorId={actor} />);
    expect(screen.getByRole('heading', { name: 'Order Decision Queue' })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Order queue unavailable');
    const nav = screen.getByRole('navigation', { name: 'Primary navigation' });
    expect(within(nav).getByRole('link', { name: /^(Orders|All Orders)$/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByLabelText('Demo role selector')).toHaveValue(actor);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('navigates from the Sidebar while preserving every existing navigation destination', async () => {
    window.history.replaceState({}, '', '/not-a-route');
    render(<App />);
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Primary navigation' });
    const group = within(nav).queryByRole('button', { name: /^Orders$/ });
    if (group?.getAttribute('aria-expanded') === 'false') fireEvent.click(group);
    expect(within(nav).getAllByRole('link').map(link => link.getAttribute('href'))).toEqual(group ? ['/overview', '/orders', '/orders/pending', '/communications', '/settings'] : ['/overview', '/activity', '/inbox', '/orders', '/commitments/demo', '/recovery/demo', '/communications']);
    const orders = within(nav).getByRole('link', { name: /^(Orders|All Orders)$/ });
    orders.focus(); expect(orders).toHaveFocus();
    fireEvent.click(orders);
    expect(await screen.findByRole('heading', { name: 'Order Decision Queue' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/orders');
    fireEvent.change(screen.getByLabelText('Demo role selector'), { target: { value: 'user_staff_01' } });
    expect(screen.getByTestId('shell-tenant-badge')).toHaveTextContent('STAFF');
    expect(await screen.findByRole('alert')).toHaveTextContent('Order queue unavailable');
  });

  it('keeps the actual legacy /orders/:id component, API lookup and breadcrumb navigation', async () => {
    const context: OrderContextRecord = {
      context_id: 'synthetic-context', tenant_id: 'tenant_demo_01', order_id: 'legacy-order',
      customer_id: 'synthetic-customer', customer_identity_status: 'LINK_VERIFIED',
      status: 'INFORMATION_PARTIAL', requested_items: [], requested_delivery_at: null,
      missing_fields: [], conflicts: [], source_message_ids: [], field_evidence: {}, context_version: 1,
      created_at: '2026-10-23T00:00:00Z', updated_at: '2026-10-23T00:00:00Z',
    };
    const getContext = vi.spyOn(operationalApi, 'getContextByOrder').mockResolvedValue(context);
    vi.spyOn(operationalApi, 'listContextVersions').mockResolvedValue([]);
    vi.spyOn(operationalApi, 'listContextReviews').mockResolvedValue([]);
    window.history.replaceState({}, '', '/orders/legacy-order');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Order Context: legacy-order' })).toBeInTheDocument();
    expect(getContext).toHaveBeenCalledWith('legacy-order', expect.objectContaining({ 'X-Tenant-ID': 'tenant_demo_01', 'X-Actor-ID': 'user_owner_01' }));
    expect(screen.getByRole('heading', { name: 'Order detail & feasibility' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Order Decision Queue' })).not.toBeInTheDocument();
    const crumbs = screen.queryByRole('navigation', { name: 'Breadcrumb' });
    fireEvent.click(crumbs ? within(crumbs).getByRole('link', { name: 'Orders' }) : screen.getByRole('link', { name: 'Back to Order Queue' }));
    expect(await screen.findByRole('heading', { name: 'Order Decision Queue' })).toBeInTheDocument();
  });
});
