import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../../shared/auth';
import { OrderDetailWorkspace } from './OrderDetailWorkspace';
import type { OrderDetail } from './detailTypes';

const now = Date.parse('2026-10-24T02:00:00Z');
const detail: OrderDetail = {
  id: 'source/order-1',
  tenantId: 'tenant-test',
  customer: 'Source buyer',
  version: '3',
  status: 'PENDING_ACCEPTANCE',
  currentDeadline: '2026-10-25T01:00:00Z',
  lines: [{ sku: 'BREAD', quantity: { amount: '12', unit: 'pieces' } }],
  assessment: {
    id: 'assessment-1',
    version: '1',
    orderVersion: '3',
    snapshotId: 'snapshot-1',
    snapshotAt: '2026-10-24T01:00:00Z',
    status: 'FEASIBLE',
    sourceVerified: true,
    complete: true,
    freshness: 'CURRENT',
    constraints: ['Source constraint'],
    recommendation: 'Source recommendation',
  },
};

function setup(data: OrderDetail | undefined = detail) {
  const refresh = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthProvider initialTenantId="tenant-test">
        <MemoryRouter>
          <OrderDetailWorkspace
            id="source/order-1"
            detail={data}
            now={now}
            busy={false}
            onRefresh={refresh}
            state={null}
            legacy={
              <section aria-label="Legacy source">
                <h2>Existing review workflow</h2>
              </section>
            }
            decisionSource={{
              cacheKey: 'workspace-test-only',
              load: async () => ({
                tenantId: 'tenant-test',
                orderId: 'source/order-1',
                sourceLabel: 'Synthetic test read source',
                financialAccess: 'UNKNOWN',
                events: [],
              }),
            }}
          />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
  return refresh;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it('shows source identity, back navigation, summary and a read-only decision panel without inventing missing fields', () => {
  const refresh = setup();
  expect(screen.getByRole('link', { name: 'Back to Order Queue' })).toHaveAttribute('href', '/orders');
  expect(screen.getByRole('heading', { level: 1, name: 'Order detail & feasibility' })).toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Order key facts' })).toHaveTextContent('12 pieces');
  expect(screen.getByRole('region', { name: 'Order key facts' })).toHaveTextContent('—');
  expect(screen.getByRole('complementary', { name: 'Decision panel' })).toHaveTextContent('Source recommendation');
  fireEvent.click(screen.getByRole('button', { name: 'Refresh order assessment view' }));
  expect(refresh).toHaveBeenCalledOnce();
});

it('supports accessible keyboard tabs without splitting routes or unmounting the existing history workflow', () => {
  setup();
  const overview = screen.getByRole('tab', { name: 'Overview' });
  overview.focus();
  expect(screen.queryByRole('heading', { name: 'Existing review workflow' })).not.toBeInTheDocument();
  fireEvent.keyDown(overview, { key: 'ArrowRight' });
  expect(screen.getByRole('tab', { name: 'Feasibility' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('region', { name: 'Inventory & materials' })).toBeVisible();
  fireEvent.keyDown(screen.getByRole('tab', { name: 'Feasibility' }), { key: 'End' });
  expect(screen.getByRole('heading', { name: 'Existing review workflow' })).toBeVisible();
  fireEvent.keyDown(screen.getByRole('tab', { name: 'History' }), { key: 'Home' });
  expect(screen.getByRole('region', { name: 'Order summary' })).toBeVisible();
});

it('does not promote an unknown or stale recommendation into decision guidance', () => {
  setup({ ...detail, assessment: { ...detail.assessment!, freshness: 'STALE' } });
  const panel = screen.getByRole('complementary', { name: 'Decision panel' });
  expect(panel).toHaveTextContent('Unavailable as decision guidance');
  expect(panel).not.toHaveTextContent('Source recommendation');
  expect(screen.getByRole('button', { name: 'Reassess feasibility' })).toBeDisabled();
});

it('opens the existing review workflow from the original evidence anchor', () => {
  setup();
  fireEvent.click(
    screen.getByRole('link', {
      name: 'Open existing P1 review, validation, versions and Core publishing',
    })
  );
  expect(screen.getByRole('tab', { name: 'History' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('heading', { name: 'Existing review workflow' })).toBeVisible();
});

it('does not aggregate different quantity units or reveal redacted financial values in summary cards', () => {
  setup({
    ...detail,
    lines: [
      { quantity: { amount: '12', unit: 'pieces' } },
      { quantity: { amount: '5', unit: 'kg' } },
    ],
    pricing: { access: 'REDACTED', quotedPrice: '999', currency: 'MYR' },
  });
  expect(screen.getByRole('region', { name: 'Order key facts' })).toHaveTextContent('2 separate lines');
  expect(screen.queryByText('MYR 999')).not.toBeInTheDocument();
  expect(screen.getByText('Financial data redacted by source authorization.')).toBeInTheDocument();
});
