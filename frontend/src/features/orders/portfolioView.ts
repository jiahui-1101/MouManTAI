import { instant } from './queue';
import { portfolioFresh } from './portfolioSource';
import type { PortfolioDimension, PortfolioScenario, PortfolioSnapshot } from './portfolioTypes';

export const financialDimensions = new Set<PortfolioDimension>(['revenue', 'cost', 'profit', 'margin']);
export function metricText(data: PortfolioSnapshot, scenario: PortfolioScenario, key: PortfolioDimension, now: number): string {
  const metric = scenario.metrics[key];
  if (metric?.state === 'REDACTED' || (financialDimensions.has(key) && data.financialAccess === 'REDACTED')) return 'Redacted';
  if (!portfolioFresh(data, now) || scenario.validation !== 'VALIDATED' || !metric || metric.state !== 'KNOWN' ||
    !metric.evidence.length || (financialDimensions.has(key) &&
      (data.financialAccess !== 'AUTHORIZED' || metric.financialModelComplete !== true || !metric.unit?.trim() ||
        !/^-?\d+(\.\d+)?$/.test(metric.value ?? '')))) return 'Unknown';
  return `${metric.value}${metric.unit ? ` ${metric.unit}` : ''}`;
}
const normalize = (value: string) => /^-?\d+(\.\d+)?$/.test(value)
  ? value.replace(/^(-?)0+(?=\d)/, '$1').replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '').replace(/^-0$/, '0') : value;
export function metricDifference(data: PortfolioSnapshot, scenarios: PortfolioScenario[], key: PortfolioDimension, now: number): string {
  if (scenarios.length < 2) return 'Select at least two scenarios';
  const first = scenarios[0];
  const values = scenarios.map(s => metricText(data, s, key, now));
  if (values.some(value => ['Unknown', 'Redacted'].includes(value))) return 'Not comparable';
  if (scenarios.some(s => s.objectiveId !== first.objectiveId || s.modelVersion !== first.modelVersion ||
    s.constraintPolicy !== first.constraintPolicy || s.metrics[key]?.unit !== first.metrics[key]?.unit)) return 'Not comparable';
  return new Set(scenarios.map(s => normalize(s.metrics[key]!.value!))).size > 1 ? 'Verified difference · no improvement implied' : 'Same source value';
}
export function verifiedRecommendation(data: PortfolioSnapshot, now: number) {
  const r = data.recommendation;
  if (!r || !portfolioFresh(data, now) || data.coverage !== 'COMPLETE' || data.integrationMode !== 'LIVE' ||
    !['VALIDATED', 'LIVE'].includes(data.evidenceTier) || r.authority !== 'BACKEND' ||
    r.snapshotId !== data.snapshotId || r.snapshotVersion !== data.snapshotVersion ||
    ![r.source, r.reason, r.scenarioId, r.scenarioVersion, r.objectiveId, r.modelVersion, r.constraintPolicy, r.issuedAt, r.expiresAt]
      .every(v => typeof v === 'string' && v.trim()) ||
    !Array.isArray(r.evidence) || !r.evidence.length || !r.evidence.every(v => typeof v === 'string' && v.trim()) ||
    !Array.isArray(r.limitations) || !r.limitations.every(v => typeof v === 'string') ||
    instant(r.issuedAt) === null || instant(r.expiresAt) === null || instant(r.issuedAt)! < instant(data.updatedAt)! ||
    instant(r.issuedAt)! > now || instant(r.expiresAt)! <= now || instant(r.expiresAt)! > instant(data.expiresAt)!) return null;
  const s = data.scenarios.find(s => s.id === r.scenarioId && s.version === r.scenarioVersion && s.validation === 'VALIDATED' &&
    s.objectiveId === r.objectiveId && s.modelVersion === r.modelVersion && s.constraintPolicy === r.constraintPolicy &&
    ['OPTIMAL', 'FEASIBLE_NOT_PROVEN_OPTIMAL', 'NOT_APPLICABLE'].includes(s.solverStatus) &&
    // A redacted display string is not a usable profit value, even with snapshot-level authorization.
    (s.strategy !== 'PROFIT' || (data.financialAccess === 'AUTHORIZED' && s.metrics.profit?.state === 'KNOWN' &&
      metricText(data, s, 'profit', now) !== 'Unknown')));
  return s ? { ...r, label: s.label } : null;
}
