import type { RequestAuthHeaders } from '../../shared/api';
import type { EvidenceTier, IntegrationMode } from '../../shared/ui';

/** Provisional presentation contract, NOT a Backend DTO or published API. */
export const portfolioDimensions = [
  ['included', 'Included orders'], ['excluded', 'Excluded orders'], ['deferred', 'Deferred orders'],
  ['delivery', 'Delivery feasibility'], ['workload', 'Production workload'], ['capacity', 'Capacity utilization'],
  ['materials', 'Material availability'], ['revenue', 'Expected revenue'], ['cost', 'Estimated cost'],
  ['profit', 'Estimated profit'], ['margin', 'Estimated margin'], ['risk', 'Delivery risk'],
  ['violations', 'Constraint violations'], ['score', 'Objective score'],
] as const;
export type PortfolioDimension = typeof portfolioDimensions[number][0];
export interface PortfolioMetric {
  state: 'KNOWN' | 'UNKNOWN' | 'REDACTED';
  value?: string; unit?: string; evidence: string[];
  /** Complete authorized price/cost model; never inferred by the browser. */
  financialModelComplete?: boolean;
}
export interface PortfolioOrder {
  id: string; requestVersion: string; customerReference?: string; deadline?: string;
  evidence: string[];
}
export interface PortfolioAllocation {
  orderId: string; requestVersion: string;
  membership: 'INCLUDED' | 'EXCLUDED' | 'DEFERRED' | 'UNKNOWN';
  reason?: string; resources?: string; conflict?: string; evidence: string[];
}
export interface PortfolioScenario {
  id: string; version: string; label: string; strategy: 'FCFS' | 'PROFIT' | 'EXPIRY' | 'ALTERNATIVE';
  snapshotId: string; snapshotVersion: string; objectiveId: string; modelVersion: string; constraintPolicy: string;
  validation: 'VALIDATED' | 'UNKNOWN' | 'VALIDATION_MISMATCH';
  solverStatus: string; evidence: string[];
  metrics: Partial<Record<PortfolioDimension, PortfolioMetric>>;
  allocations: PortfolioAllocation[];
  constraints: { id: string; description: string; severity?: string; status: string; source: string;
    orderIds: string[]; resources: string[]; evidence: string[]; uncertainty?: string }[];
}
export interface PortfolioSnapshot {
  tenantId: string; actorId: string; readAuthorized: boolean; financialAccess: 'AUTHORIZED' | 'REDACTED' | 'UNKNOWN';
  source: string; sourceVerified: boolean; evidenceTier: EvidenceTier; integrationMode: IntegrationMode;
  snapshotId: string; snapshotVersion: string; currentVersion: string;
  updatedAt: string; expiresAt: string; freshness: 'CURRENT' | 'STALE' | 'UNKNOWN';
  coverage: 'COMPLETE' | 'PARTIAL'; evidence: string[];
  orders: PortfolioOrder[]; scenarios: PortfolioScenario[];
  recommendation?: { scenarioId: string; scenarioVersion: string; snapshotId: string; snapshotVersion: string;
    source: string; authority: 'BACKEND' | 'DIAGNOSTIC'; objectiveId: string; modelVersion: string;
    constraintPolicy: string; reason: string; limitations: string[]; evidence: string[]; issuedAt: string; expiresAt: string };
}
export interface PortfolioSource {
  cacheKey: string;
  load(auth: RequestAuthHeaders, signal: AbortSignal): Promise<PortfolioSnapshot>;
}
