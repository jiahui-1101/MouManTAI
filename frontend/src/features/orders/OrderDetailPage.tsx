import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { ApiError, authHeaders } from '../../shared/api';
import { useAuth } from '../../shared/auth';
import { OrderContextDetail } from '../context/OrderContextDetail';
import type { OrderContextRecord } from '../context/types';
import { loadLegacyContextDetail, type OrderDetailSource } from './detailApi';
import type { OrderDecisionSource } from './decisionTypes';
import { OrderDetailWorkspace } from './OrderDetailWorkspace';
import './orderDetail.css';
import { demoOrderDetailSource, ordersDemoEnabled } from './demoSource';
import { dbOrderDetailSource, ordersPersistedEnabled } from './dbSource';

const defaultOrderDetailSource = (): OrderDetailSource | undefined => {
  if (ordersPersistedEnabled()) return dbOrderDetailSource;
  if (ordersDemoEnabled()) return demoOrderDetailSource;
  return undefined;
};

export interface OrderDetailPageProps { orderId?: string; source?: OrderDetailSource; decisionSource?: OrderDecisionSource }

export function OrderDetailPage({ orderId, source = defaultOrderDetailSource(), decisionSource }: OrderDetailPageProps = {}) {
  const params = useParams<{ id: string }>(); const id = orderId ?? params.id ?? '';
  const { authHeaders: auth } = useAuth();
  const legacyHeaders = useMemo(() => authHeaders(auth), [auth]);
  const identity = `${id}:${auth.tenantId}:${auth.actorId}`;
  const [contextState, setContextState] = useState<{ identity: string; context: OrderContextRecord } | null>(null);
  const [reload, setReload] = useState(0);
  const generation = `${identity}:${reload}`;
  const activeGeneration = useRef<string | null>(generation);
  useLayoutEffect(() => {
    activeGeneration.current = generation;
    return () => { activeGeneration.current = null; };
  }, [generation]);
  const legacyContext = contextState?.identity === identity ? contextState.context : null;
  const contextMismatch = !!legacyContext && (legacyContext.order_id !== id || legacyContext.tenant_id !== auth.tenantId);
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
    enabled: !!id && !contextMismatch && (!!source || !!legacyContext), retry: false, gcTime: 0,
  });
  const denied = query.error instanceof ApiError && [401, 403].includes(query.error.status);
  const d = !contextMismatch && !query.isFetching && !query.isError ? query.data : undefined;
  const sourceState = <>{contextMismatch ? <p role="alert">The legacy context does not match this order and tenant. Context, assessment and decision details are withheld. Refresh to read the correct source.</p> : !id ? <p role="alert">No order identifier provided.</p> : !source && !legacyContext ? <p role="status">Awaiting the existing P1 context source. Pending-order assessment is unavailable until a verified contract is provided.</p> : query.isPending || query.isFetching ? <p role="status"><span>Loading order detail…</span> Previous sensitive assessment and decision results are hidden.</p> : query.error ?
      <section className="od-panel" role="status" aria-label="Order assessment source state"><h2>{denied ? 'Order detail access unavailable' : 'Order detail unavailable'}</h2>
        <p>{denied ? 'Check tenant access and current session permissions.' : 'The source could not be loaded or safely mapped. No assessment data is shown.'}</p>
        <button type="button" disabled={query.isFetching} onClick={() => void query.refetch()}>Retry order detail</button></section> : !d ?
      <section className="od-panel" role="status"><h2>No order detail available</h2><p>No record was returned by the configured source.</p></section> : null}{d?.sourceWarnings?.map((warning, i) => <p className="od-notice" key={i}>{warning}</p>)}</>;
  const legacyPanel = id && !contextMismatch && <section className="od-legacy" id="legacy-order-context" aria-labelledby="od-legacy-title">
      <h2 id="od-legacy-title">Existing P1 context, review & history</h2>
      <p>This is the original P1 context workflow. Publishing context to Core is not v2.2 order acceptance or proof of resource reservation.</p>
      <OrderContextDetail key={`${identity}:${reload}`} orderId={id} requestHeaders={legacyHeaders}
        onContextLoaded={context => { if (activeGeneration.current === generation) setContextState({ identity, context }); }}
        onContextUpdated={context => {
          if (activeGeneration.current !== generation) return;
          setContextState({ identity, context }); if (source) void query.refetch();
        }} />
    </section>;
  return <OrderDetailWorkspace key={identity} id={id} detail={d} now={now} busy={query.isFetching} state={sourceState} legacy={legacyPanel} decisionSource={decisionSource}
    onRefresh={() => {
      if (!source || contextMismatch) { setContextState(null); setReload(value => value + 1); }
      if (source) void query.refetch();
    }} />;
}
