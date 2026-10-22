import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useAuth } from "../../shared/auth";
import { ApiError, type RequestAuthHeaders } from "../../shared/api";
import { formatKLTimestamp } from "../../shared/date";
import { confirmationKeys, listConfirmations } from "./confirmationApi";
import { ConfirmationBadge, ConfirmationError } from "./confirmationPresentation";
import { FollowUpResponse } from "./FollowUpResponse";
import { attentionLabels, classifyFollowUp, defaultQueueFilters, followUpCounts, visibleFollowUps, type QueueFilters } from "./followUp";
import "./communication.css";
import "./follow-up.css";
import { P4ErrorPanel, P4Loading } from "./P4Feedback";

export function FollowUpQueuePage() {
  const { authHeaders } = useAuth();
  return <QueueSession key={JSON.stringify([authHeaders.tenantId, authHeaders.actorId])} auth={authHeaders} />;
}
function QueueSession({ auth }: { auth: RequestAuthHeaders }) {
  const [filters, setFilters] = useState<QueueFilters>(defaultQueueFilters);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer); }, []);
  const query = useQuery({ queryKey: confirmationKeys.queue(auth),
    queryFn: ({ signal }) => listConfirmations(undefined, auth, signal), retry: false,
    staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: true });
  // Never present cached records or metrics as current after refresh/error.
  const records = query.isSuccess && !query.isFetching ? query.data : undefined;
  const counts = records ? followUpCounts(records, now) : undefined;
  const visible = visibleFollowUps(records ?? [], filters, now);
  const change = <K extends keyof QueueFilters>(key: K, value: QueueFilters[K]) => {
    setFilters(previous => ({ ...previous, [key]: value })); setExpanded(null);
  };
  const refresh = () => { setExpanded(null); setNow(Date.now()); void query.refetch(); };
  return <section className="communication-center follow-up-queue" aria-label="Follow-Up Queue">
    <header className="page-heading"><div><p className="eyebrow">Customer confirmation review</p>
      <h2>Follow-Up Queue</h2><span className="fu-readonly">Read-only</span>
      <p className="muted">Review outstanding responses and exceptions for each exact proposal version.</p></div>
      <div className="cc-actions"><Link className="btn btn-ghost" to="/communications">Communication Center</Link>
        <button className="btn btn-secondary" onClick={refresh} disabled={query.isFetching}>Refresh queue</button></div>
    </header>
    <p className="muted text-sm">Last refreshed: {records ? `${formatKLTimestamp(new Date(query.dataUpdatedAt).toISOString())} · browser receipt time` : "Unavailable"}</p>
    <div className="fu-notice" role="note"><strong>P4 Evidence Only · Synthetic Only</strong>
      <p>Attention labels are browser display hints, not backend lifecycle states. No reminder dispatch, escalation workflow or customer acceptance is performed here.</p>
      <details className="p4-helper"><summary>How attention labels work</summary>
        <p className="text-sm">Expiring Soon: an awaiting, unrestricted confirmation expires within the next 24 hours. For non-terminal records, a timestamp at or before the browser clock means Expired — Needs Review. Time hints refresh every minute. Backend state remains separate.</p>
        <p className="text-sm">Terminal means no pending response for this consumed challenge. Replanning, business follow-up and fulfilment may still be required. Reminder and escalation execution status: unavailable in this API.</p>
      </details>
    </div>
    <div className="fu-metrics" aria-label="Loaded confirmation statistics" aria-busy={query.isFetching}>
      <Metric label="Total Confirmations" value={counts?.total} />
      <Metric label="Awaiting Response" value={counts?.awaiting} />
      <Metric label="Needs Attention" value={counts?.attention} />
      <Metric label="Expiring Soon" value={counts?.expiring} />
      <Metric label="Terminal" value={counts?.terminal} />
    </div>
    <p className="muted text-sm">Counts cover loaded records, before filters; they are not system-wide KPIs. Awaiting Response counts the backend state. Needs Attention counts UI exceptions, including Expiring Soon.</p>
    {query.isFetching ? <P4Loading>Loading confirmation queue…</P4Loading> : query.isError ?
      <QueueError error={query.error} retry={refresh} /> : records ? <>
        <form className="fu-filters" aria-label="Follow-up filters" onSubmit={event => event.preventDefault()}>
          <label>Search IDs<input type="search" value={filters.search} maxLength={256} placeholder="Confirmation or communication ID"
            onChange={event => change("search", event.target.value)} /></label>
          <label>Backend state<select value={filters.state} onChange={event => change("state", event.target.value)}>
            <option value="">All backend states</option>{[...new Set(records.map(value => value.state))].sort().map(state => <option key={state}>{state}</option>)}
          </select></label>
          <label>Attention category<select value={filters.attention} onChange={event => change("attention", event.target.value)}>
            <option value="">All attention categories</option>{Object.entries(attentionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
          <label>Sort by<select value={filters.sort} onChange={event => change("sort", event.target.value as QueueFilters["sort"])}>
            <option value="expiry">Expiration time</option><option value="created">Creation time</option><option value="proposal">Proposal version</option>
          </select></label>
          <label>Sort direction<select value={filters.direction} onChange={event => change("direction", event.target.value as QueueFilters["direction"])}>
            <option value="asc">Ascending</option><option value="desc">Descending</option>
          </select></label>
          <button className="btn btn-secondary" type="button" onClick={() => { setFilters(defaultQueueFilters); setExpanded(null); }}>Reset filters</button>
        </form>
        <p className="muted text-sm" role="status">Showing {visible.length} of {records.length} loaded confirmations</p>
        {!records.length ? <div className="cc-state"><h3>No confirmations available</h3><p className="muted">No records were returned for this authorized scope.</p></div> :
          !visible.length ? <div className="cc-state"><h3>No filter results</h3><p className="muted">Change the filters or select Reset filters.</p></div> :
          <ul className="fu-items" aria-label="Confirmation follow-ups">{visible.map(value => {
            const attention = classifyFollowUp(value, now);
            return <li key={value.confirmation_id}><article className="cc-panel fu-item" aria-label={`Confirmation ${value.confirmation_id}`}>
              <div className="cc-row"><div><p className="eyebrow">Confirmation reference</p><h3>{value.confirmation_id}</h3></div>
                <span className={`fu-attention fu-attention-${attention}`}>{attentionLabels[attention]}</span></div>
              <dl className="cc-facts fu-facts">
                <Fact label="Communication ID" value={value.communication_id} />
                <Fact label="Proposal ID" value={value.reference.proposal_id} />
                <Fact label="Proposal version" value={value.reference.proposal_version} />
                <Fact label="Customer reference" value={value.customer_id} />
                <Fact label="Channel" value={value.channel.replace("MOCK_", "Mock ")} />
                <div><dt>Backend state</dt><dd><code>{value.state}</code><br /><ConfirmationBadge value={value} /></dd></div>
                <Fact label="Expires at" value={formatKLTimestamp(value.expires_at)} />
                <Fact label="Created at" value={formatKLTimestamp(value.created_at)} />
                <Fact label="Proposal currentness" value="Unavailable — not reported by this read API." />
                <Fact label="Core fulfilment" value="Unavailable — confirmation evidence is separate." />
              </dl>
              <div className="fu-reasons"><strong>Blocked reasons</strong>{value.blocked_reasons.length ? <ul>{value.blocked_reasons.map((reason, index) =>
                <li key={`${index}:${reason}`}><code>{reason}</code></li>)}</ul> : <p className="muted text-sm">None reported; this does not establish current authorization.</p>}</div>
              <p className="muted text-sm">This record applies only to {value.reference.proposal_id} · v{value.reference.proposal_version}. Message delivery does not establish acceptance; acceptance does not prove fulfilment.</p>
              <div className="cc-actions"><Link className="btn btn-primary" to={`/confirmations/${encodeURIComponent(value.confirmation_id)}`}>View Confirmation</Link>
                <button className="btn btn-secondary" aria-expanded={expanded === value.confirmation_id}
                  aria-controls={`response-${encodeURIComponent(value.confirmation_id)}`}
                  onClick={() => setExpanded(previous => previous === value.confirmation_id ? null : value.confirmation_id)}>
                  {expanded === value.confirmation_id ? "Hide response" : "Load latest response"}</button></div>
              {expanded === value.confirmation_id ? <div id={`response-${encodeURIComponent(value.confirmation_id)}`}>
                <FollowUpResponse id={value.confirmation_id} auth={auth} proposalId={value.reference.proposal_id} proposalVersion={value.reference.proposal_version} />
              </div> : <p className="muted text-sm">Latest customer response: not loaded. Open it on demand or view the full confirmation history.</p>}
            </article></li>;
          })}</ul>}
      </> : null}
  </section>;
}
function Metric({ label, value }: { label: string; value?: number }) {
  return <div className="cc-metric"><span className="muted">{label}</span><strong>{value ?? "—"}</strong></div>;
}
function Fact({ label, value }: { label: string; value: string | number }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}
function QueueError({ error, retry }: { error: unknown; retry: () => void }) {
  if (error instanceof ApiError && (error.status === 400 || error.status === 404)) {
    return <P4ErrorPanel error={error} message={error.status === 400
      ? "The confirmation list request was rejected. Refresh or contact the integration owner."
      : "The confirmation list or its route is unavailable. Check the deployed API and retry."} retry={retry} />;
  }
  return <ConfirmationError error={error} retry={retry} />;
}
