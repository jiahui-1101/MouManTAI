import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ApiError } from '../../shared/api';
import { useAuth } from '../../shared/auth';
import { Button, ContentCard, StatusBadge } from '../../shared/ui';
import { OrderQueueUnavailableError, unavailableOrderQueueSource, type OrderQueueSource } from './api';
import type { OrderQueueItem, QueueFilters, StatusView } from './types';
import { profitText, selectOrders, shown, timestamp } from './queue';
import { useQueuePreferences } from './useQueuePreferences';
import { OrderQueueSummary } from './OrderQueueSummary';
import { OrderQueueIcon } from './OrderQueueIcon';
import './orders.css';
import { demoOrderQueueSource, ordersDemoEnabled } from './demoSource';
import { dbOrderQueueSource, ordersPersistedEnabled } from './dbSource';

const defaultOrderQueueSource = (): OrderQueueSource => {
  if (ordersPersistedEnabled()) return dbOrderQueueSource;
  if (ordersDemoEnabled()) return demoOrderQueueSource;
  return unavailableOrderQueueSource;
};

const statusViews: { value: StatusView; label: string }[] = [
  { value: 'ALL', label: 'All Statuses' },
  { value: 'PENDING_ACCEPTANCE', label: 'Pending acceptance' },
  { value: 'ACCEPTED', label: 'Accepted' }, { value: 'REJECTED', label: 'Rejected' },
  { value: 'OTHER', label: 'Other / unknown' },
];
const tiers: Record<OrderQueueItem['evidenceTier'], string> = {
  VERIFIED_FACT: 'Verified fact', CLAIM: 'Customer / supplier claim',
  COMPUTED_ASSESSMENT: 'Computed assessment', SCENARIO: 'Scenario',
  SYNTHETIC: 'DEMO-ONLY / SYNTHETIC', UNKNOWN: 'Not verified',
};

function OrderRow({ order }: { order: OrderQueueItem }) {
  const feasibility = ['FEASIBLE', 'CONDITIONAL', 'INFEASIBLE', 'UNKNOWN'].includes(order.feasibility ?? '')
    ? order.feasibility : 'UNKNOWN';
  const statusTone = order.status === 'ACCEPTED' ? 'success' : order.status === 'REJECTED' ? 'danger' : order.status === 'PENDING_ACCEPTANCE' ? 'warning' : 'muted';
  return <tr>
    <th scope="row"><strong className="oq-order-id">{order.id}</strong><span className="oq-muted">{shown(order.customer)}</span>
      <span className={`oq-badge oq-tier-${order.evidenceTier}`}>{tiers[order.evidenceTier] ?? 'Not verified'}</span>
      <small>Priority: {shown(order.priority)}</small>
      <details className="oq-row-details"><summary>Evidence &amp; order details</summary>
        <small>Original received</small><span>{timestamp(order.receivedAt)}</span>
        <small>Information completed</small><span>{timestamp(order.completedAt)}</span>
        <small>Channel: {shown(order.channel)}</small><small>Size: {shown(order.size)}</small>
        {order.lines?.length ? <ul>{order.lines.map((line, index) => <li key={index}>{shown(line.product)} · {shown(line.quantity)} {line.unit ?? ''}</li>)}</ul> : <small>Products: Not available</small>}
        <small>Method: {shown(order.fulfilment)}</small>
        <dl><dt>Stock</dt><dd>{shown(order.stockReason)}</dd><dt>Expiry</dt><dd>{shown(order.expiryReason)}</dd><dt>Capacity</dt><dd>{shown(order.capacityReason)}</dd></dl>
        <small>Backend recommendation</small><span>{shown(order.recommendation)}</span>
        <small>Price source: {shown(order.profit?.priceSource)}</small><small>Cost source: {shown(order.profit?.costSource)}</small>
        <small>Cost coverage: {order.profit?.costComplete === true ? 'Complete (source-reported)' : order.profit?.costComplete === false ? 'Incomplete' : 'Unknown'}</small>
      </details>
    </th>
    <td className="oq-deadline">{timestamp(order.deadline)}<small>MYT · source deadline</small></td>
    <td><span className={`oq-badge oq-tone-${statusTone}`}>{order.status?.trim() || 'UNKNOWN'}</span>
      {order.status === 'PENDING_ACCEPTANCE' && <small>Request only · no reservation</small>}</td>
    <td><StatusBadge dimension="feasibility" state={feasibility ?? 'UNKNOWN'} />
      {feasibility === 'UNKNOWN' && <small>Awaiting assessment / not verified</small>}</td>
    <td><span className="oq-risk-label">{shown(order.risk)}</span><small>Source-reported · not a local risk score</small></td>
    <td className="oq-profit">{profitText(order.profit)}<small>Provenance in order details</small></td>
    <td><Link className="oq-detail-link" aria-label={`View Details for ${order.id}`} to={`/orders/${encodeURIComponent(order.id)}`}>View Details<OrderQueueIcon name="arrow" /></Link></td>
  </tr>;
}

