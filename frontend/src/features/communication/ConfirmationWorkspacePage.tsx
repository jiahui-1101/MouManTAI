import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../../shared/auth";
import { formatKLTimestamp } from "../../shared/date";
import type { RequestAuthHeaders } from "../../shared/api";
import { confirmationKeys, getConfirmation, getConfirmationAttempts } from "./confirmationApi";
import { ConfirmationBadge, ConfirmationError, currentnessText, responseLabels } from "./confirmationPresentation";
import type { ConfirmationView } from "./confirmationTypes";
import "./communication.css";
import "./confirmation.css";
import { P4Loading } from "./P4Feedback";

export function ConfirmationWorkspacePage() {
  const { id = "" } = useParams();
  const { authHeaders } = useAuth();
  return <Workspace key={JSON.stringify([authHeaders.tenantId, authHeaders.actorId, id])} id={id} auth={authHeaders} />;
}
function Workspace({ id, auth }: { id: string; auth: RequestAuthHeaders }) {
  const detail = useQuery({ queryKey: confirmationKeys.detail(auth, id),
    queryFn: ({ signal }) => getConfirmation(id, auth, signal), enabled: !!id, retry: false,
    staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: true });
  const history = useQuery({ queryKey: confirmationKeys.attempts(auth, id),
    queryFn: ({ signal }) => getConfirmationAttempts(id, auth, signal), enabled: !!id && detail.isSuccess && !detail.isFetching,
    retry: false, staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: true });
  const refresh = () => { void detail.refetch(); void history.refetch(); };
  const value = detail.isSuccess && !detail.isFetching ? detail.data : undefined;
  return <section className="communication-center confirmation-workspace" aria-label="Customer Confirmation Workspace">
    <header className="page-heading"><div><p className="eyebrow">Closed-loop communication</p>
      <h2>Confirmation workspace</h2><p className="muted">Review the exact proposal version and its recorded customer response.</p></div>
      <div className="cc-actions"><Link className="btn btn-ghost" to="/communications">Communication Center</Link>
        <Link className="btn btn-secondary" to="/communications/follow-ups">Follow-Up Queue</Link>
        <button className="btn btn-secondary" onClick={refresh} disabled={!id || detail.isFetching || history.isFetching}>Refresh workspace</button></div>
    </header>
    {!id ? <p className="cc-state">No confirmation selected. Open a linked record from the Communication Center.</p> :
      detail.isFetching ? <P4Loading>Loading confirmation details…</P4Loading> :
      detail.isError ? <ConfirmationError error={detail.error} retry={refresh} /> : value ? <>
        <div className="cw-notice" role="note"><strong>Synthetic evidence workspace</strong>
          <p>This response contains P4 evidence only and reports no Core transition. Check Core separately for the current agreement. Acceptance does not prove fulfilment.</p></div>
        <section className="cc-panel cw-summary" aria-label="Confirmation overview">
          <div className="cc-row"><div><p className="eyebrow">Confirmation record</p><h3>{value.confirmation_id}</h3></div><ConfirmationBadge value={value} /></div>
          <dl className="cc-facts"><Fact label="Communication ID"><code>{value.communication_id}</code></Fact>
            <Fact label="Outbound ID"><code>{value.outbound_id}</code></Fact>
            <Fact label="Customer reference"><code>{value.customer_id}</code></Fact>
            <Fact label="Channel">{value.channel.replace("MOCK_", "Mock ")}</Fact>
            <Fact label="Created at">{formatKLTimestamp(value.created_at)}</Fact>
            <Fact label="Expires at">{formatKLTimestamp(value.expires_at)}</Fact>
            <Fact label="Consumed at">{value.consumed_at ? formatKLTimestamp(value.consumed_at) : "Not consumed"}</Fact>
            <Fact label="Revoked at">{value.revoked_at ? formatKLTimestamp(value.revoked_at) : "No revocation reported"}</Fact>
          </dl>
        </section>
        <div className="cw-grid"><div className="cw-column">
          <section className="cc-panel" aria-label="Proposal and version details"><h3>Proposal & version</h3>
            <p className="cw-version"><code>{value.reference.proposal_id}</code><span>Version {value.reference.proposal_version}</span></p>
            <dl className="cc-facts"><Fact label="Commitment ID"><code>{value.reference.commitment_id}</code></Fact>
              <Fact label="Bound commitment version">{value.reference.commitment_version}</Fact>
              <Fact label="Proposal ID"><code>{value.reference.proposal_id}</code></Fact>
              <Fact label="Proposal version">{value.reference.proposal_version}</Fact>
              <Fact label="Proposal currentness">{currentnessText(value)}</Fact>
              <Fact label="Approved terms">Unavailable — only the exact terms digest is returned.</Fact>
              <Fact label="Terms digest"><code>{value.terms_digest}</code></Fact>
              <Fact label="Content digest"><code>{value.content_hash}</code></Fact>
            </dl>
            <p className="muted text-sm">Evidence for this version cannot establish acceptance of a revised proposal. Revised terms require their own versioned proposal and verified response.</p>
          </section>
          <section className="cc-panel" aria-label="Customer response history"><div className="cc-row"><h3>Customer response history</h3>
            <button className="btn btn-secondary" disabled={history.isFetching} onClick={() => { void history.refetch(); }}>Refresh history</button></div>
            {history.isFetching || history.isPending ? <p role="status">Loading response history…</p> : history.isError ?
              <ConfirmationError error={history.error} retry={() => { void history.refetch(); }} /> : !history.data?.length ?
              <p className="cc-state">No customer responses recorded. A sent message does not establish acceptance.</p> :
              <ol className="cw-timeline">{history.data.map(attempt => <li key={attempt.attempt_id}>
                <article aria-label={`Response ${attempt.attempt_id}`}><div className="cc-row"><h4>{responseLabels[attempt.intent]}</h4>
                  <time dateTime={attempt.received_at}>{formatKLTimestamp(attempt.received_at)}</time></div>
                  <p className="muted text-sm">Applies to {value.reference.proposal_id} · v{value.reference.proposal_version}</p>
                  <dl className="cc-facts"><Fact label="Response reference"><code>{attempt.attempt_id}</code></Fact>
                    <Fact label="Inbound message reference"><code>{attempt.inbound_message_id}</code></Fact>
                    <Fact label="Classification reason"><code>{attempt.reason}</code></Fact>
                    <Fact label="Verification">Evidence references recorded. Current identity verification is unavailable in this read API.</Fact></dl>
                  <h5>Response evidence references</h5><ul className="cw-evidence">{attempt.evidence_refs.map((ref, index) => <li key={`${index}:${ref}`}><code>{ref}</code></li>)}</ul>
                  {attempt.proposed_changes && Object.keys(attempt.proposed_changes).length > 0 && <div className="cw-notice">
                    <h5>Customer-proposed changes</h5><p className="text-sm">Original approved terms remain unchanged.</p>
                    <dl className="cc-facts">{Object.entries(attempt.proposed_changes).map(([key, entry]) =>
                      <Fact key={key} label={key.replace(/_/g, " ")}>{entry}</Fact>)}</dl></div>}
                </article></li>)}</ol>}
            <p className="muted text-sm">Only persisted attempts are returned. Rejected API calls, full audit records and deduplicated webhook deliveries are not supplied by this endpoint.</p>
          </section>
        </div><aside className="cw-column" aria-label="Confirmation safeguards">
          <StatusCard value={value} />
          <section className="cc-panel" aria-label="Evidence and verification"><h3>Evidence & verification</h3>
            <dl className="cc-facts cw-single"><Fact label="Evidence scope">P4 evidence only · Synthetic only</Fact>
              <Fact label="Current customer identity">Unavailable — no live identity verdict is returned.</Fact>
              <Fact label="Recipient contact">Unavailable — contact data is redacted by the API.</Fact>
              <Fact label="Audit details">Unavailable — use the authorized audit workflow.</Fact>
              <Fact label="Updated at">Unavailable — this API does not return an updated timestamp.</Fact>
              <Fact label="Source event"><code>{value.reference.source_event_id}</code></Fact>
              <Fact label="Correlation reference"><code>{value.reference.correlation_id}</code></Fact>
            </dl>
          </section>
          <section className="cc-panel cw-next" aria-label="Next steps"><h3>Next steps</h3>
            <p>Customer responses must arrive through a trusted inbound processor. This workspace cannot accept or reject on a customer's behalf.</p>
            <p className="muted">This read API does not report live processor connectivity or the current Core agreement result.</p>
            <p className="muted text-sm">Use the authorized integration workflow to verify identity and current proposal terms. Refresh to read the latest persisted evidence.</p>
          </section>
        </aside></div>
      </> : <p className="cc-state">No confirmation data available.</p>}
  </section>;
}
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return <div><dt>{label}</dt><dd>{children}</dd></div>;
}
function StatusCard({ value }: { value: ConfirmationView }) {
  return <section className="cc-panel" aria-label="Confirmation status"><h3>Confirmation status</h3>
    <ConfirmationBadge value={value} />
    <dl className="cc-facts cw-single"><Fact label="Recorded response state"><code>{value.state}</code></Fact>
      <Fact label="Message delivery">Unavailable here — inspect the separate outbound record.</Fact>
      <Fact label="Core agreement transition">Not applied by this workflow.</Fact>
      <Fact label="Operational fulfilment">Unavailable — no Core fulfilment evidence is returned.</Fact>
    </dl>
    {!!value.blocked_reasons.length && <div className="cw-notice"><strong>Backend-reported restrictions</strong>
      <ul>{value.blocked_reasons.map((reason, index) => <li key={`${index}:${reason}`}><code>{reason}</code></li>)}</ul></div>}
    <p className="muted text-sm">Status and expiry above are backend-reported. This page does not determine whether the proposal is active.</p>
  </section>;
}
