import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { ApiError, authHeaders } from '../../shared/api';
import { useAuth } from '../../shared/auth';
import { OrderContextDetail } from '../context/OrderContextDetail';
import type { OrderContextRecord } from '../context/types';
import { loadLegacyContextDetail, type OrderDetailSource } from './detailApi';
import { OrderSummaryPanel, CustomerRequestPanel, InventoryAssessmentPanel, CapacityAssessmentPanel,
  FeasibilitySummary, PricingProvenancePanel, DecisionReadinessPanel } from './OrderDetailPanels';
import './orderDetail.css';

export interface OrderDetailPageProps { orderId?: string; source?: OrderDetailSource }

export function OrderDetailPage({ orderId, source }: OrderDetailPageProps = {}) {
  const params = useParams<{ id: string }>(); const id = orderId ?? params.id ?? '';
  const { authHeaders: auth } = useAuth();
  const legacyHeaders = useMemo(() => authHeaders(auth), [auth]);
  const identity = `${id}:${auth.tenantId}:${auth.actorId}`;
  const [contextState, setContextState] = useState<{ identity: string; context: OrderContextRecord } | null>(null);
  const [reload, setReload] = useState(0);
  const legacyContext = contextState?.identity === identity ? contextState.context : null;
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 60000); return () => window.clearInterval(timer); }, []);
  const query = useQuery({
    queryKey: ['orders', 'detail', source?.cacheKey ?? 'legacy-p1-context-read-v1', auth.tenantId, auth.actorId, id, source ? null : legacyContext?.context_version, reload],
    queryFn: async ({ signal }) => {
      const detail = source ? await source.load(id, auth, signal) : await loadLegacyContextDetail(legacyContext, id, auth, signal);
      if (detail && (detail.id !== id || detail.tenantId !== auth.tenantId)) throw new Error('Order identity mismatch');
      setNow(Date.now());
      return detail;
    },
    enabled: !!id && (!!source || !!legacyContext), retry: false,
  });
  const denied = query.error instanceof ApiError && [401, 403].includes(query.error.status);
  const d = query.data;
  return <div className="order-detail">
    <header className="od-heading"><div><Link to="/orders">Back to Order Queue</Link><h1>Order detail & feasibility</h1>
      <p>Order {id || 'Not available'} · Read-only decision support</p></div>
      <button type="button" disabled={!id || query.isFetching} onClick={() => {
        if (source) void query.refetch(); else { setContextState(null); setReload(value => value + 1); }
      }}>Refresh order assessment view</button></header>
    <p className="od-notice">Assessment is separate from acceptance and reservation. Existing P1 review and Core publishing remain available below through their original workflow.</p>
    {!id ? <p role="alert">No order identifier provided.</p> : !source && !legacyContext ? <p role="status">Awaiting the existing P1 context source. Pending-order assessment is unavailable until a verified contract is provided.</p> : query.isPending ? <p role="status">Loading order detail…</p> : query.error ?
      <section className="od-panel" role="status" aria-label="Order assessment source state"><h2>{denied ? 'Order detail access unavailable' : 'Order detail unavailable'}</h2>
        <p>{denied ? 'Check tenant access and current session permissions.' : 'The source could not be loaded or safely mapped. No assessment data is shown.'}</p>
        <button type="button" disabled={query.isFetching} onClick={() => void query.refetch()}>Retry order detail</button></section> : !d ?
      <section className="od-panel" role="status"><h2>No order detail available</h2><p>No record was returned by the configured source.</p></section> : <>
        {query.isFetching && <p role="status">Refreshing order detail…</p>}
        {d.sourceWarnings?.map((warning, i) => <p className="od-notice" key={i}>{warning}</p>)}
        <OrderSummaryPanel detail={d} /><FeasibilitySummary detail={d} now={now} />
        <CustomerRequestPanel detail={d} /><InventoryAssessmentPanel detail={d} /><CapacityAssessmentPanel detail={d} />
        <PricingProvenancePanel detail={d} /><DecisionReadinessPanel detail={d} now={now} />
      </>}
    {id && <section className="od-legacy" id="legacy-order-context" aria-labelledby="od-legacy-title">
      <h2 id="od-legacy-title">Existing P1 context, review & history</h2>
      <p>This is the original P1 context workflow. Publishing context to Core is not v2.2 order acceptance or proof of resource reservation.</p>
      <OrderContextDetail key={`${identity}:${reload}`} orderId={id} requestHeaders={legacyHeaders}
        onContextLoaded={context => setContextState({ identity, context })}
        onContextUpdated={context => { setContextState({ identity, context }); if (source) void query.refetch(); }} />
    </section>}
  </div>;
}
