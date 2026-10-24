import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, useAuth } from '../../shared/auth';
import { ApiError } from '../../shared/api';
import { PortfolioComparisonPage } from './PortfolioComparisonPage';
import { portfolioFixture, portfolioWithExpiryFixture, portfolioTestNow } from './portfolioTest.fixtures';
import type { PortfolioSnapshot, PortfolioSource } from './portfolioTypes';

const sourceFor = (data = portfolioFixture()): PortfolioSource => ({ cacheKey: 'test-only', load: vi.fn().mockResolvedValue(data) });
function ContextControls() { const auth = useAuth(); return <>
  <button onClick={() => auth.setTenantId('other-tenant')}>Switch test tenant</button>
  <button onClick={() => auth.setActorId('user_staff_01')}>Switch test actor</button></>; }
function setup(source?: PortfolioSource) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><AuthProvider initialTenantId="test-tenant" initialActorId="user_owner_01">
    <MemoryRouter><ContextControls /><PortfolioComparisonPage source={source} /></MemoryRouter></AuthProvider></QueryClientProvider>);
}
beforeEach(() => { vi.spyOn(Date, 'now').mockReturnValue(portfolioTestNow); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('Portfolio Comparison states and read safety', () => {
  it('settles with an advancing clock instead of repainting continuously or rereading the source', async () => {
    let ticks = 0;
    vi.spyOn(Date, 'now').mockImplementation(() => {
      if (++ticks > 150) throw new Error('Portfolio clock did not settle');
      return portfolioTestNow + ticks;
    });
    const source = sourceFor(); setup(source);
    await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    const settled = ticks;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); });
    expect(ticks - settled).toBeLessThan(12); expect(source.load).toHaveBeenCalledTimes(1);
  });
  it('reads persisted inputs by default without fabricating strategies on API failure', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); setup();
    expect(screen.getByRole('heading', { name: 'Portfolio Comparison' })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith('/v1/planning/portfolio/inputs', expect.any(Object));
  });
  it('shows cancellable loading', () => {
    let signal: AbortSignal | undefined;
    const view = setup({ cacheKey: 'pending', load: (_, supplied) => { signal = supplied; return new Promise(() => {}); } });
    expect(screen.getByRole('status')).toHaveTextContent('Loading portfolio'); view.unmount(); expect(signal?.aborted).toBe(true);
  });
  it('shows source-backed cards, comparison, allocations, constraints and honest authority labels', async () => {
    const d = portfolioFixture(); const before = structuredClone(d); const source = sourceFor(d); setup(source);
    expect(await screen.findByRole('table', { name: 'Scenario metrics and comparability' })).toBeInTheDocument();
    const allocations = screen.getByRole('table', { name: 'Proposed scenario membership, not order lifecycle status' });
    for (const membership of ['INCLUDED', 'EXCLUDED', 'DEFERRED']) expect(within(allocations).getAllByText(membership)).toHaveLength(2);
    expect(screen.getAllByText('Source-reported capacity bottleneck')).toHaveLength(2);
    expect(screen.getAllByText(/Supplier availability not independently verified/)).toHaveLength(2);
    expect(screen.getByText(/FCFS describes source-supplied ordering/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'one' })).toHaveAttribute('href', '/orders/one');
    expect(screen.queryByText(/Backend recommendation:/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /accept|reserve|save|submit|send|execute/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Profit candidate/ }));
    expect(screen.queryByRole('article', { name: 'Summary: Profit candidate' })).not.toBeInTheDocument();
    expect(source.load).toHaveBeenCalledTimes(1); expect(d).toEqual(before);
  });
  it('renders an explicitly verified recommendation with source, objective, policy and limitations', async () => {
    const d = portfolioFixture(); d.evidenceTier = 'VALIDATED'; d.integrationMode = 'LIVE'; setup(sourceFor(d));
    expect(await screen.findByRole('heading', { name: 'Backend recommendation: Profit candidate' })).toBeInTheDocument();
    expect(screen.getByText('Source-provided trade-off explanation')).toBeInTheDocument();
    expect(screen.getByText(/Limitations: Source limitation/)).toBeInTheDocument();
  });
  it('withholds the backend Profit recommendation when only its profit metric is redacted', async () => {
    const d = portfolioFixture(); d.evidenceTier = 'VALIDATED'; d.integrationMode = 'LIVE';
    d.scenarios[1].metrics.profit!.state = 'REDACTED';
    d.scenarios[1].metrics.profit!.value = '987654321.99';
    const before = structuredClone(d); setup(sourceFor(d));
    await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    expect(screen.getByRole('article', { name: 'Summary: Profit candidate' })).toHaveTextContent('Redacted');
    expect(screen.queryByRole('heading', { name: 'Backend recommendation: Profit candidate' })).not.toBeInTheDocument();
    expect(screen.getByText(/An authoritative portfolio recommendation is not currently available/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('987654321.99');
    expect(d).toEqual(before);
    expect(screen.queryByRole('button', { name: /accept|reserve|submit|execute/i })).not.toBeInTheDocument();
  });
  it('does not invent scenarios for an empty response', async () => {
    const d = portfolioFixture(); d.scenarios = []; d.orders = []; setup(sourceFor(d));
    expect(await screen.findByRole('heading', { name: 'No source scenarios' })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
  it('shows incomplete metrics and redaction without leaking supplied financial values', async () => {
    const d = portfolioFixture(); d.financialAccess = 'REDACTED'; d.coverage = 'PARTIAL';
    for (const s of d.scenarios) { s.metrics.profit!.value = 'secret-profit-999'; s.metrics.revenue!.value = 'secret-revenue'; }
    setup(sourceFor(d)); await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    expect(screen.getByText(/Partial source coverage/)).toBeInTheDocument();
    expect(screen.getAllByText('Redacted').length).toBeGreaterThan(0); expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0);
    expect(document.body).not.toHaveTextContent('secret-profit'); expect(document.body).not.toHaveTextContent('secret-revenue');
  });
  it.each(['STALE', 'UNKNOWN'] as const)('withholds %s data and recommendations', async freshness => {
    const d = portfolioFixture(); d.freshness = freshness; setup(sourceFor(d));
    expect(await screen.findByRole('heading', { name: 'Current verified snapshot unavailable' })).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument(); expect(document.body).not.toHaveTextContent('Synthetic customer');
  });
  it('withholds snapshot version conflict', async () => {
    const d = portfolioFixture(); d.currentVersion = '8'; setup(sourceFor(d));
    expect(await screen.findByRole('heading', { name: 'This record has changed' })).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('withholds request version mismatch using shared conflict banner', async () => {
    const d = portfolioFixture(); d.scenarios[0].allocations[0].requestVersion = '3'; setup(sourceFor(d));
    expect(await screen.findByRole('heading', { name: 'This record has changed' })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('Synthetic customer');
  });
  it.each([401, 403, 409])('handles HTTP %s without raw errors or stale financial data', async status => {
    const source = sourceFor(); vi.mocked(source.load).mockRejectedValue(new ApiError(status, 'TEST', 'private-server-detail')); setup(source);
    expect(await screen.findByRole('alert')).toBeInTheDocument(); expect(document.body).not.toHaveTextContent('private-server-detail');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('retries only an explicit safe read after network failure', async () => {
    const source = sourceFor(); vi.mocked(source.load).mockRejectedValueOnce(new TypeError('Failed to fetch')); setup(source);
    expect(await screen.findByRole('heading', { name: 'Connection problem' })).toBeInTheDocument();
    expect(source.load).toHaveBeenCalledTimes(1); fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByRole('table', { name: 'Scenario metrics and comparability' }); expect(source.load).toHaveBeenCalledTimes(2);
  });
  it('hides previous results during refresh and after permission revocation', async () => {
    const source = sourceFor(); setup(source); await screen.findByRole('link', { name: 'one' });
    let reject!: (e: Error) => void; vi.mocked(source.load).mockImplementationOnce(() => new Promise((_, failure) => { reject = failure; }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh portfolio' }));
    await waitFor(() => expect(screen.queryByRole('table')).not.toBeInTheDocument());
    await act(async () => reject(new ApiError(403, 'FORBIDDEN', 'private')));
    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('Synthetic customer');
  });
  it.each(['Switch test tenant', 'Switch test actor'])('clears previous data after %s and rejects wrong scoped response', async label => {
    const source = sourceFor(); setup(source); await screen.findByRole('link', { name: 'one' });
    fireEvent.click(screen.getByRole('button', { name: label })); await screen.findByRole('alert');
    expect(screen.queryByRole('table')).not.toBeInTheDocument(); expect(document.body).not.toHaveTextContent('Synthetic customer');
    expect(source.load).toHaveBeenCalledTimes(2);
  });
  it('ignores a late old-tenant response and aborts its signal', async () => {
    let resolve!: (d: PortfolioSnapshot) => void; let signal!: AbortSignal;
    const source: PortfolioSource = { cacheKey: 'late-test', load: vi.fn().mockImplementationOnce((_, s) => {
      signal = s; return new Promise(done => { resolve = done; }); }).mockRejectedValue(new ApiError(403, 'FORBIDDEN', 'private')) };
    setup(source); fireEvent.click(screen.getByRole('button', { name: 'Switch test tenant' }));
    await screen.findByRole('heading', { name: 'Access denied' }); expect(signal.aborted).toBe(true);
    await act(async () => resolve(portfolioFixture())); expect(document.body).not.toHaveTextContent('Synthetic customer');
  });
  it('expires visible results while idle without a refresh', async () => {
    const d = portfolioFixture(); d.expiresAt = new Date(portfolioTestNow + 100).toISOString(); d.recommendation = undefined;
    setup(sourceFor(d)); await screen.findByRole('link', { name: 'one' });
    vi.spyOn(Date, 'now').mockReturnValue(portfolioTestNow + 101);
    expect(await screen.findByRole('heading', { name: 'Current verified snapshot unavailable' })).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('invalidates the recommendation first and the snapshot later while idle', async () => {
    const d = portfolioFixture(); d.evidenceTier = 'VALIDATED'; d.integrationMode = 'LIVE';
    d.recommendation!.expiresAt = new Date(portfolioTestNow + 150).toISOString();
    d.expiresAt = new Date(portfolioTestNow + 350).toISOString();
    setup(sourceFor(d)); await screen.findByRole('heading', { name: 'Backend recommendation: Profit candidate' });
    vi.spyOn(Date, 'now').mockReturnValue(portfolioTestNow + 151);
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Backend recommendation: Profit candidate' })).not.toBeInTheDocument());
    expect(screen.getByRole('table', { name: 'Scenario metrics and comparability' })).toBeInTheDocument();
    vi.spyOn(Date, 'now').mockReturnValue(portfolioTestNow + 351);
    expect(await screen.findByRole('heading', { name: 'Current verified snapshot unavailable' })).toBeInTheDocument();
  });
  it('shows unavailable allocations and encodes detail links without inferring membership', async () => {
    const d = portfolioFixture(); d.orders = [{ id: 'request/one', requestVersion: '2', evidence: ['synthetic-request'] }];
    for (const s of d.scenarios) { s.allocations = []; s.constraints = []; }
    setup(sourceFor(d)); const link = await screen.findByRole('link', { name: 'request/one' });
    expect(link).toHaveAttribute('href', '/orders/request%2Fone');
    expect(screen.getAllByText('Allocation evidence unavailable')).toHaveLength(2);
    expect(screen.getAllByText(/empty list does not prove unconstrained/)).toHaveLength(2);
  });
});

describe('Source-supplied strategy availability', () => {
  it.each([
    ['FCFS'], ['PROFIT'], ['EXPIRY'], ['FCFS', 'PROFIT'], ['FCFS', 'EXPIRY'], ['PROFIT', 'EXPIRY'], ['EXPIRY', 'FCFS', 'PROFIT'],
  ])('distinguishes only the returned strategy set %j without reordering or generating scenarios', async (...strategies: string[]) => {
    const data = portfolioWithExpiryFixture();
    data.scenarios = strategies.map(strategy => data.scenarios.find(s => s.strategy === strategy)!);
    const before = structuredClone(data); setup(sourceFor(data));
    await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    for (const [strategy, label] of [['FCFS', 'FCFS'], ['PROFIT', 'Profit'], ['EXPIRY', 'Expiry-aware']]) {
      const card = screen.getByRole('article', { name: `Availability: ${label}` });
      expect(card).toHaveTextContent(strategies.includes(strategy) ? 'Returned by source · 1 scenario.' : 'Not provided in this snapshot');
      if (!strategies.includes(strategy)) expect(card).toHaveTextContent('The source supplied no reason');
    }
    expect(screen.getAllByRole('checkbox').map(input => input.closest('label')?.textContent))
      .toEqual(data.scenarios.map(s => `${s.label}${s.strategy} · version ${s.version}`));
    expect(screen.getAllByRole('article', { name: /^Summary:/ }).map(card => within(card).getByRole('heading').textContent))
      .toEqual(data.scenarios.map(s => s.label));
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    expect(screen.queryByRole('article', { name: `Summary: ${data.scenarios[0].label}` })).not.toBeInTheDocument();
    expect(screen.getByRole('article', { name: `Availability: ${data.scenarios[0].strategy === 'EXPIRY' ? 'Expiry-aware' : data.scenarios[0].strategy === 'PROFIT' ? 'Profit' : 'FCFS'}` })).toHaveTextContent('Returned by source');
    expect(data).toEqual(before);
  });
  it('keeps empty snapshots empty while marking all three strategies not provided', async () => {
    const d = portfolioFixture(); d.scenarios = []; d.orders = []; setup(sourceFor(d));
    await screen.findByRole('heading', { name: 'No source scenarios' });
    expect(within(screen.getByRole('region', { name: 'Strategy availability' })).getAllByText(/Not provided in this snapshot/)).toHaveLength(3);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
  it('does not describe stale, failed or unauthorized snapshots as strategies omitted by the source', async () => {
    const d = portfolioWithExpiryFixture(); d.freshness = 'STALE'; setup(sourceFor(d));
    await screen.findByRole('heading', { name: 'Current verified snapshot unavailable' });
    const availability = screen.getByRole('region', { name: 'Strategy availability' });
    expect(within(availability).getAllByText(/Not verified/)).toHaveLength(3);
    expect(availability).not.toHaveTextContent('Returned by source'); expect(availability).not.toHaveTextContent('Not provided');
  });
  it.each(['REDACTED', 'UNKNOWN'] as const)('distinguishes returned Profit scenarios from %s financial visibility', async financialAccess => {
    const d = portfolioWithExpiryFixture(); d.financialAccess = financialAccess; setup(sourceFor(d));
    await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    const card = screen.getByRole('article', { name: 'Availability: Profit' });
    expect(card).toHaveTextContent('Returned by source');
    expect(card).toHaveTextContent(financialAccess === 'REDACTED' ? 'Financial values are redacted' : 'Financial authorization is unknown');
    expect(screen.queryByRole('heading', { name: /^Backend recommendation:/ })).not.toBeInTheDocument();
  });
  it('retains partial coverage, invalid validation and incomplete metric explanations without asserting usable results', async () => {
    const d = portfolioWithExpiryFixture(); d.coverage = 'PARTIAL';
    d.scenarios[1].validation = 'VALIDATION_MISMATCH'; d.scenarios[2].metrics.profit!.financialModelComplete = false;
    setup(sourceFor(d)); await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    expect(screen.getByRole('article', { name: 'Availability: Profit' })).toHaveTextContent('Validation is incomplete or mismatched');
    expect(screen.getByRole('region', { name: 'Strategy availability' })).toHaveTextContent('This response has partial coverage');
    expect(screen.getByRole('article', { name: 'Summary: Expiry-aware candidate' })).toHaveTextContent('Unknown');
    expect(screen.queryByRole('heading', { name: /^Backend recommendation:/ })).not.toBeInTheDocument();
  });
  it('preserves source recommendation and B-01 per-metric redaction while the strategy remains returned', async () => {
    const d = portfolioWithExpiryFixture(); d.evidenceTier = 'VALIDATED'; d.integrationMode = 'LIVE';
    const source = sourceFor(d); setup(source);
    await screen.findByRole('heading', { name: 'Backend recommendation: Profit candidate' });
    const hidden = structuredClone(d); hidden.scenarios[1].metrics.profit!.state = 'REDACTED';
    vi.mocked(source.load).mockResolvedValueOnce(hidden);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh portfolio' }));
    await waitFor(() => expect(screen.getByRole('article', { name: 'Availability: Profit' })).toHaveTextContent('One or more profit metrics are redacted'));
    expect(screen.queryByRole('heading', { name: /^Backend recommendation:/ })).not.toBeInTheDocument();
  });
  it('hides returned strategy status throughout pending refresh and denied recovery', async () => {
    const source = sourceFor(portfolioWithExpiryFixture()); setup(source);
    await screen.findByRole('table', { name: 'Scenario metrics and comparability' });
    let reject!: (error: Error) => void;
    vi.mocked(source.load).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh portfolio' }));
    await waitFor(() => expect(screen.getByRole('region', { name: 'Strategy availability' })).not.toHaveTextContent('Returned by source'));
    await act(async () => reject(new ApiError(403, 'FORBIDDEN', 'private')));
    await screen.findByRole('alert');
    expect(within(screen.getByRole('region', { name: 'Strategy availability' })).getAllByText(/Not verified/)).toHaveLength(3);
  });
});


describe('Smart portfolio dashboard selection', () => {
 it('changes the selected strategy, allocation and explanation without fetching or mutating the source', async () => {
  const data=portfolioWithExpiryFixture();const before=structuredClone(data);const source=sourceFor(data);setup(source);
  await screen.findByRole('table',{name:'Selected strategy proposed allocations'});const button=screen.getByRole('button',{name:'Select Profit strategy'});button.focus();expect(button).toHaveFocus();fireEvent.click(button);
  expect(screen.getByRole('heading',{name:'Selected Strategy: Profit candidate'})).toBeInTheDocument();expect(button).toHaveAttribute('aria-pressed','true');
  let table=screen.getByRole('table',{name:'Selected strategy proposed allocations'});
  expect(within(within(table).getByRole('rowheader',{name:/one/}).closest('tr')!).getByText('Exclude')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Select Expiry-aware strategy'}));
  table=screen.getByRole('table',{name:'Selected strategy proposed allocations'});expect(within(table).getAllByText('Defer')).toHaveLength(3);
  expect(screen.getByRole('heading',{name:'Selected Strategy: Expiry-aware candidate'})).toBeInTheDocument();
  expect(source.load).toHaveBeenCalledTimes(1);expect(data).toEqual(before);
 });
 it('keeps selected strategy detail independent when every comparison checkbox is cleared', async () => {
  setup(sourceFor());await screen.findByRole('table',{name:'Selected strategy proposed allocations'});
  for(const checkbox of screen.getAllByRole('checkbox')) fireEvent.click(checkbox);
  expect(screen.queryByRole('table',{name:'Scenario metrics and comparability'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Select Profit strategy'}));
  expect(screen.getByRole('heading',{name:'Selected Strategy: Profit candidate'})).toBeInTheDocument();
  expect(screen.getByRole('table',{name:'Selected strategy proposed allocations'})).toBeInTheDocument();
 });
 it.each(['INFEASIBLE','MODEL_INVALID','SOLVER_UNAVAILABLE'])('withholds positive allocation and profit for a %s solver',async status=>{
  const data=portfolioFixture();data.scenarios[0].solverStatus=status;data.scenarios[0].metrics.profit!.value='7654321';setup(sourceFor(data));
  await screen.findByRole('table',{name:'Scenario metrics and comparability'});
  expect(screen.queryByRole('table',{name:'Selected strategy proposed allocations'})).not.toBeInTheDocument();
  expect(document.body).not.toHaveTextContent('7654321');expect(screen.getByText(/Allocation withheld/)).toBeInTheDocument();
 });
});
