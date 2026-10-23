import { useQuery } from '@tanstack/react-query';
import { ApiError } from '../../shared/api';
import { useAuth } from '../../shared/auth';
import { EvidenceTierBadge, ErrorState, MutationStateView, StateTimeline, UncertaintyNote, VersionConflictBanner } from '../../shared/ui';
import type { OrderDetail } from './detailTypes';
import type { OrderDecisionSource, OrderDecisionSnapshot } from './decisionTypes';
import { coreOrderDecisionSource } from './decisionApi';
import { acceptanceBlockers, assentLabel, commandDependency, receiptLabel } from './decisionGuards';
import { DecisionTermsView, TermsComparison } from './DecisionTermsView';
import { ProposalPreparation } from './ProposalPreparation';
import { instant, shown, timestamp } from './queue';
import './orderDecisions.css';

function DecisionTimeline({ snapshot }: { snapshot: OrderDecisionSnapshot }) {
  const events = [...snapshot.events].sort((a, b) => (instant(a.at) ?? Infinity) - (instant(b.at) ?? Infinity) || a.id.localeCompare(b.id));
  return <section className="decision-panel" aria-labelledby="decision-history"><h3 id="decision-history">Decision & audit timeline</h3>
    <p>Only supplied persisted records appear. A legacy Core event does not prove a v2.2 reservation, customer assent or decision receipt.</p>
    {!events.length ? <p>No decision timeline records supplied. No successful event has been synthesized.</p> : <ol>{events.map(event => <li key={event.id}>
      <strong>{event.eventType}</strong><p>Persisted entry: {event.id} · {timestamp(event.at)} · {shown(event.actor)} / {shown(event.role)}</p>
      <p>Recorded action: {shown(event.action)} · Reason: {shown(event.reason)}</p>
      <p>Request / commitment version: {shown(event.requestVersion)} / {shown(event.commitmentVersion)}</p>
      <p>Proposal / version: {shown(event.proposalId)} / {shown(event.proposalVersion)} · Terms identity: {shown(event.termsHash)}</p>
      <p>Recorded state: {shown(event.recordedState)} · Receipt: {shown(event.receiptId)} · Reservation: {shown(event.reservationRef)}</p>
      <p>Evidence: {event.evidence.join(', ') || 'Not available'}</p></li>)}</ol>}
    {(snapshot.receipts ?? []).map(receipt => <article key={receipt.id} className="decision-receipt"><h4>Recorded receipt {receipt.id}</h4>
      <p>{receiptLabel(receipt, snapshot)}</p><p>Source outcome: {receipt.outcome} · Reason: {shown(receipt.reason)} · {timestamp(receipt.at)}</p>
      <p>Audit: {shown(receipt.auditRef)} · Reservation: {shown(receipt.reservationRef)} · Request version: {shown(receipt.requestVersion)}</p>
      {receipt.outcome === 'PENDING' && <MutationStateView state={{ status: 'pending', message: 'Persisted receipt reports PENDING. Acceptance is not confirmed.' }} />}
      {receipt.outcome === 'UNKNOWN' && <ErrorState kind="unknown-outcome" description="The recorded operation outcome is unknown. Reconcile its authoritative receipt before any new submission." />}
    </article>)}
    {!!snapshot.receipts?.length && <StateTimeline label="Recorded receipt verification states" stages={snapshot.receipts.map(receipt => ({
      id: receipt.id, label: `Recorded receipt ${receipt.id} · ${receipt.outcome}`, timestamp: receipt.at,
      status: receipt.outcome === 'FAILED' ? 'failed' : receiptLabel(receipt, snapshot).startsWith('Source records') ? 'completed' : 'pending',
      description: receiptLabel(receipt, snapshot), evidenceRefs: receipt.auditRef ? [receipt.auditRef] : [],
    }))} />}
  </section>;
}

