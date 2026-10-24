import { apiRequest, authHeaders } from '../../shared/api';
import { record } from './detailApi';
import type { OrderDetail } from './detailTypes';
import type { DecisionEvent, DecisionTerms, OrderDecisionSnapshot, OrderDecisionSource } from './decisionTypes';

function requiredText(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error('Invalid Core read contract');
  return value;
}
const maybeText = (value: unknown) => typeof value === 'string' ? value : null;
function refs(value: unknown): string[] {
  if (!Array.isArray(value) || value.some(item => typeof item !== 'string')) throw new Error('Invalid Core evidence list');
  return value;
}
const versionText = (value: unknown) => {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) throw new Error('Invalid Core version');
  return String(value);
};

/** Exact existing Core DTO: no price, terms hash, assent, reservation or request-version promotion. */
export function mapCoreDecision(raw: unknown, order: OrderDetail, tenant: string): OrderDecisionSnapshot {
  const c = record(raw);
  if (!order.commitmentId || c.commitment_id !== order.commitmentId || c.order_id !== order.id || c.tenant_id !== tenant ||
      (order.customer && c.customer_id !== order.customer)) throw new Error('Core/order binding mismatch');
  const terms = record(c.terms);
  const lines = terms.items == null ? [terms] : terms.items;
  if (!Array.isArray(lines)) throw new Error('Invalid Core terms');
  const view: DecisionTerms = { basis: 'LEGACY_CORE_TERMS', customerId: requiredText(c.customer_id),
    lines: lines.map(rawLine => { const line = record(rawLine); return { sku: requiredText(line.sku), quantity: requiredText(line.quantity), unit: requiredText(line.unit) }; }),
    deadline: maybeText(terms.deadline), instructions: maybeText(terms.special_instructions), evidence: refs(c.evidence_refs) };
  const state = requiredText(c.agreement_state); const version = versionText(c.commitment_version);
  return { tenantId: tenant, orderId: order.id, sourceLabel: 'Existing Core commitment read (development identity)',
    financialAccess: 'UNKNOWN', currentAgreement: state === 'CONFIRMED' ? { version, terms: view, evidence: view.evidence } : null,
    legacyCommitmentState: state, events: [], warnings: [
      `Core commitment ${order.commitmentId} reports ${state} at commitment version ${version}. This does not establish v2.2 order acceptance, canonical terms identity, price disclosure, exact customer assent or reservation.`,
    ] };
}

/** Timeline scope is verified by the preceding tenant/order-bound Core lookup and server route. */
export function mapCoreTimeline(raw: unknown): DecisionEvent[] {
  if (!Array.isArray(raw)) throw new Error('Invalid Core timeline');
  const rows = raw.map(value => {
    const e = record(value); const state = e.new_state == null ? {} : record(e.new_state);
    const dimensions = ['agreement_state', 'feasibility_state', 'risk_state', 'recovery_state', 'fulfilment_state'];
    return { id: requiredText(e.entry_id), at: maybeText(e.occurred_at), actor: requiredText(e.actor_id), role: requiredText(e.actor_role),
      eventType: requiredText(e.event_type), action: maybeText(e.action), reason: maybeText(e.approval_reason),
      commitmentVersion: e.commitment_version == null ? null : versionText(e.commitment_version),
      proposalId: maybeText(e.proposal_id), evidence: refs(e.evidence_refs),
      recordedState: dimensions.filter(key => typeof state[key] === 'string').map(key => `${key}: ${state[key]}`).join('; ') || null };
  });
  if (new Set(rows.map(row => row.id)).size !== rows.length) throw new Error('Duplicate timeline IDs');
  return rows;
}

/** Read-only production boundary. There is deliberately no command transport or preview-key configuration. */
export const coreOrderDecisionSource: OrderDecisionSource = {
  cacheKey: 'legacy-core-decision-read-v1',
  async load(order, auth, signal) {
    if (order.tenantId !== auth.tenantId) throw new Error('Order tenant mismatch');
    if (!order.commitmentId) return { tenantId: auth.tenantId, orderId: order.id, financialAccess: 'UNKNOWN',
      sourceLabel: 'No explicit Core commitment link supplied', events: [], warnings: ['Exact order decision, proposal, amendment and receipt APIs are unavailable. No command has been sent.'] };
    const path = `/v1/commitments/${encodeURIComponent(order.commitmentId)}`;
    const read = (url: string) => apiRequest<unknown>(url, { headers: authHeaders(auth), signal });
    const snapshot = mapCoreDecision(await read(path), order, auth.tenantId);
    // A failed timeline read fails visibly; it must not masquerade as an empty audit history.
    return { ...snapshot, events: mapCoreTimeline(await read(`${path}/timeline`)) };
  },
};
