/** SYNTHETIC test-only input. Imported exclusively by *.test files. */
import type { OrderDetail } from './detailTypes';
import type { DecisionTerms, OrderDecisionSnapshot, ProposalView } from './decisionTypes';
export const decisionNow = Date.parse('2026-10-24T04:00:00Z');
export function requestedTerms(): DecisionTerms {
  return { basis: 'BACKEND_EXACT_TERMS', requestVersion: '7', revision: '3', hash: 'test-backend-hash-original',
    customerId: 'synthetic-customer', customerVerified: true, lines: [{ sku: 'BREAD', quantity: '20', unit: 'pieces', unitPrice: '6' }],
    price: '120', currency: 'MYR', priceSource: 'approved-quote', priceSourceVersion: 'quote-v3', priceVerified: true,
    disclosed: true, disclosureEvidence: ['synthetic-disclosure'], method: 'PICKUP', deadline: '2026-10-25T04:00:00Z',
    instructions: 'Keep dry', conditions: ['No substitution'], evidence: ['synthetic-offer'], fees: '0', tax: '0', discount: '0' };
}
export function decisionOrder(): OrderDetail {
  return { id: 'order-one', tenantId: 'tenant-one', customer: 'synthetic-customer', status: 'PENDING_ACCEPTANCE', version: '7', fields: [{ name: 'sku', status: 'VALID' }],
    assessment: { id: 'assessment-one', snapshotId: 'snapshot-one', orderVersion: '7', status: 'FEASIBLE', snapshotAt: '2026-10-24T03:00:00Z', freshness: 'CURRENT', complete: true, sourceVerified: true } };
}
export function offeredProposal(): ProposalView {
  return { id: 'proposal-one', version: '2', terms: { ...requestedTerms(), hash: 'test-backend-hash-proposal', price: '130' },
    state: 'SOURCE_PENDING', sentState: 'SENT', expiresAt: '2026-10-25T00:00:00Z', reason: 'Revised delivery cost',
    assent: { state: 'AGREED', verified: true, proposalId: 'proposal-one', proposalVersion: '2', termsHash: 'test-backend-hash-proposal',
      customerId: 'synthetic-customer', at: '2026-10-24T03:00:00Z', evidence: ['synthetic-exact-assent'] } };
}
export function decisionSnapshot(): OrderDecisionSnapshot {
  return { tenantId: 'tenant-one', orderId: 'order-one', requestVersion: '7', sourceLabel: 'SYNTHETIC test-only decision projection',
    financialAccess: 'AUTHORIZED', exactOriginal: requestedTerms(), proposals: [offeredProposal()],
    currentAgreement: { version: '4', terms: requestedTerms() }, previousAgreements: [{ version: '3', terms: { ...requestedTerms(), price: '110' }, evidence: ['prior-audit'] }],
    amendment: { id: 'amendment-one', version: '5', state: 'SOURCE_PROPOSED', reason: 'Customer requested later pickup', initiator: 'Synthetic SME',
      proposed: { ...requestedTerms(), deadline: '2026-10-26T04:00:00Z' }, consentRequired: 'Exact customer assent required', consequences: ['Reservation delta not verified'], evidence: ['amendment-audit'] },
    events: [{ id: 'event-one', eventType: 'source.terms_proposed', at: '2026-10-24T01:00:00Z', actor: 'synthetic-manager', role: 'MANAGER', evidence: ['source-audit'], proposalId: 'proposal-one', proposalVersion: '2' }] };
}
