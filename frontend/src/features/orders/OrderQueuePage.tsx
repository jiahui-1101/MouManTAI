import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ApiError } from '../../shared/api';
import { useAuth } from '../../shared/auth';
import { StatusBadge } from '../../shared/StatusBadge';
import { OrderQueueUnavailableError, unavailableOrderQueueSource, type OrderQueueSource } from './api';
import type { OrderQueueItem, QueueFilters, StatusView } from './types';
import { initialFilters, profitText, selectOrders, shown, timestamp } from './queue';
import './orders.css';

const statusViews: { value: StatusView; label: string }[] = [
  { value: 'PENDING_ACCEPTANCE', label: 'Pending acceptance' },
  { value: 'ACCEPTED', label: 'Accepted' }, { value: 'REJECTED', label: 'Rejected' },
  { value: 'OTHER', label: 'Other / unknown' }, { value: 'ALL', label: 'All statuses' },
];
const tiers: Record<OrderQueueItem['evidenceTier'], string> = {
  VERIFIED_FACT: 'Verified fact', CLAIM: 'Customer / supplier claim',
  COMPUTED_ASSESSMENT: 'Computed assessment', SCENARIO: 'Scenario',
  SYNTHETIC: 'DEMO-ONLY / SYNTHETIC', UNKNOWN: 'Not verified',
};

function OrderRow({ order }: { order: OrderQueueItem }) {
  const feasibility = ['FEASIBLE', 'CONDITIONAL', 'INFEASIBLE', 'UNKNOWN'].includes(order.feasibility ?? '')
    ? order.feasibility : 'UNKNOWN';
  return <tr>
    <th scope="row"><strong>{order.id}</strong><span className="oq-muted">{shown(order.customer)}</span>
      <span className={`oq-badge oq-tier-${order.evidenceTier}`}>{tiers[order.evidenceTier] ?? 'Not verified'}</span></th>
    <td><span className={`oq-badge ${order.status === 'PENDING_ACCEPTANCE' ? 'oq-warning' : ''}`}>
      {order.status?.trim() || 'UNKNOWN'}</span>
      {order.status === 'PENDING_ACCEPTANCE' && <small>Request only · no reservation</small>}
      <small>Priority: {shown(order.priority)}</small><small>Risk: {shown(order.risk)}</small>
      <small>Size: {shown(order.size)}</small></td>
    <td><small>Original received</small><span>{timestamp(order.receivedAt)}</span>
      <small>Information completed</small><span>{timestamp(order.completedAt)}</span>
      <small>Channel: {shown(order.channel)}</small></td>
    <td>{order.lines?.length ? <ul>{order.lines.map((line, index) => <li key={index}>
      {shown(line.product)} · {shown(line.quantity)} {line.unit ?? ''}</li>)}</ul> : 'Not available'}
      <small>Deadline</small>{timestamp(order.deadline)}<small>Method: {shown(order.fulfilment)}</small></td>
    <td><StatusBadge dimension="feasibility" state={feasibility ?? 'UNKNOWN'} />
      {feasibility === 'UNKNOWN' && <small>Awaiting assessment / not verified</small>}
      <dl><dt>Stock</dt><dd>{shown(order.stockReason)}</dd><dt>Expiry</dt><dd>{shown(order.expiryReason)}</dd>
        <dt>Capacity</dt><dd>{shown(order.capacityReason)}</dd></dl>
      <small>Backend recommendation</small>{shown(order.recommendation)}</td>
    <td><span>{profitText(order.profit)}</span><small>Price source: {shown(order.profit?.priceSource)}</small>
      <small>Cost source: {shown(order.profit?.costSource)}</small>
      <small>Cost coverage: {order.profit?.costComplete === true ? 'Complete (source-reported)' :
        order.profit?.costComplete === false ? 'Incomplete' : 'Unknown'}</small></td>
    <td><Link aria-label={`View Details for ${order.id}`} to={`/orders/${encodeURIComponent(order.id)}`}>View Details</Link></td>
  </tr>;
}

export interface OrderQueuePageProps { source?: OrderQueueSource }

