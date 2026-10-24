import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../../shared/api';
import { useAuth } from '../../shared/auth';
import { ConfirmationDialog } from '../../shared/ConfirmationDialog';
import {
  acceptOrderRequest, closeDemoSession, getCommitmentEvidenceTimeline, getDemoSession,
  getNotificationIntents, getOrderRequest, getOrderRequestFeasibility, getOrderRequestTimeline,
  getReservationReceipt, listOrderRequests, openDemoSession, reviewOrderRequest,
  type DemoSession, type FeasibilityPreview,
} from './orderRequestApi';

function diagnostic(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Operator session expired. Sign in again.';
    if (error.status === 403) return 'Manager permission, tenant scope or CSRF validation denied this request.';
    if (error.status === 404) return 'This record is unavailable in the operator tenant.';
    if (error.status === 409) return `Currentness conflict (${error.code}). Refresh before a new decision.`;
    if (error.status === 422) return 'The command failed validation. Check the version and reason.';
    return `${error.code}: ${error.message}`;
  }
  return 'The server could not be reached. No action is assumed successful.';
}

function Gate({ children }: { children: (session: DemoSession) => ReactNode }) {
  const [token, setToken] = useState('');
  const [failure, setFailure] = useState('');
  const [busy, setBusy] = useState(false);
  const queryClient = useQueryClient();
  const { tenantId, actorId, setTenantId, setActorId } = useAuth();
  const session = useQuery({ queryKey: ['demo-bff-session'], queryFn: getDemoSession, retry: false });
  useEffect(() => {
    if (session.data && (session.data.tenant_id !== tenantId || session.data.actor_id !== actorId)) {
      setTenantId(session.data.tenant_id); setActorId(session.data.actor_id);
    }
  }, [session.data, tenantId, actorId, setTenantId, setActorId]);
  const signIn = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setFailure('');
    try {
      const value = await openDemoSession(token);
      setToken(''); queryClient.setQueryData(['demo-bff-session'], value);
    } catch (error) { setFailure(diagnostic(error)); }
    finally { setBusy(false); }
  };
  if (session.isPending) return <p role="status">Checking isolated operator session…</p>;
  if (!session.data) return <section className="od-panel" aria-labelledby="demo-login-title">
    <h1 id="demo-login-title">Synthetic OrderRequest workspace</h1>
    <p>Manager access requires a server-issued isolated demo session. The tenant and role selector does not authorize these actions.</p>
    {session.error instanceof ApiError && session.error.status === 503 ?
      <p role="alert">Secure demo bootstrap is not configured. OrderRequest actions are disabled.</p> :
      <form onSubmit={signIn}><label>Operator bootstrap token
        <input type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} required minLength={32} />
      </label><button type="submit" disabled={busy}>{busy ? 'Opening session…' : 'Open isolated session'}</button></form>}
    {failure && <p role="alert">{failure}</p>}
  </section>;
  return <section>
    <p className="od-notice">MOCK / DEMO-ONLY · Server session: {session.data.tenant_id} / {session.data.actor_id} · Expires {new Date(session.data.expires_at).toLocaleTimeString()}</p>
    <button type="button" onClick={async () => {
      try { await closeDemoSession(session.data); }
      finally { queryClient.removeQueries({ queryKey: ['demo-bff'] }); queryClient.removeQueries({ queryKey: ['demo-bff-session'] }); void session.refetch(); }
    }}>Revoke session</button>
    {children(session.data)}
  </section>;
}