export function OrderDecisionWorkspace({ order, now, source = coreOrderDecisionSource }: { order: OrderDetail; now: number; source?: OrderDecisionSource }) {
  const { authHeaders: auth } = useAuth();
  const query = useQuery({ queryKey: ['orders', 'decisions', source.cacheKey, auth.tenantId, auth.actorId, order.id, order.version ?? null,
    order.contextVersion ?? null, order.contextUpdatedAt ?? null, order.commitmentId ?? null],
    queryFn: async ({ signal }) => {
      if (order.tenantId !== auth.tenantId) throw new Error('Order/session tenant mismatch');
      const snapshot = await source.load(order, auth, signal);
      if (snapshot.tenantId !== auth.tenantId || snapshot.orderId !== order.id) throw new Error('Decision source identity mismatch');
      return snapshot;
    }, retry: false });
  const error = query.error; const snapshot = query.data;
  const errorText = error instanceof ApiError ? [401, 403].includes(error.status) ? 'Permission unavailable. Check the current tenant/session.' :
    error.status === 409 ? 'Source version conflict. Refresh authoritative records before reviewing terms.' :
      error.status === 404 ? 'Linked decision source was not found. No order decision is inferred.' :
        error.status === 422 ? 'Source validation failed. No command or reservation was performed.' : 'Decision source unavailable. No command was submitted.' :
    'Decision source could not be safely read. No business command was submitted.';
  return <section className="order-decisions" aria-labelledby="order-decisions-heading"><header><h2 id="order-decisions-heading">Order Decision workspace</h2>
    <p>Read-only Backend boundary · acceptance, proposal, rejection and amendment commands unavailable.</p>
    <EvidenceTierBadge evidenceTier="TARGET" title="Order command capability is not yet operational" />
    <button type="button" disabled={query.isFetching} onClick={() => void query.refetch()}>Refresh decision records</button></header>
    {query.isPending ? <p role="status">Loading decision records…</p> : error ? <div role="status" aria-label="Order decision source state">
      {error instanceof ApiError && error.status === 409 ? <VersionConflictBanner message={errorText} expectedVersion={order.version ?? undefined} /> : <ErrorState error={error} description={errorText} />}
      <button type="button" disabled={query.isFetching} onClick={() => void query.refetch()}>Retry decision records</button></div> : snapshot && <>
      {query.isFetching && <p role="status">Refreshing decision records…</p>}
      <p>Decision data source: {snapshot.sourceLabel}</p>{snapshot.warnings?.map((warning, i) => <p key={i} className="decision-notice">{warning}</p>)}
      <section className="decision-panel" aria-labelledby="acceptance-review"><h3 id="acceptance-review">Acceptance review</h3>
        <UncertaintyNote kind="insufficient-evidence">Frontend review never grants decision permission; server command authority remains unavailable.</UncertaintyNote>
        <p>Order reference: {order.id} · Authoritative request version: {shown(snapshot.requestVersion)}. Context and commitment versions cannot substitute.</p>
        <DecisionTermsView terms={snapshot.exactOriginal} title="Exact original customer-offered terms" financial={snapshot.financialAccess === 'AUTHORIZED'} />
        <h4>Acceptance blockers and source conditions</h4><ul>{acceptanceBlockers(order, snapshot, now).map(blocker => <li key={blocker}>{blocker}</li>)}</ul>
        <p>Assessment/snapshot reference: {shown(order.assessment?.id)} / {shown(order.assessment?.snapshotId)} · Source freshness: {order.assessment?.freshness ?? 'UNKNOWN'}</p>
        <p>Outstanding conditions: {order.assessment?.conditions?.join('; ') || 'Not available'}</p>
        <p><strong>Accept as Requested — unavailable.</strong> {commandDependency}</p>
        <p><strong>Accept Agreed Proposal — unavailable.</strong> Exact proposal assent alone is not execution permission.</p>
      </section>
      <section className="decision-panel" aria-labelledby="proposal-workspace"><h3 id="proposal-workspace">Order proposals · original versus proposed</h3>
        {!snapshot.proposals?.length && <p>No authoritative order proposal records supplied.</p>}
        {snapshot.proposals?.map(proposal => <article key={`${proposal.id}:${proposal.version}`}><h4>Proposal {proposal.id} · version {proposal.version}</h4>
          <p>Source state: {shown(proposal.state)} · Sending state: {shown(proposal.sentState)} · Valid until: {timestamp(proposal.expiresAt)}</p>
          <p>{assentLabel(proposal, now)}</p><p>Change reason: {shown(proposal.reason)} · Backend terms hash: {shown(proposal.terms.hash)}</p>
          <p>Assessment / version / freshness: {shown(proposal.assessmentId)} / {shown(proposal.assessmentVersion)} / {shown(proposal.assessmentFreshness)}</p>
          <p>Assent evidence: {proposal.assent?.evidence?.join(', ') || 'Not available'}</p>
          <DecisionTermsView terms={proposal.terms} title="Exact proposed terms (not current agreement)" financial={snapshot.financialAccess === 'AUTHORIZED'} />
          <TermsComparison original={snapshot.exactOriginal} proposed={proposal.terms} financial={snapshot.financialAccess === 'AUTHORIZED'} /></article>)}
        <ProposalPreparation key={`proposal:${auth.tenantId}:${auth.actorId}:${order.id}:${source.cacheKey}:${query.dataUpdatedAt}:${query.isFetching}`} base={snapshot.exactOriginal} financial={snapshot.financialAccess === 'AUTHORIZED'} />
        <p><strong>Submit proposal — unavailable.</strong> No sending, customer assent or durable proposal is created by local preparation.</p>
      </section>
      <section className="decision-panel" aria-labelledby="rejection-review"><h3 id="rejection-review">Order rejection</h3>
        <p><strong>Reject order — unavailable.</strong> Required reason, role, version, idempotency and audit response depend on a verified order rejection contract. No local lifecycle update occurs.</p></section>
      <section className="decision-panel" aria-labelledby="amendment-workspace"><h3 id="amendment-workspace">Order amendments · preserve confirmed terms</h3>
        <p>Legacy Core state: {shown(snapshot.legacyCommitmentState)}. A legacy CONFIRMED agreement is not v2.2 ACCEPTED/reserved status.</p>
        <DecisionTermsView terms={snapshot.currentAgreement?.terms} title="Currently confirmed agreement (preserved)" financial={snapshot.financialAccess === 'AUTHORIZED'} />
        <p>Current agreement version: {shown(snapshot.currentAgreement?.version)}</p>
        {(snapshot.previousAgreements ?? []).map(agreement => <article key={agreement.version}><h4>Previous confirmed version {agreement.version}</h4>
          <DecisionTermsView terms={agreement.terms} title="Previous accepted terms record" financial={snapshot.financialAccess === 'AUTHORIZED'} />
          <p>Effective: {timestamp(agreement.effectiveAt)} · Audit evidence: {agreement.evidence?.join(', ') || 'Not available'}</p></article>)}
        {!snapshot.previousAgreements?.length && <p>Previous confirmed agreement records not available; history is not reconstructed from guesses.</p>}
        {snapshot.amendment ? <><p>Amendment {snapshot.amendment.id} · version {snapshot.amendment.version} · State: {shown(snapshot.amendment.state)}</p>
          <p>Initiator: {shown(snapshot.amendment.initiator)} · Reason: {shown(snapshot.amendment.reason)} · Consent required: {shown(snapshot.amendment.consentRequired)}</p>
          <p>Feasibility/reservation consequences: {snapshot.amendment.consequences?.join('; ') || 'Not verified'}</p>
          <TermsComparison original={snapshot.currentAgreement?.terms} proposed={snapshot.amendment.proposed} financial={snapshot.financialAccess === 'AUTHORIZED'}
            originalLabel="Currently confirmed terms (preserved)" proposedLabel="Backend-proposed amendment (not effective)" />
          <p>Amendment audit evidence: {snapshot.amendment.evidence?.join(', ') || 'Not available'}</p></> : <p>No authoritative amendment record supplied.</p>}
        {snapshot.currentAgreement ? <ProposalPreparation key={`amendment:${auth.tenantId}:${auth.actorId}:${order.id}:${source.cacheKey}:${query.dataUpdatedAt}:${query.isFetching}`} base={snapshot.currentAgreement.terms} financial={snapshot.financialAccess === 'AUTHORIZED'} amendment /> : <p>Amendment preparation requires an authoritative current agreement record.</p>}
        <p><strong>Submit amendment — unavailable.</strong> Backend decides effectiveness after exact assent, reassessment and reservation adjustment. Existing terms/resources remain unchanged.</p>
      </section>
      <DecisionTimeline snapshot={snapshot} />
    </>}
  </section>;
}
