import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useAuth } from "../../shared/auth";
import type { RequestAuthHeaders } from "../../shared/api";
import { formatKLTimestamp } from "../../shared/date";
import { communicationKeys, getCommunication, getCommunicationSummary, listCommunications } from "./api";
import { communicationLabel, channelText, DisplayBadge, ErrorNotice, OriginBadge, DeliveryModeBadge } from "./presentation";
import { CommunicationDetails } from "./CommunicationDetails";
import { RecipientPreferences } from "./RecipientPreferences";
import type { MessageDraftView } from "./types";
import "./communication.css";
import { P4Loading } from "./P4Feedback";

export function CommunicationCenterPage() {
  const { authHeaders } = useAuth();
  // Remount local selection/history when either security scope changes.
  return <CommunicationSession key={JSON.stringify([authHeaders.tenantId, authHeaders.actorId])} auth={authHeaders} />;
}

type Verified = Pick<MessageDraftView, "draft_id" | "expires_at">;
function CommunicationSession({ auth }: { auth: RequestAuthHeaders }) {
  const client = useQueryClient();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const [selected, setSelected] = useState("");
  const [detailDirty, setDetailDirty] = useState(false);
  const [pendingSelection, setPendingSelection] = useState("");
  const [known, setKnown] = useState<Record<string, string[]>>({});
  const [verified, setVerified] = useState<Record<string, Verified | undefined>>({});
  const [attention, setAttention] = useState<Record<string, boolean>>({});
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer); }, []);
  const list = useQuery({ queryKey: communicationKeys.list(auth),
    queryFn: ({ signal }) => listCommunications(auth, signal), retry: false, staleTime: 0 });
  const summary = useQuery({ queryKey: communicationKeys.summary(auth),
    queryFn: ({ signal }) => getCommunicationSummary(auth, signal), retry: false,
    staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: true });
  const detail = useQuery({ queryKey: communicationKeys.detail(auth, selected),
    queryFn: ({ signal }) => getCommunication(selected, auth, signal), enabled: !!selected,
    retry: false, staleTime: 0, refetchOnMount: "always" });
  const remember = useCallback((id: string, draftId: string) => {
    setKnown(previous => previous[id]?.includes(draftId) ? previous :
      { ...previous, [id]: [...(previous[id] ?? []), draftId] });
  }, []);
  const checked = useCallback((id: string, value?: MessageDraftView, failed = false) => {
    setVerified(previous => ({ ...previous, [id]: value ? { draft_id: value.draft_id, expires_at: value.expires_at } : undefined }));
    setAttention(previous => ({ ...previous, [id]: failed }));
  }, []);
  const requests = list.data ?? [];
  const isDrafted = (id: string) => !!verified[id] && Date.parse(verified[id]!.expires_at) > now;
  const label = (request: typeof requests[number]) => request.outbound_status === "SENT" ? "Sent" :
    request.outbound_status === "QUEUED" ? "Sending" : request.outbound_status ? "Blocked" : (attention[request.communication_id] ||
    (verified[request.communication_id] && !isDrafted(request.communication_id))) ? "Blocked" :
    communicationLabel(request.request_status, request.message_status, isDrafted(request.communication_id));
  const visible = requests.filter(request => {
    const haystack = [request.communication_id, request.reference.commitment_id, request.reference.proposal_id].join(" ").toLowerCase();
    return haystack.includes(search.toLowerCase().trim()) && (!status || label(request) === status) &&
      (!channel || (request.channel ?? "UNKNOWN") === channel);
  });
  const refresh = () => {
    setVerified({}); setAttention({});
    void client.invalidateQueries({ queryKey: communicationKeys.scope(auth) });
  };
  const selectRequest = (id: string) => {
    if (id === selected) return;
    if (detailDirty) { setPendingSelection(id); return; }
    setDetailDirty(false); setPendingSelection(""); setSelected(id);
  };
  return <section className="communication-center" aria-label="Communication Center">
    <header className="page-heading">
      <div><p className="eyebrow">Customer communication</p><h2>Communication Center</h2>
        <p className="muted">Review revised promises and prepare customer message drafts.</p></div>
      <div className="cc-actions"><Link className="btn btn-secondary" to="/communications/follow-ups">Follow-Up Queue</Link>
        <button className="btn btn-secondary" onClick={refresh} disabled={list.isFetching}>Refresh</button></div>
    </header>
    <RecipientPreferences auth={auth} />
    <section aria-label="Dashboard statistics">
      <div className="cc-metrics" aria-label="Communication summary" aria-busy={summary.isFetching}>
        <Metric title="Total" count={summary.isSuccess && !summary.isFetching ? summary.data.total : null} />
        <Metric title="Drafted" count={summary.isSuccess && !summary.isFetching ? summary.data.drafted : null} />
        <Metric title="Sent" count={summary.isSuccess && !summary.isFetching ? summary.data.sent : null} />
        <Metric title="Needs Attention" count={summary.isSuccess && !summary.isFetching && !summary.data.unavailable_reasons.needs_attention ? summary.data.needs_attention : null} />
      </div>
      {summary.isFetching ? <p className="muted text-sm" role="status">Loading dashboard statistics…</p> : summary.isError ?
        <ErrorNotice error={summary.error} resource="summary" onRetry={() => { void summary.refetch(); }} /> : summary.data ? <>
          <p className="muted text-sm">All requests in this workspace · Checked {formatKLTimestamp(summary.data.checked_at)}</p>
          {summary.data.drafted === null && <p className="muted text-sm">Drafted — Not available: current drafts could not be reliably verified.</p>}
          {summary.data.sent === null && <p className="muted text-sm">Sent — Not available: verified sending records are not connected.</p>}
          {summary.data.unavailable_reasons.needs_attention && <p className="muted text-sm">Needs Attention — Not available: sending failures could not be reliably counted.</p>}
        </> : null}
    </section>
    {list.isFetching ? <P4Loading>Loading communication requests…</P4Loading> : list.isError ?
      <ErrorNotice error={list.error} resource="list" onRetry={refresh} /> : <>
      {!requests.length ? <div className="cc-state"><h3>No communication requests</h3><p className="muted">Requests will appear here when they are created from an approved recovery proposal.</p></div> :
        <div className="cc-workspace">
          <div className="cc-queue">
            <form className="cc-filters" onSubmit={event => event.preventDefault()} aria-label="Request filters">
              <label>Search references<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Commitment, communication or proposal" /></label>
              <label>Status<select value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{["Pending", "Drafted", "Sent", "Blocked"].map(value => <option key={value}>{value}</option>)}</select></label>
              <label>Channel<select value={channel} onChange={event => setChannel(event.target.value)}><option value="">All channels</option>{[...new Set(requests.map(r => r.channel ?? "UNKNOWN"))].map(value => <option key={value} value={value}>{channelText(value)}</option>)}</select></label>
              <button className="btn btn-ghost" type="button" onClick={() => { setSearch(""); setStatus(""); setChannel(""); }}>Clear filters</button>
            </form>
            <p className="muted text-sm cc-filter-note">Search and filters apply to the {requests.length} loaded requests.</p>
            <section className="cc-list" aria-label="Communication requests">
            <h3>Requests <span className="muted">({visible.length})</span></h3>
            {pendingSelection && <div className="cc-unsaved-warning" role="alert"><span>Unsaved communication input will be lost.</span><button type="button" className="btn btn-secondary" onClick={() => setPendingSelection("")}>Keep editing</button><button type="button" className="btn btn-secondary" onClick={() => { setDetailDirty(false); setSelected(pendingSelection); setPendingSelection(""); }}>Discard and switch</button></div>}
            {!visible.length ? <p className="muted">No search results. Try clearing your filters.</p> :
              <ul>{visible.map(request => <li key={request.communication_id}>
                <button className="cc-request" aria-pressed={selected === request.communication_id}
                  onClick={() => selectRequest(request.communication_id)}>
                  <span className="cc-row"><strong>{request.reference.commitment_id}</strong><DisplayBadge label={label(request)} /></span>
                  <span className="cc-id">{request.communication_id}</span>
                  <span className="muted">{request.reference.proposal_id} · v{request.reference.proposal_version}</span>
                  <span className="cc-row muted">
                    <span className="cc-badges-group">
                      <OriginBadge request={request} />
                      <DeliveryModeBadge request={request} />
                    </span>
                    <time>{formatKLTimestamp(request.created_at)}</time>
                  </span>
                </button></li>)}</ul>}
          </section>
          </div>
          <section className="cc-panel" aria-label="Communication details">
            {!selected ? <div className="cc-state"><h3>Select a request</h3><p className="muted">Review its proposal and prepare a draft.</p></div> :
              detail.isFetching ? <P4Loading>Loading communication details…</P4Loading> :
              detail.isError ? <ErrorNotice error={detail.error} resource="detail" onRetry={() => { void detail.refetch(); }} /> : detail.data ?
              <CommunicationDetails key={selected} request={detail.data} auth={auth} knownIds={known[selected] ?? []}
                remember={remember} checked={checked} onDirtyChange={setDetailDirty} now={now} /> : null}
          </section>
        </div>}
    </>}
  </section>;
}

function Metric({ title, count }: { title: string; count: number | null }) {
  return <div className="cc-metric"><span className="muted">{title}</span><strong>{count ?? "—"}</strong></div>;
}
