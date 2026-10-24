import { assessmentState } from './detailView';
import { instant } from './queue';
import type { OrderDetail } from './detailTypes';
import type { DecisionReceipt, OrderDecisionSnapshot, ProposalView } from './decisionTypes';

/** This increment has no verified order command; a display check can never grant authority. */
export const commandDependency = 'Unavailable: no verified v2.2 order command, permission, idempotency or receipt-reconciliation contract is configured.';

export function acceptanceBlockers(d: OrderDetail, snapshot: OrderDecisionSnapshot, now: number): string[] {
  const t = snapshot.exactOriginal; const result = [commandDependency];
  if (!t || t.basis !== 'BACKEND_EXACT_TERMS' || !t.hash?.trim()) result.push('Exact customer-offered terms and backend terms identity are not verified.');
  if (!d.version || snapshot.requestVersion !== d.version || t?.requestVersion !== d.version) result.push('Current order request version is missing or inconsistent; a context/commitment version cannot substitute.');
  if (!t?.customerVerified) result.push('Customer identity is not verified for these exact terms.');
  if (snapshot.financialAccess !== 'AUTHORIZED' || !t?.price || !t.currency || !t.priceSource || !t.priceSourceVersion || !t.priceVerified)
    result.push('Authorized price and price provenance are incomplete or redacted.');
  if (!t?.disclosed || !t.disclosureEvidence?.length) result.push('Exact price disclosure / required customer agreement evidence is missing.');
  if (!t?.lines.length || t.lines.some(l => !l.sku.trim() || !l.quantity.trim() || !l.unit.trim()) || !t?.method || instant(t?.deadline) === null)
    result.push('Binding products, quantities, units or fulfilment terms are incomplete.');
  if (assessmentState(d, now) !== 'FEASIBLE') result.push('A current matching feasibility result and backend revalidation are required; conditional/unknown evidence is not permission.');
  if (d.fields?.some(f => f.status !== 'VALID') || d.fieldConflicts?.length) result.push('Captured fields are unresolved, unverified or conflicting.');
  return Array.from(new Set([...result, ...(snapshot.backendBlockers ?? [])]));
}

/** Display-only binding of an already supplied assent record. Never a client assent validator/command gate. */
export function assentLabel(p: ProposalView, now: number): string {
  const a = p.assent; const expires = instant(p.expiresAt); const at = instant(a?.at);
  if (p.superseded) return 'Superseded proposal — assent cannot authorize current terms';
  if (expires === null) return 'Proposal validity unknown — exact assent not verified';
  if (expires <= now) return 'Proposal expired — current acceptance unavailable';
  if (a?.state === 'REJECTED') return 'Source reports customer rejection; no agreement inferred';
  if (p.terms.basis !== 'BACKEND_EXACT_TERMS' || a?.state !== 'AGREED' || !a.verified || !a.evidence?.length || !p.terms.hash ||
      a.proposalId !== p.id || a.proposalVersion !== p.version || a.termsHash !== p.terms.hash ||
      !p.terms.customerId || a.customerId !== p.terms.customerId || at === null || at > now || at >= expires)
    return 'Exact customer assent not verified — sending is not agreement';
  return 'Source-reported exact assent evidence matches displayed proposal; backend revalidation still required';
}

export function receiptLabel(r: DecisionReceipt, snapshot: OrderDecisionSnapshot): string {
  if (r.outcome === 'UNKNOWN' || r.outcome === 'PENDING') return 'Outcome unresolved — reconcile authoritative receipt; do not resubmit';
  if (r.outcome === 'FAILED') return 'Recorded failure — no acceptance inferred';
  const terms = [snapshot.exactOriginal, ...(snapshot.proposals ?? []).map(p => p.terms)].filter(Boolean);
  if (r.outcome === 'ACCEPTED' && r.orderId === snapshot.orderId && !!snapshot.requestVersion && r.requestVersion === snapshot.requestVersion &&
      !!r.termsHash && terms.some(t => t?.hash === r.termsHash) && !!r.auditRef && !!r.reservationRef && r.reservationVerified && r.reservationState === 'CONFIRMED')
    return 'Source records acceptance with a linked verified reservation and audit receipt';
  if (r.outcome === 'REJECTED' && r.orderId === snapshot.orderId && !!r.auditRef) return 'Source records audited rejection';
  return 'Receipt is incomplete or unverified — no final decision inferred';
}