/** Requires existing AuthProvider, QueryClientProvider and Router; registers no routes. */
export function OrderQueuePage({ source = unavailableOrderQueueSource }: OrderQueuePageProps = {}) {
  const { authHeaders: auth } = useAuth();
  const [filters, setFilters] = useState<QueueFilters>(initialFilters);
  const [analysis, setAnalysis] = useState('QUEUE');
  const query = useQuery({
    queryKey: ['orders', 'queue', source.cacheKey, auth.tenantId, auth.actorId],
    queryFn: ({ signal }) => source.load(auth, signal),
    retry: false,
  });
  const items = query.data?.items ?? [];
  const visible = selectOrders(items, filters);
  const update = <K extends keyof QueueFilters>(key: K, value: QueueFilters[K]) =>
    setFilters(current => ({ ...current, [key]: value }));
  const invalidRange = !!filters.from && !!filters.to && filters.from > filters.to;
  const textFilter = (key: 'search' | 'product' | 'customer', label: string) => <label>{label}
    <input type="search" value={filters[key]} onChange={e => update(key, e.target.value)} /></label>;
  const operationalFilter = (key: 'channel' | 'priority' | 'risk' | 'size', label: string) => {
    const options = Array.from(new Set(items.map(order => shown(order[key])))).sort();
    return <label key={key}>{label}<select value={filters[key]} onChange={e => update(key, e.target.value)}>
      <option value="">All</option>{options.map(option => <option key={option}>{option}</option>)}
    </select></label>;
  };
  const activeLabel = statusViews.find(view => view.value === filters.status)?.label;
  const error = query.error;
  const accessDenied = error instanceof ApiError && [401, 403].includes(error.status);
  return <section className="order-queue" aria-labelledby="oq-title">
    <header className="oq-heading"><div><p className="oq-eyebrow">Orders & planning · read only</p>
      <h1 id="oq-title">Order Decision Queue</h1><p>Review requests, uncertainty and backend assessments before opening an order.</p></div>
      <button type="button" disabled={query.isFetching} onClick={() => void query.refetch()}>Refresh queue</button></header>
    <p className="oq-notice">Pending acceptance is a request only. Feasibility and recommendations do not accept orders or reserve resources.</p>
    <fieldset className="oq-status"><legend>Order status</legend>{statusViews.map(view => <button type="button"
      key={view.value} aria-pressed={filters.status === view.value} onClick={() => update('status', view.value)}>{view.label}</button>)}</fieldset>
    <div className="oq-filters">
      {textFilter('search', 'Search order, customer or product')}{textFilter('customer', 'Customer')}{textFilter('product', 'Product')}
      <label>Received from (MYT)<input type="date" value={filters.from} onChange={e => update('from', e.target.value)} /></label>
      <label>Received through (MYT)<input type="date" value={filters.to} onChange={e => update('to', e.target.value)} /></label>
      {operationalFilter('channel', 'Origin channel')}{operationalFilter('priority', 'Priority')}
      {operationalFilter('risk', 'Risk')}{operationalFilter('size', 'Order size')}
      <button type="button" onClick={() => setFilters(initialFilters)}>Reset filters</button>
    </div>
    {invalidRange && <p role="alert">Received from must be on or before Received through.</p>}
    <div className="oq-analysis"><label>Analysis view<select value={analysis} onChange={e => setAnalysis(e.target.value)}>
      <option value="QUEUE">Queue ordering · original received (FCFS)</option><option value="FCFS">FCFS portfolio</option>
      <option value="PROFIT">Profit portfolio</option><option value="EXPIRY">Expiry-aware portfolio</option></select></label>
      <p role="status">{analysis === 'QUEUE' ? 'Queue sorted by original received time, then order ID. Unknown times appear last. No allocation calculated.' :
        `${analysis === 'EXPIRY' ? 'Expiry-aware' : analysis === 'PROFIT' ? 'Profit' : 'FCFS'} analysis unavailable: requires a verified backend portfolio result and resource snapshot. Queue order is unchanged.`}</p></div>
    {query.isPending ? <p role="status">Loading order queue…</p> : error ? <div className="oq-state" role="alert">
      <h2>{accessDenied ? 'Order queue access unavailable' : error instanceof OrderQueueUnavailableError ? 'Order queue unavailable' : 'Could not load order queue'}</h2>
      <p>{accessDenied ? 'Your current session cannot read these orders. Check your tenant and permissions.' :
        error instanceof OrderQueueUnavailableError ? error.message : 'The request failed. No order data is shown. Retry to load a fresh snapshot.'}</p>
      {error instanceof ApiError && error.correlationId && <p>Reference: {error.correlationId}</p>}
      <button type="button" disabled={query.isFetching} onClick={() => void query.refetch()}>Retry</button>
    </div> : <>
      <p className="oq-muted" aria-live="polite">{visible.length} matching of {items.length} loaded orders.
        {' '}{query.data?.coverage === 'complete' ? 'Source reports a complete snapshot.' : 'Partial snapshot: filters apply only to loaded orders, not the entire tenant.'}
        {' '}Source updated: {timestamp(query.data?.asOf)}. Dates: Asia/Kuala_Lumpur.</p>
      {query.isFetching && <p role="status">Refreshing snapshot…</p>}
      {visible.length && !invalidRange ? <div className="oq-scroll" role="region" aria-label="Order queue table, scroll horizontally" tabIndex={0}>
        <table><caption>{activeLabel} · loaded orders · read only</caption><thead><tr>
          {['Order / customer', 'Status / priority / risk', 'Received / completed', 'Products / deadline', 'Assessment / reasons', 'Expected profit / provenance', 'Details'].map(heading => <th key={heading} scope="col">{heading}</th>)}
        </tr></thead><tbody>{visible.map(order => <OrderRow key={order.id} order={order} />)}</tbody></table></div> :
        <div className="oq-state" role="status"><h2>{invalidRange ? 'Check the date range' : `No ${activeLabel?.toLowerCase()} orders match`}</h2>
          <p>{query.data?.coverage === 'partial' ? 'No matches in the loaded subset. More orders may exist outside this snapshot.' : 'Try another status or reset the search and filters.'}</p></div>}
    </>}
  </section>;
}