export function OrderRequestListPage() {
  return <Gate>{() => <OrderRequestList />}</Gate>;
}
function OrderRequestList() {
  const query = useQuery({ queryKey: ['demo-bff', 'order-requests'], queryFn: listOrderRequests, retry: false });
  return <section className="order-queue"><h1>OrderRequests</h1>
    <p>Persisted synthetic requests. REVIEWED means awaiting a separate acceptance decision; it is not a Commitment.</p>
    <button type="button" disabled={query.isFetching} onClick={() => void query.refetch()}>Refresh requests</button>
    {query.isPending || query.isFetching ? <p role="status">Loading requests…</p> : query.error ?
      <p role="alert">{diagnostic(query.error)}</p> : !query.data?.length ? <p role="status">No OrderRequests in this tenant.</p> :
      <div role="region" aria-label="OrderRequest list" tabIndex={0}><table><thead><tr>
        <th scope="col">Request</th><th scope="col">Customer</th><th scope="col">Status</th><th scope="col">Version</th><th scope="col">Commitment</th><th scope="col">Detail</th>
      </tr></thead><tbody>{query.data.map(request => <tr key={request.order_request_id}>
        <td>{request.order_request_id}</td><td>{request.customer_id}</td><td>{request.decision_status}</td><td>{request.request_version}</td>
        <td>{request.commitment_id ?? 'None'}</td><td><Link to={`/order-requests/${encodeURIComponent(request.order_request_id)}`}>Inspect {request.order_request_id}</Link></td>
      </tr>)}</tbody></table></div>}
  </section>;
}