export interface OrderQueuePageProps { source?: OrderQueueSource }

/** Presentation-only dashboard. Source authorization and identity-scoped query isolation are unchanged. */
export function OrderQueuePage({ source = defaultOrderQueueSource() }: OrderQueuePageProps = {}) {
  const { authHeaders: auth } = useAuth();
  const { filters, setFilters, analysis, setAnalysis, resetFilters } = useQueuePreferences(auth);
  const query = useQuery({
    queryKey: ['orders', 'queue', source.cacheKey, auth.tenantId, auth.actorId],
    queryFn: ({ signal }) => source.load(auth, signal), retry: false, gcTime: 0,
  });
  const data = !query.isFetching && !query.isError ? query.data : undefined;
  const items = data?.items ?? [];
  const visible = selectOrders(items, filters);
  const update = <K extends keyof QueueFilters>(key: K, value: QueueFilters[K]) => setFilters(current => ({ ...current, [key]: value }));
  const invalidRange = !!filters.from && !!filters.to && filters.from > filters.to;
  const invalidDeadline = !!filters.deadlineFrom && !!filters.deadlineTo && filters.deadlineFrom > filters.deadlineTo;
  const invalid = invalidRange || invalidDeadline;
  const textFilter = (key: 'product' | 'customer', label: string) => <label>{label}<input type="search" value={filters[key]} onChange={e => update(key, e.target.value)} /></label>;
  const operationalFilter = (key: 'channel' | 'priority' | 'risk' | 'size', label: string) => {
    const options = Array.from(new Set(items.map(order => shown(order[key])))).sort();
    const provided = items.some(order => !!order[key]?.trim());
    return <label key={key}>{label}<select value={filters[key]} disabled={!provided && !filters[key]} onChange={e => update(key, e.target.value)}>
      <option value="">{provided ? 'All' : 'Unavailable'}</option>{options.map(option => <option key={option}>{option}</option>)}
      {filters[key] && !options.includes(filters[key]) && <option value={filters[key]}>Saved preference · source unavailable</option>}
    </select></label>;
  };
  const activeLabel = statusViews.find(view => view.value === filters.status)?.label;
  const error = query.error;
  const accessDenied = error instanceof ApiError && [401, 403].includes(error.status);
  const loading = query.isPending || query.isFetching;
  const hasDeadlines = items.some(order => !!order.deadline);
  const hasFeasibility = items.some(order => !!order.feasibility);
  return <section className="order-queue" aria-labelledby="oq-page-title">
    <header className="oq-heading"><div><p className="oq-eyebrow">Orders &amp; planning</p><h1 id="oq-page-title">Orders</h1><p>Manage, evaluate and prioritize customer orders.</p></div>
      <Button variant="secondary" className="oq-refresh" aria-label="Refresh queue" aria-busy={loading} disabled={loading} onClick={() => void query.refetch()}><OrderQueueIcon name="refresh" className={loading ? 'oq-spinning' : ''} />{loading ? 'Refreshing…' : 'Refresh'}</Button>
    </header>
    <OrderQueueSummary data={data} status={filters.status} onStatus={status => update('status', status)} />
    <ContentCard className="oq-workspace" aria-labelledby="oq-title">
      <div className="oq-queue-heading"><div><h2 id="oq-title">Order Decision Queue</h2><p>Inspect source evidence and uncertainty before making a separate order decision.</p></div><span className="oq-readonly"><OrderQueueIcon name="information" />Read only</span></div>
      <div className="oq-toolbar">
        <div className="oq-search"><label htmlFor="oq-search">Search by Order ID or Customer</label><div className="oq-search-control">
          <OrderQueueIcon name="search" /><input id="oq-search" type="search" placeholder="Search by Order ID or Customer..." aria-describedby="oq-search-help" value={filters.search} onChange={e => update('search', e.target.value)} />
          <button type="button" className="oq-clear" aria-label="Clear search" disabled={!filters.search} onClick={() => update('search', '')}>Clear</button>
        </div></div>
        <label className="oq-status">Order Status<select value={filters.status} onChange={e => update('status', e.target.value as StatusView)}>{statusViews.map(view => <option key={view.value} value={view.value}>{view.label}</option>)}</select></label>
        {operationalFilter('risk', 'Risk Level')}
        <label>Sort By<select value={filters.sort} onChange={e => update('sort', e.target.value as QueueFilters['sort'])} aria-describedby="oq-sort-help">
          <option value="FCFS">FCFS · original received</option><option value="DEADLINE">Earliest Deadline</option>
          <option disabled>Highest Priority · ordering contract unavailable</option><option disabled>Highest Risk · ordering contract unavailable</option><option disabled>Estimated Profit · comparable authorized amounts unavailable</option>
        </select></label>
      </div>
      <p id="oq-search-help" className="oq-muted oq-search-help">Search applies only to loaded orders: Order ID and customer display text when supplied by the source.</p>
      <div className="oq-filter-actions"><details className="oq-advanced"><summary><OrderQueueIcon name="filter" />Advanced Filters</summary><div className="oq-filters">
        {textFilter('customer', 'Customer')}{textFilter('product', 'Product')}
        <label>Deadline from (MYT)<input type="date" value={filters.deadlineFrom} disabled={!hasDeadlines && !filters.deadlineFrom} onChange={e => update('deadlineFrom', e.target.value)} /></label>
        <label>Deadline through (MYT)<input type="date" value={filters.deadlineTo} disabled={!hasDeadlines && !filters.deadlineTo} onChange={e => update('deadlineTo', e.target.value)} /></label>
        <label>Received from (MYT)<input type="date" value={filters.from} onChange={e => update('from', e.target.value)} /></label>
        <label>Received through (MYT)<input type="date" value={filters.to} onChange={e => update('to', e.target.value)} /></label>
        {operationalFilter('channel', 'Sales Channel')}{operationalFilter('priority', 'Priority')}{operationalFilter('size', 'Order size')}
        <label>Feasibility Status<select value={filters.feasibility} disabled={!hasFeasibility && !filters.feasibility} onChange={e => update('feasibility', e.target.value)}><option value="">{hasFeasibility ? 'All' : 'Unavailable'}</option>{['FEASIBLE', 'CONDITIONAL', 'INFEASIBLE', 'UNKNOWN'].map(value => <option key={value}>{value}</option>)}</select></label>
      </div><p className="oq-muted">Deadline and feasibility filters require source fields. Quantity range is unavailable: no comparable cross-order unit contract is supplied.</p></details>
        <Button variant="ghost" onClick={resetFilters}>Reset filters</Button>
      </div>
      {invalidRange && <p role="alert">Received from must be on or before Received through.</p>}
      {invalidDeadline && <p role="alert">Deadline from must be on or before Deadline through.</p>}
      <div className="oq-analysis"><label>Analysis view<select value={analysis} onChange={e => setAnalysis(e.target.value)}>
        <option value="QUEUE">Queue ordering · original received (FCFS)</option><option value="FCFS">FCFS portfolio</option><option value="PROFIT">Profit portfolio</option><option value="EXPIRY">Expiry-aware portfolio</option></select></label>
        <p id="oq-sort-help" role="status">{analysis === 'QUEUE' ? `${filters.sort === 'DEADLINE' ? 'Queue sorted by source deadline' : 'Queue sorted by original received time'}, then order ID. Unknown times appear last. No allocation calculated.` : `${analysis === 'EXPIRY' ? 'Expiry-aware' : analysis === 'PROFIT' ? 'Profit' : 'FCFS'} analysis unavailable: requires a verified backend portfolio result and resource snapshot. Queue sorting is independent of portfolio analysis.`}</p>
      </div>
      {!!data && !invalid && visible.length > 0 && <div className="oq-scroll" role="region" aria-label="Order queue table, scroll horizontally" tabIndex={0}><table><caption>{activeLabel} · loaded orders · read only</caption><thead><tr>{['Order / Customer', 'Deadline', 'Status', 'Feasibility', 'Risk', 'Est. Profit', 'Actions'].map(heading => <th key={heading} scope="col">{heading}</th>)}</tr></thead><tbody>{visible.map(order => <OrderRow key={order.id} order={order} />)}</tbody></table></div>}
      <div className="oq-results" aria-live="polite">{data ? <><span>{invalid ? 'Results withheld: check the date range.' : `${visible.length} matching of ${items.length} loaded orders.`} {data.coverage === 'complete' ? 'Source reports a complete snapshot.' : 'Partial snapshot: filters apply only to loaded orders, not the entire tenant.'}</span><span>Source updated: {timestamp(data.asOf)} · Asia/Kuala_Lumpur</span></> : <span>{loading ? 'Reading a fresh order snapshot…' : 'Results unavailable · no verified order snapshot'}</span>}</div>
      {loading ? <div className="oq-state oq-loading" role="status" aria-busy="true"><div className="oq-skeleton" aria-hidden="true"><span /><span /><span /></div><h3>Loading order queue…</h3><p>Previous sensitive results are hidden.</p></div> : error ? <div className="oq-state" role="alert">
        <span className="oq-state-icon"><OrderQueueIcon name={accessDenied ? 'information' : 'unavailable'} /></span>
        <h3>{accessDenied ? 'Order queue access unavailable' : error instanceof OrderQueueUnavailableError ? 'Order queue unavailable' : 'Could not load order queue'}</h3>
        <p>{accessDenied ? 'Your current session cannot read these orders. Check your tenant and permissions.' : error instanceof OrderQueueUnavailableError ? 'Order data is currently unavailable.' : 'The request failed. No order data is shown. Retry to load a fresh snapshot.'}</p>
        {error instanceof OrderQueueUnavailableError && <p className="oq-muted">{error.message}</p>}
        {error instanceof ApiError && error.correlationId && <p>Reference: {error.correlationId}</p>}
        <Button variant="secondary" onClick={() => void query.refetch()}><OrderQueueIcon name="refresh" />Retry</Button>
      </div> : data && (!visible.length || invalid) ? <div className="oq-state" role="status"><span className="oq-state-icon"><OrderQueueIcon name="search" /></span><h3>{invalid ? 'Check the date range' : !items.length && data.coverage === 'complete' ? 'No orders yet' : 'No orders match your filters.'}</h3><p>{invalid ? 'Correct the date range to show matching orders.' : !items.length && data.coverage === 'complete' ? 'The source confirms this order snapshot is empty.' : data.coverage === 'partial' ? 'No matches in the loaded subset. More orders may exist outside this snapshot.' : 'Try another status or reset the search and filters.'}</p></div> : null}
      <p className="oq-notice"><OrderQueueIcon name="information" /><span>Pending acceptance is a request only. Feasibility and recommendations do not accept orders or reserve resources.</span></p>
    </ContentCard>
  </section>;
}
