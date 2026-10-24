import type { OrderDetail } from './detailTypes';
import type { RequestAuthHeaders } from '../../shared/api';

/** Local presentation types only. No v2.2 wire/command contract is declared. */
export interface DecisionTerms {
  basis: 'BACKEND_EXACT_TERMS' | 'LEGACY_CORE_TERMS';
  revision?: string | null; requestVersion?: string | null; hash?: string | null;
  customerId?: string | null; customerVerified?: boolean;
  lines: { sku: string; variant?: string | null; quantity: string; unit: string; unitPrice?: string | null }[];
  price?: string | null; currency?: string | null; priceSource?: string | null; priceSourceVersion?: string | null;
  priceVerified?: boolean; disclosed?: boolean; disclosureEvidence?: string[];
  fees?: string | null; tax?: string | null; discount?: string | null;
  method?: string | null; deadline?: string | null; windowStart?: string | null;
  location?: string | null; businessTimezone?: string | null; instructions?: string | null;
  conditions?: string[]; policyRef?: string | null; evidence?: string[];
}
export interface ProposalView {
  id: string; version: string; terms: DecisionTerms; state?: string | null; sentState?: string | null;
  reason?: string | null; expiresAt?: string | null; superseded?: boolean;
  assessmentId?: string | null; assessmentVersion?: string | null; assessmentFreshness?: string | null;
  assent?: { state?: string | null; verified?: boolean; proposalId?: string | null; proposalVersion?: string | null;
    termsHash?: string | null; customerId?: string | null; at?: string | null; evidence?: string[] };
}
export interface AgreementView { version: string; terms: DecisionTerms; evidence?: string[]; effectiveAt?: string | null }
export interface DecisionEvent {
  id: string; at?: string | null; actor?: string | null; role?: string | null;
  eventType: string; action?: string | null; commitmentVersion?: string | null;
  requestVersion?: string | null; proposalId?: string | null; proposalVersion?: string | null;
  termsHash?: string | null; recordedState?: string | null; reason?: string | null;
  receiptId?: string | null; reservationRef?: string | null; evidence: string[];
}
export interface DecisionReceipt {
  id: string; orderId: string; requestVersion?: string | null; termsHash?: string | null;
  outcome: string; auditRef?: string | null; reservationRef?: string | null; reservationVerified?: boolean;
  reservationState?: string | null; reason?: string | null; at?: string | null;
}
export interface OrderDecisionSnapshot {
  tenantId: string; orderId: string; requestVersion?: string | null;
  sourceLabel: string; financialAccess: 'AUTHORIZED' | 'REDACTED' | 'UNKNOWN';
  exactOriginal?: DecisionTerms | null; proposals?: ProposalView[];
  currentAgreement?: AgreementView | null; previousAgreements?: AgreementView[];
  amendment?: { id: string; version: string; state?: string | null; reason?: string | null; initiator?: string | null;
    proposed: DecisionTerms; consentRequired?: string | null; consequences?: string[]; evidence?: string[] } | null;
  backendBlockers?: string[]; events: DecisionEvent[]; receipts?: DecisionReceipt[];
  legacyCommitmentState?: string | null; warnings?: string[];
}
export interface OrderDecisionSource {
  cacheKey: string;
  load: (order: OrderDetail, auth: RequestAuthHeaders, signal: AbortSignal) => Promise<OrderDecisionSnapshot>;
}

/** Ephemeral comparison input; never a saved proposal, canonical DTO, hash or assent. */
export type PreparedTerms = Pick<DecisionTerms, 'lines' | 'price' | 'currency' | 'fees' | 'tax' | 'discount' |
  'method' | 'deadline' | 'windowStart' | 'location' | 'businessTimezone' | 'instructions' | 'conditions' | 'policyRef'>;