export function OrderRequestDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  return <Gate>{session => <OrderRequestDetail key={id} id={id} session={session} />}</Gate>;
}
function OrderRequestDetail({ id, session }: { id: string; session: DemoSession }) {
  const pendingKey = `demo-bff:pending:${session.tenant_id}:${id}`;
  const receiptKey = `demo-bff:receipt:${session.tenant_id}:${id}`;
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ['demo-bff', 'order-request', id], queryFn: () => getOrderRequest(id), retry: false });
  const request = detail.data;
  const feasibility = useQuery({ queryKey: ['demo-bff', 'feasibility', id, request?.request_version],
    queryFn: () => getOrderRequestFeasibility(id), enabled: request?.decision_status === 'REVIEWED', retry: false });
  const requestTimeline = useQuery({ queryKey: ['demo-bff', 'request-timeline', id],
    queryFn: () => getOrderRequestTimeline(id), enabled: !!request, retry: false });
  const commitmentId = request?.commitment_id;
  const commitmentTimeline = useQuery({ queryKey: ['demo-bff', 'commitment-timeline', commitmentId],
    queryFn: () => getCommitmentEvidenceTimeline(commitmentId!), enabled: !!commitmentId, retry: false });
  const intents = useQuery({ queryKey: ['demo-bff', 'notification-intents', commitmentId],
    queryFn: () => getNotificationIntents(commitmentId!), enabled: !!commitmentId, retry: false });
  const [reason, setReason] = useState('');
  const [action, setAction] = useState<'REVIEWED' | 'REJECTED' | 'ACCEPT' | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [operationId, setOperationId] = useState(() => sessionStorage.getItem(receiptKey) ?? '');
  const [key, setKey] = useState<string | null>(() => sessionStorage.getItem(pendingKey));
  const receipt = useQuery({ queryKey: ['demo-bff', 'receipt', operationId],
    queryFn: () => getReservationReceipt(operationId), enabled: !!operationId, retry: false });
  const refresh = async () => {
    await Promise.all([detail.refetch(), requestTimeline.refetch()]);
    await queryClient.invalidateQueries({ queryKey: ['demo-bff'] });
  };
  const decide = async () => {
    if (!request || !action || !reason.trim()) return;
    setBusy(true); setNotice('');
    try {
      if (action === 'ACCEPT') {
        const preview = feasibility.data as FeasibilityPreview | undefined;
        if (!preview || preview.request_version !== request.request_version || preview.terms_hash !== request.terms_hash ||
          preview.assessment.status !== 'FEASIBLE' || !preview.assessment.evidence_complete)
          throw new Error('Current, complete feasible P2 evidence required. Refresh before acceptance.');
        const stableKey = key ?? crypto.randomUUID();
        sessionStorage.setItem(pendingKey, stableKey);
        setKey(stableKey);
        const result = await acceptOrderRequest(request, preview, session, reason.trim(), stableKey);
        sessionStorage.setItem(receiptKey, result.reservation.operation_id);
        setOperationId(result.reservation.operation_id);
        if (result.reservation.status === 'UNKNOWN' || !result.commitment) {
          setNotice('RESERVATION_UNKNOWN: no accepted Commitment is claimed. Inspect the durable receipt and request manager reconciliation.');
        } else if (result.order_request.decision_status === 'ACCEPTED' && result.reservation.status === 'CONFIRMED' &&
          result.order_request.commitment_id === result.commitment.commitment_id) {
          setNotice(`OrderRequest accepted. Commitment ${result.commitment.commitment_id} is persisted.`);
          sessionStorage.removeItem(pendingKey);
          setKey(null);
        } else throw new Error('Acceptance response lacks a matching confirmed reservation and Commitment.');
      } else {
        const result = await reviewOrderRequest(id, session, request.request_version, action, reason.trim());
        setNotice(`OrderRequest status: ${result.decision_status}. Acceptance remains separate.`);
      }
      setReason('');
      await refresh();
    } catch (error) {
      setNotice(action === 'ACCEPT' && !(error instanceof ApiError && error.status === 409)
        ? `${diagnostic(error)} Acceptance outcome may be unknown. Refresh the request and receipt before another submission; the same key is retained.`
        : diagnostic(error));
      if (error instanceof ApiError && error.status === 409) await refresh();
    } finally { setBusy(false); setAction(null); }
  };
  return <section className="order-detail"><Link to="/order-requests">← OrderRequests</Link><h1>OrderRequest {id}</h1>
    <button type="button" disabled={detail.isFetching} onClick={() => void refresh()}>Refresh server state</button>
    {detail.isPending || detail.isFetching ? <p role="status">Loading persisted OrderRequest…</p> : detail.error ?
      <p role="alert">{diagnostic(detail.error)}</p> : request ? <>
        <p className="od-notice">MOCK / DEMO-ONLY · {request.decision_status} · Request v{request.request_version} · Terms revision {request.terms.terms_revision}</p>
        <p>Customer {request.customer_id} · Source {request.source_id} v{request.source_version} · Valid through {request.source_valid_through}</p>
        <p>Terms hash: <code>{request.terms_hash}</code></p>
        <p>Requested {request.terms.fulfilment_method.toLowerCase()} by {request.terms.window_end} · {request.terms.currency} {request.terms.total}</p>
        <ul>{request.terms.items.map((item, index) => <li key={index}>{item.sku} · {item.quantity} {item.unit} · unit price {item.unit_price}</li>)}</ul>
        <p>Price source: {request.terms.price_source.source_type} / {request.terms.price_source.source_id} v{request.terms.price_source.source_version}</p>
        <p>Evidence: {request.source_evidence_refs.join(', ')}</p>
        {request.review_actor_id && <p>Reviewed by {request.review_actor_id}: {request.review_reason}</p>}
        {request.decision_status === 'PENDING' && <section><h2>Review request</h2>
          <label>Decision reason <textarea value={reason} onChange={event => setReason(event.target.value)} /></label>
          <button type="button" disabled={!reason.trim() || busy} onClick={() => setAction('REVIEWED')}>Mark reviewed</button>
          <button type="button" disabled={!reason.trim() || busy} onClick={() => setAction('REJECTED')}>Reject request</button>
        </section>}
        {request.decision_status === 'REVIEWED' && <section><h2>P2 feasibility before acceptance</h2>
          {feasibility.isPending || feasibility.isFetching ? <p role="status">Checking current P2 snapshot…</p> : feasibility.error ?
            <p role="alert">{diagnostic(feasibility.error)}</p> : feasibility.data ? <>
              <p>{feasibility.data.assessment.status} · Snapshot {feasibility.data.assessment.snapshot_id} v{feasibility.data.assessment.snapshot_version} · Evidence {feasibility.data.assessment.evidence_complete ? 'complete' : 'incomplete'}</p>
              <p>Assessment {feasibility.data.assessment.assessment_id} · {feasibility.data.assessment.evidence_refs.join(', ')}</p>
            </> : null}
          <label>Acceptance reason <textarea value={reason} onChange={event => setReason(event.target.value)} /></label>
          <button type="button" disabled={!reason.trim() || busy || !feasibility.data || feasibility.data.assessment.status !== 'FEASIBLE' || !feasibility.data.assessment.evidence_complete}
            onClick={() => setAction('ACCEPT')}>Accept Order</button>
          {key && <p>Unresolved submission key retained across browser refresh. Refresh records before an explicit retry.</p>}
        </section>}
        {notice && <p role="status">{notice}</p>}
        {(request.decision_status === 'RESERVATION_UNKNOWN' || operationId) && <section><h2>Reservation receipt</h2>
          {operationId ? <><p>Operation {operationId}</p><button type="button" onClick={() => void receipt.refetch()}>Inspect durable receipt</button>
            {receipt.data && <p>Persisted receipt status: {receipt.data.status} · Evidence {receipt.data.evidence_refs.join(', ')}</p>}
            {receipt.error && <p role="alert">{diagnostic(receipt.error)}</p>}</> : <p>Operation ID is unavailable in this browser session. Request manager reconciliation; do not resubmit with a new key.</p>}
        </section>}
        {commitmentId && <section><h2>Linked Commitment {commitmentId}</h2>
          <p><Link to={`/commitments/${encodeURIComponent(commitmentId)}`}>P2 Commitment</Link> · <Link to={`/recovery/${encodeURIComponent(commitmentId)}`}>P3 Recovery</Link> · <Link to={`/activity?commitment_id=${encodeURIComponent(commitmentId)}`}>Activity</Link></p>
          <h3>P4 notification intents</h3>{intents.isPending ? <p>Loading intents…</p> : intents.error ? <p role="alert">{diagnostic(intents.error)}</p> : !intents.data?.length ? <p>No persisted intents.</p> :
            <ul>{intents.data.map(intent => <li key={intent.intent_id}>{intent.status} · {intent.delivery_status} · {intent.blocker_codes.join(', ') || 'No blockers reported'} · {intent.evidence_refs.join(', ')}</li>)}</ul>}
          <h3>Same-Commitment timeline</h3>{commitmentTimeline.isPending ? <p>Loading timeline…</p> : commitmentTimeline.error ? <p role="alert">{diagnostic(commitmentTimeline.error)}</p> :
            <ol>{commitmentTimeline.data?.entries.map(event => <li key={event.event_id}>{event.occurred_at} · {event.event_type} · {event.status} · {event.evidence_refs.join(', ')}</li>)}</ol>}
        </section>}
        <section><h2>OrderRequest audit</h2>{requestTimeline.isPending ? <p>Loading audit…</p> : requestTimeline.error ? <p role="alert">{diagnostic(requestTimeline.error)}</p> :
          <ol>{requestTimeline.data?.map((event, index) => <li key={`${event.occurred_at}-${index}`}>{event.occurred_at} · {event.event_type} · {event.source} · {event.evidence_refs.join(', ')}</li>)}</ol>}</section>
      </> : <p>No request returned.</p>}
    <ConfirmationDialog open={!!action} onOpenChange={open => { if (!open) setAction(null); }}
      title={action === 'ACCEPT' ? 'Accept this OrderRequest?' : action === 'REJECTED' ? 'Reject this OrderRequest?' : 'Record human review?'}
      description={`Request ${id} · version ${request?.request_version ?? 'unknown'} · ${action === 'ACCEPT' ? 'Mock resources will be reserved and a Core Commitment created only after server validation.' : 'The decision is recorded in the audit.'}`}
      confirmLabel={action === 'ACCEPT' ? 'Confirm Accept Order' : 'Confirm decision'}
      scope={request ? `Terms ${request.terms_hash} · ${request.terms.currency} ${request.terms.total}` : undefined}
      pending={busy} confirmDisabled={!reason.trim()} onConfirm={decide} />
  </section>;
}
