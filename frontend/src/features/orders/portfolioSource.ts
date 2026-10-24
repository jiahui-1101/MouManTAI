import { ApiError, type RequestAuthHeaders } from '../../shared/api';
import { instant } from './queue';
import { portfolioDimensions, type PortfolioSnapshot, type PortfolioSource } from './portfolioTypes';

export class PortfolioUnavailableError extends Error {}
export class PortfolioIdentityError extends Error {}
export class PortfolioVersionError extends Error {}
export const unavailablePortfolioSource: PortfolioSource = {
  cacheKey: 'portfolio-api-unavailable-v1',
  async load() { throw new PortfolioUnavailableError('No verified portfolio read API'); },
};

const text = (value: unknown): value is string => typeof value === 'string' && !!value.trim();
const refs = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const unique = (values: string[]) => new Set(values).size === values.length;
const optionalText = (value: unknown) => value === undefined || typeof value === 'string';
function requireContract(valid: unknown): asserts valid {
  if (!valid) throw new PortfolioIdentityError('Portfolio source identity or presentation contract mismatch');
}
/** Validate supplied feature models at the read boundary. A future DTO adapter must map exact server fields first. */
export function validatePortfolio(data: PortfolioSnapshot, auth: RequestAuthHeaders): PortfolioSnapshot {
  requireContract(data && data.tenantId === auth.tenantId && data.actorId === auth.actorId);
  if (data.readAuthorized !== true) throw new ApiError(403, 'FORBIDDEN', 'Portfolio read denied');
  requireContract(text(data.source) && typeof data.sourceVerified === 'boolean' && refs(data.evidence) &&
    ['AUTHORIZED', 'REDACTED', 'UNKNOWN'].includes(data.financialAccess) &&
    ['TARGET', 'DEMO-ONLY', 'VALIDATED', 'LIVE'].includes(data.evidenceTier) &&
    ['LIVE', 'SYNTHETIC', 'MOCK_ORBYTE'].includes(data.integrationMode) &&
    ['CURRENT', 'STALE', 'UNKNOWN'].includes(data.freshness) && ['COMPLETE', 'PARTIAL'].includes(data.coverage) &&
    [data.snapshotId, data.snapshotVersion, data.currentVersion].every(text) &&
    instant(data.updatedAt) !== null && instant(data.expiresAt) !== null &&
    instant(data.expiresAt)! > instant(data.updatedAt)! && Array.isArray(data.orders) && Array.isArray(data.scenarios));
  requireContract(unique(data.orders.map(o => o.id)) && unique(data.scenarios.map(s => s.id)));
  const orders = new Map(data.orders.map(o => [o.id, o.requestVersion]));
  for (const order of data.orders) requireContract(text(order.id) && text(order.requestVersion) && refs(order.evidence) && order.evidence.length &&
    optionalText(order.customerReference) &&
    (order.deadline === undefined || instant(order.deadline) !== null));
  for (const s of data.scenarios) {
    requireContract([s.id, s.version, s.label, s.objectiveId, s.modelVersion, s.constraintPolicy, s.solverStatus].every(text) &&
      ['FCFS', 'PROFIT', 'EXPIRY', 'ALTERNATIVE'].includes(s.strategy) &&
      ['VALIDATED', 'UNKNOWN', 'VALIDATION_MISMATCH'].includes(s.validation) && refs(s.evidence) && s.evidence.length &&
      s.metrics && Array.isArray(s.allocations) && Array.isArray(s.constraints));
    if (s.snapshotId !== data.snapshotId || s.snapshotVersion !== data.snapshotVersion)
      throw new PortfolioVersionError('Scenario snapshot differs from comparison snapshot');
    requireContract(unique(s.allocations.map(a => a.orderId)) && unique(s.constraints.map(c => c.id)));
    for (const a of s.allocations) {
      requireContract(orders.has(a.orderId) && refs(a.evidence) && [a.reason, a.resources, a.conflict].every(optionalText) &&
        ['INCLUDED', 'EXCLUDED', 'DEFERRED', 'UNKNOWN'].includes(a.membership));
      if (orders.get(a.orderId) !== a.requestVersion) throw new PortfolioVersionError('Order request version differs');
    }
    for (const [, metric] of portfolioDimensions.map(([key]) => [key, s.metrics[key]] as const)) {
      if (!metric) continue;
      requireContract(['KNOWN', 'UNKNOWN', 'REDACTED'].includes(metric.state) && refs(metric.evidence) && optionalText(metric.unit) &&
        (metric.state !== 'KNOWN' || text(metric.value)));
    }
    for (const c of s.constraints) requireContract([c.id, c.description, c.status, c.source].every(text) && [c.severity, c.uncertainty].every(optionalText) &&
      refs(c.evidence) && c.evidence.length && refs(c.resources) && refs(c.orderIds) && c.orderIds.every(id => orders.has(id)));
  }
  return data;
}

export function portfolioFresh(data: PortfolioSnapshot, now: number): boolean {
  return data.sourceVerified && data.evidence.length > 0 && data.freshness === 'CURRENT' &&
    data.snapshotVersion === data.currentVersion && instant(data.updatedAt)! <= now && instant(data.expiresAt)! > now;
}
