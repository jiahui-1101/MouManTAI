import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../../shared/auth';
import { PortfolioDemoDashboard } from './PortfolioDemoDashboard';

const ref = 'a'.repeat(64);
const inputs = {
  tenant_id: 'tenant_demo_01', actor_id: 'user_owner_01', snapshot_ref: ref,
  source: 'persisted://postgresql/p4_orders+resource_stocks+portfolio_demo_planning', integration_mode: 'SYNTHETIC', evidence_tier: 'DEMO-ONLY',
  total_orders: 1, eligible_orders: 1, excluded_orders: [], planning_data_available: true,
  planning_horizon: { from: '2026-10-23', to: '2026-11-30', max_units: '400', unit: 'pcs', provenance: 'DEMO_ONLY' },
  orders: [{ id: 'ORDER-A', received_at: '2026-10-01T00:00:00Z', requested_delivery_at: '2026-11-01T00:00:00Z',
    lifecycle_status: 'UNKNOWN', items: [{ sku: 'SKU-A', quantity: '6', unit: 'pcs' }], evidence_refs: [] }],
  stocks: [{ resource_id: 'MAT-A', unit: 'pcs', free: '10', total: '10', reserved: '0', snapshot_version: 1 }], limitations: [],
};
const scenario = (strategy: string) => ({ strategy, status: 'COMPUTED_SIMULATION', reason_codes: [],
  allocations: [{ order_id: 'ORDER-A', customer_display_name: 'Demo Customer', items: [{sku:'SKU-A',quantity:'6',unit:'pcs'}], membership: 'ALLOCATE', reason_code: 'WITHIN_DEMO_RESOURCE_AND_CAPACITY_LIMITS', requested_delivery_at: '2026-11-01T00:00:00Z',
    resource_usage: { 'MAT-A': '6' }, sequence: 1 }], allocated_count: 1, deferred_count: 0, allocation_rate: '1', units_allocated: '6',
  remaining_resources: { 'MAT-A': '4' }, resource_consumed:{'MAT-A':'6'}, capacity_used:'6',capacity_total:'400',near_expiry_consumed:{'MAT-A':'6'}, contribution: strategy === 'PROFIT' ? '30' : '30',
  candidate_sequence: ['ORDER-A'], schedule_status: 'SEQUENCE_ONLY_NO_COMPLETION_TIME' });

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AuthProvider initialTenantId="tenant_demo_01" initialActorId="user_owner_01">
    <MemoryRouter><PortfolioDemoDashboard /></MemoryRouter></AuthProvider></QueryClientProvider>);
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('automatically loads persisted orders, computes all strategies, and displays allocation trade-offs', async () => {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => new Response(JSON.stringify(url.endsWith('/inputs') ? inputs : {
    tenant_id: inputs.tenant_id, actor_id: inputs.actor_id, snapshot_ref: ref,
    assumptions_provenance: 'SEEDED_DEMO_ONLY', validation_status: 'UNVERIFIED_BY_P2', read_only: true,
    orders_considered: ['ORDER-A'], scenarios: ['FCFS', 'PROFIT', 'EXPIRY_AWARE'].map(scenario), limitations: [],
  }), { status: 200 }));
  vi.stubGlobal('fetch', fetch); mount();
  expect(await screen.findAllByRole('link', { name: 'ORDER-A' })).toHaveLength(2);
  expect(screen.getAllByRole('link', { name: 'ORDER-A' })[0]).toHaveAttribute('href', '/orders/ORDER-A');
  expect(await screen.findByRole('region', { name: 'Strategy comparison matrix' })).toBeInTheDocument();
  expect(screen.getByText('Demo Planning Simulation')).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Simulation assumptions' })).not.toBeInTheDocument();
  const post = fetch.mock.calls.find(call => call[0].endsWith('/compare'))!;
  expect(post[0]).toBe('/v1/planning/portfolio/compare');
  expect(post[1]?.method).toBe('POST');
  expect(new Headers(post[1]?.headers).get('X-Tenant-ID')).toBe('tenant_demo_01');
  expect(new Headers(post[1]?.headers).get('X-Actor-ID')).toBe('user_owner_01');
  expect(JSON.parse(String(post[1]?.body))).toEqual({ snapshot_ref: ref });
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Profit-first' }));
  expect(screen.getByRole('region', { name: 'Order allocation details' })).toHaveTextContent('Profit-first allocation details');
  expect(screen.getAllByText('MYR 30 · demo').length).toBeGreaterThan(0);
  expect(screen.getByText(/not verified production commitments/)).toBeInTheDocument();
  const previousCalls = fetch.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh portfolio comparison' }));
  await waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThanOrEqual(previousCalls + 2));
});

it('fails closed on an identity-mismatched input response', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...inputs, actor_id: 'different' }), { status: 200 })));
  mount();
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('identity or schema mismatch'));
  expect(screen.queryByRole('link', { name: 'ORDER-A' })).not.toBeInTheDocument();
});
