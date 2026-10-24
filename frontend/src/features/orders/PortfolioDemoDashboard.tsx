import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { useAuth } from '../../shared/auth';
import { loadPlanningInputs, comparePlanning, type PlanningInputs, type PlanningResult } from './portfolioSimulationApi';
import { PortfolioCalendarContext } from './portfolioCalendarContext';
import { OrderQueueIcon } from './OrderQueueIcon';
import './portfolio.css';

const titles = { FCFS: 'FCFS', PROFIT: 'Profit-first', EXPIRY_AWARE: 'Expiry-aware' } as const;
type Strategy = keyof typeof titles;
function displayDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Date unavailable' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date);
}
function amount(value: string | null | undefined, unit = '') { return value == null ? 'Unavailable' : `${value}${unit ? ` ${unit}` : ''}`; }

export function PortfolioDemoDashboard() {
  const { authHeaders: auth } = useAuth();
  const [selected, setSelected] = useState<Strategy>('FCFS');
  const query = useQuery({
    queryKey: ['planning', 'portfolio-demo', auth.tenantId, auth.actorId],
    queryFn: async ({ signal }) => {
      const inputs = await loadPlanningInputs(auth, signal) as PlanningInputs & { total_orders?: number; eligible_orders?: number; excluded_orders?: { id: string; reason_code: string }[]; planning_horizon?: { from: string; to: string; max_units: string; unit: string; provenance: string } | null };
      const result = await comparePlanning(auth, { snapshot_ref: inputs.snapshot_ref }, signal);
      return { inputs, result };
    }, retry: false, gcTime: 0, staleTime: 0,
  });
  const refresh = () => { void query.refetch(); };
  const current = query.data?.result.scenarios.find(s => s.strategy === selected);
  const planning = query.data?.inputs;
  const scenarios = query.data?.result.scenarios ?? [];
  const allocated = (s: PlanningResult['scenarios'][number]) => s.allocations.filter(a => a.membership === 'ALLOCATE').length;
  const deferred = (s: PlanningResult['scenarios'][number]) => s.allocations.filter(a => a.membership === 'DEFER').length;
  return <section className="portfolio-comparison pc-workspace" aria-labelledby="pc-title">
    <div className="pc-top-bar"><Link to="/orders" className="pc-back-link" aria-label="Back to Order Decision Queue">← Back</Link></div>
    <header className="pc-header"><div className="pc-title-row"><h1 id="pc-title">Portfolio Comparison</h1><span className="pc-demo-badge">Demo Planning Simulation</span></div>
      <div className="pc-header-actions">
        <Link to="/orders/calendar" className="pc-header-nav-link" aria-label="Production & Delivery Calendar">
          Production &amp; Delivery Calendar
        </Link>
        <button type="button" className="btn btn-secondary pc-refresh-btn" onClick={refresh} disabled={query.isFetching} aria-label="Refresh portfolio comparison">
          <OrderQueueIcon name="refresh" /> Refresh
        </button>
      </div></header>
    <PortfolioCalendarContext />
    {query.isFetching && <p role="status">Loading orders and calculating strategies…</p>}
    {query.isError && <div role="alert"><h2>Portfolio comparison unavailable</h2><p>{query.error instanceof Error ? query.error.message : 'The database-backed comparison could not be loaded.'}</p><button className="btn btn-secondary" onClick={refresh}>Retry</button></div>}
    {planning && <>
      <section className="pc-overview-grid" aria-label="Portfolio overview">
        <article className="pc-overview-card"><span>Total orders</span><strong>{planning.total_orders ?? planning.orders.length}</strong></article>
        <article className="pc-overview-card"><span>Eligible orders</span><strong>{planning.eligible_orders ?? planning.orders.length}</strong></article>
        <article className="pc-overview-card"><span>Excluded from new allocation</span><strong>{planning.excluded_orders?.length ?? 0}</strong></article>
        <article className="pc-overview-card"><span>Available resources</span><strong>{planning.stocks.length}</strong></article>
        {planning.planning_horizon && <article className="pc-overview-card"><span>Demo capacity</span><strong>{planning.planning_horizon.max_units} {planning.planning_horizon.unit}</strong><small>{displayDate(planning.planning_horizon.from)} – {displayDate(planning.planning_horizon.to)}</small></article>}
      </section>
      <details className="pc-card pc-source-details" open><summary>Orders and available stock</summary>
        <p>Stock and lot records are seeded demo inputs and reconcile to the existing inventory snapshot.</p>
        <div className="pc-scroll" role="region" tabIndex={0} aria-label="Portfolio input summary"><table><thead><tr><th>Order</th><th>Product / quantity</th><th>Requested delivery</th></tr></thead><tbody>
          {planning.orders.map(o => <tr key={o.id}><th scope="row"><Link to={`/orders/${encodeURIComponent(o.id)}`}>{o.id}</Link></th><td>{o.items.map(i => `${i.quantity} ${i.unit} ${i.sku}`).join(', ')}</td><td>{displayDate(o.requested_delivery_at)}</td></tr>)}</tbody></table></div>
        <p>{planning.stocks.map(s => `${s.resource_id}: ${s.free} ${s.unit}`).join(' · ')}</p>
      </details>
      {planning.orders.length === 0 && <p role="status">No eligible orders are available for comparison.</p>}
      {!!planning.excluded_orders?.length && <p role="note">Excluded orders: {planning.excluded_orders.map(o => `${o.id} (${o.reason_code})`).join(', ')}</p>}
      {scenarios.length > 0 && <>
        <section className="pc-cards pc-demo-strategy-cards" aria-label="Portfolio strategies">{scenarios.map(s => <article key={s.strategy} className={`pc-card pc-demo-${s.strategy.toLowerCase()}`}>
          <h2>{titles[s.strategy]}</h2><p>{s.status === 'COMPUTED_SIMULATION' ? 'Computed using seeded demo inputs' : 'Required data unavailable'}</p>
          <dl><div><dt>Allocated orders</dt><dd>{s.status === 'COMPUTED_SIMULATION' ? allocated(s) : 'Unavailable'}</dd></div><div><dt>Deferred orders</dt><dd>{s.status === 'COMPUTED_SIMULATION' ? deferred(s) : 'Unavailable'}</dd></div>
            <div><dt>Units allocated</dt><dd>{amount(s.units_allocated)}</dd></div><div><dt>Expected contribution</dt><dd>{s.contribution === null ? 'Unavailable' : `MYR ${s.contribution} · demo`}</dd></div>
            <div><dt>Capacity used</dt><dd>{amount(s.capacity_used)} / {amount(s.capacity_total)}</dd></div>
          </dl>{s.reason_codes.length > 0 && <p>{s.reason_codes.join(', ')}</p>}
          <button type="button" className="btn btn-secondary" aria-pressed={selected === s.strategy} onClick={() => setSelected(s.strategy)}>Inspect {titles[s.strategy]}</button>
        </article>)}</section>
        <section className="pc-card" aria-label="Strategy comparison matrix"><h2>Strategy comparison</h2><div className="pc-scroll" role="region" tabIndex={0} aria-label="Comparison metrics"><table>
          <thead><tr><th>Metric</th>{scenarios.map(s => <th key={s.strategy}>{titles[s.strategy]}</th>)}</tr></thead><tbody>
            <tr><th scope="row">Allocated orders</th>{scenarios.map(s => <td key={s.strategy}>{s.status === 'COMPUTED_SIMULATION' ? allocated(s) : 'Unavailable'}</td>)}</tr>
            <tr><th scope="row">Deferred orders</th>{scenarios.map(s => <td key={s.strategy}>{s.status === 'COMPUTED_SIMULATION' ? deferred(s) : 'Unavailable'}</td>)}</tr>
            <tr><th scope="row">Units allocated</th>{scenarios.map(s => <td key={s.strategy}>{amount(s.units_allocated)}</td>)}</tr>
            <tr><th scope="row">Contribution margin</th>{scenarios.map(s => <td key={s.strategy}>{s.contribution === null ? 'Unavailable' : `MYR ${s.contribution} · demo`}</td>)}</tr>
            <tr><th scope="row">Materials consumed</th>{scenarios.map(s => <td key={s.strategy}>{s.resource_consumed ? Object.entries(s.resource_consumed).map(([k,v])=>`${k} ${v}`).join(', ') : 'Unavailable'}</td>)}</tr>
            <tr><th scope="row">Remaining stock</th>{scenarios.map(s => <td key={s.strategy}>{s.remaining_resources ? Object.entries(s.remaining_resources).map(([k,v])=>`${k} ${v}`).join(', ') : 'Unavailable'}</td>)}</tr>
            <tr><th scope="row">Capacity used</th>{scenarios.map(s => <td key={s.strategy}>{amount(s.capacity_used)} / {amount(s.capacity_total)}</td>)}</tr>
            <tr><th scope="row">Near-expiry stock consumed</th>{scenarios.map(s => <td key={s.strategy}>{s.near_expiry_consumed && Object.keys(s.near_expiry_consumed).length ? Object.entries(s.near_expiry_consumed).map(([k,v])=>`${k} ${v}`).join(', ') : '0'}</td>)}</tr>
          </tbody></table></div></section>
        {current && <section className="pc-card" aria-label="Order allocation details"><h2>{titles[current.strategy]} allocation details</h2><p>Candidate recommendation only. Manager review does not accept orders or reserve inventory.</p>
          <div className="pc-scroll" role="region" tabIndex={0} aria-label="Order allocation decisions"><table><thead><tr><th>Order</th><th>Customer / product</th><th>Quantity</th><th>Requested delivery</th><th>Recommendation</th><th>Reason</th></tr></thead><tbody>
            {current.allocations.map(a=><tr key={a.order_id}><th scope="row"><Link to={`/orders/${encodeURIComponent(a.order_id)}`}>{a.order_id}</Link></th><td>{a.customer_display_name} · {a.items.map(i=>i.sku).join(', ')}</td><td>{a.items.map(i=>`${i.quantity} ${i.unit}`).join(', ')}</td><td><strong>{displayDate(a.requested_delivery_at)}</strong></td><td>{a.membership}</td><td>{a.reason_code}</td></tr>)}</tbody></table></div>
          {current.near_expiry_consumed && Object.keys(current.near_expiry_consumed).length > 0 && <p>Near-expiry material use: {Object.entries(current.near_expiry_consumed).map(([k,v])=>`${k} ${v}`).join(', ')}</p>}
        </section>}
      </>}
      <p className="pc-demo-footnote">Illustrative development data. Results are not verified production commitments or confirmed schedules.</p>
    </>}
  </section>;
}
