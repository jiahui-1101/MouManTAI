import { describe, expect, it } from 'vitest';
import { metricDifference, metricText, verifiedRecommendation } from './portfolioView';
import { validatePortfolio } from './portfolioSource';
import { knownMetric, portfolioFixture, portfolioTestNow as now } from './portfolioTest.fixtures';
import type { PortfolioSnapshot } from './portfolioTypes';

const auth = { tenantId: 'test-tenant', actorId: 'user_owner_01' };
const withRecommendation = () => { const d = portfolioFixture(); d.integrationMode = 'LIVE'; d.evidenceTier = 'VALIDATED'; return d; };
describe('Portfolio identity and version boundary', () => {
  it('accepts complete presentation data without modifying source', () => {
    const d = portfolioFixture(); const before = structuredClone(d);
    expect(validatePortfolio(d, auth)).toBe(d); expect(d).toEqual(before);
  });
  it.each<[string, (d: PortfolioSnapshot) => void]>([
    ['wrong tenant', d => { d.tenantId = 'foreign'; }], ['wrong actor', d => { d.actorId = 'foreign'; }],
    ['denied read', d => { d.readAuthorized = false; }],
    ['wrong order', d => { d.scenarios[0].allocations[0].orderId = 'foreign'; }],
    ['wrong request version', d => { d.scenarios[0].allocations[0].requestVersion = '99'; }],
    ['wrong scenario snapshot', d => { d.scenarios[0].snapshotId = 'other'; }],
    ['wrong scenario version', d => { d.scenarios[0].snapshotVersion = '99'; }],
    ['duplicate scenario', d => { d.scenarios.push(d.scenarios[0]); }],
    ['duplicate order', d => { d.orders.push(d.orders[0]); }],
    ['duplicate allocation', d => { d.scenarios[0].allocations.push(d.scenarios[0].allocations[0]); }],
    ['missing scenario evidence', d => { d.scenarios[0].evidence = []; }],
    ['foreign constraint order', d => { d.scenarios[0].constraints[0].orderIds = ['foreign']; }],
    ['missing constraint evidence', d => { d.scenarios[0].constraints[0].evidence = []; }],
    ['naive timestamp', d => { d.updatedAt = '2026-10-24T02:00:00'; }],
    ['invalid expiry', d => { d.expiresAt = d.updatedAt; }],
  ])('rejects %s', (_, edit) => { const d = portfolioFixture(); edit(d); expect(() => validatePortfolio(d, auth)).toThrow(); });
});
describe('Portfolio financial and comparison safety', () => {
  it.each(['revenue', 'cost', 'profit', 'margin'] as const)('hides %s without authorization or complete model', key => {
    const d = portfolioFixture(); const s = d.scenarios[0];
    d.financialAccess = 'REDACTED'; expect(metricText(d, s, key, now)).toBe('Redacted');
    d.financialAccess = 'UNKNOWN'; expect(metricText(d, s, key, now)).toBe('Unknown');
    d.financialAccess = 'AUTHORIZED'; s.metrics[key]!.financialModelComplete = false;
    expect(metricText(d, s, key, now)).toBe('Unknown');
  });
  it('never defaults missing profit to zero or derives it from revenue/cost', () => {
    const d = portfolioFixture(); delete d.scenarios[0].metrics.profit;
    expect(metricText(d, d.scenarios[0], 'profit', now)).toBe('Unknown');
  });
  it('retains an explicitly verified zero', () => {
    const d = portfolioFixture(); d.scenarios[0].metrics.profit = knownMetric('0');
    expect(metricText(d, d.scenarios[0], 'profit', now)).toBe('0 MYR');
  });
  it.each(['objectiveId', 'modelVersion', 'constraintPolicy'] as const)('does not compare different %s', key => {
    const d = portfolioFixture(); d.scenarios[1][key] = 'different';
    expect(metricDifference(d, d.scenarios, 'included', now)).toBe('Not comparable');
  });
  it('does not compare different units or missing evidence', () => {
    const d = portfolioFixture(); d.scenarios[1].metrics.included!.unit = 'batches';
    expect(metricDifference(d, d.scenarios, 'included', now)).toBe('Not comparable');
    d.scenarios[1].metrics.included!.unit = 'orders'; d.scenarios[1].metrics.included!.evidence = [];
    expect(metricDifference(d, d.scenarios, 'included', now)).toBe('Not comparable');
  });
  it('describes verified differences without claiming improvement; decimal equivalents are equal', () => {
    const d = portfolioFixture(); expect(metricDifference(d, d.scenarios, 'included', now)).toContain('no improvement implied');
    d.scenarios[0].metrics.included!.value = '02.00';
    expect(metricDifference(d, d.scenarios, 'included', now)).toBe('Same source value');
  });
  it.each(['UNKNOWN', 'VALIDATION_MISMATCH'] as const)('withholds positive metrics for %s', validation => {
    const d = portfolioFixture(); d.scenarios[0].validation = validation;
    expect(metricText(d, d.scenarios[0], 'capacity', now)).toBe('Unknown');
  });
});
describe('Recommendation authority', () => {
  it('supports an explicitly authorized complete source record only', () => {
    expect(verifiedRecommendation(withRecommendation(), now)?.label).toBe('Profit candidate');
    expect(verifiedRecommendation(portfolioFixture(), now)).toBeNull();
  });
  it.each<[string, (d: PortfolioSnapshot) => void]>([
    ['individually redacted profit', d => { d.scenarios[1].metrics.profit!.state = 'REDACTED'; }],
    ['unknown profit', d => { d.scenarios[1].metrics.profit!.state = 'UNKNOWN'; }],
    ['missing profit metric', d => { delete d.scenarios[1].metrics.profit; }],
    ['redacted financial access', d => { d.financialAccess = 'REDACTED'; }],
    ['unknown financial access', d => { d.financialAccess = 'UNKNOWN'; }],
    ['incomplete financial model', d => { d.scenarios[1].metrics.profit!.financialModelComplete = false; }],
    ['unknown financial completeness', d => { delete d.scenarios[1].metrics.profit!.financialModelComplete; }],
    ['missing profit evidence', d => { d.scenarios[1].metrics.profit!.evidence = []; }],
    ['missing profit unit', d => { delete d.scenarios[1].metrics.profit!.unit; }],
    ['blank profit unit', d => { d.scenarios[1].metrics.profit!.unit = ' '; }],
    ['missing profit value', d => { delete d.scenarios[1].metrics.profit!.value; }],
    ['empty profit value', d => { d.scenarios[1].metrics.profit!.value = ''; }],
    ['unavailable profit value', d => { d.scenarios[1].metrics.profit!.value = 'Unavailable'; }],
    ['non-finite profit value', d => { d.scenarios[1].metrics.profit!.value = 'NaN'; }],
  ])('withholds a backend Profit recommendation with %s', (_, edit) => {
    const d = withRecommendation(); edit(d); const before = structuredClone(d);
    expect(verifiedRecommendation(d, now)).toBeNull(); expect(d).toEqual(before);
  });
  it.each(['20', '0', '0.00', '-2.50'])('preserves a source recommendation with usable profit %s without local ranking', value => {
    const d = withRecommendation(); d.scenarios[1].metrics.profit = knownMetric(value);
    const before = structuredClone(d);
    expect(verifiedRecommendation(d, now)).toEqual({ ...d.recommendation, label: 'Profit candidate' });
    expect(d).toEqual(before);
  });
  it.each(['FCFS', 'EXPIRY', 'ALTERNATIVE'] as const)('preserves source-recommended %s scenarios without requiring a profit metric', strategy => {
    const d = withRecommendation(); d.scenarios[1].strategy = strategy;
    delete d.scenarios[1].metrics.profit;
    expect(verifiedRecommendation(d, now)?.scenarioId).toBe(d.recommendation!.scenarioId);
  });
  it.each<[string, (d: PortfolioSnapshot) => void]>([
    ['stale snapshot', d => { d.freshness = 'STALE'; }], ['unknown freshness', d => { d.freshness = 'UNKNOWN'; }],
    ['expired snapshot', d => { d.expiresAt = '2026-10-24T02:59:00Z'; }],
    ['future snapshot', d => { d.updatedAt = '2026-10-24T03:01:00Z'; }],
    ['current version conflict', d => { d.currentVersion = '8'; }],
    ['unverified source', d => { d.sourceVerified = false; }], ['missing source evidence', d => { d.evidence = []; }],
    ['partial coverage', d => { d.coverage = 'PARTIAL'; }],
    ['diagnostic authority', d => { d.recommendation!.authority = 'DIAGNOSTIC'; }],
    ['foreign scenario', d => { d.recommendation!.scenarioId = 'other'; }],
    ['old scenario version', d => { d.recommendation!.scenarioVersion = '2'; }],
    ['wrong snapshot', d => { d.recommendation!.snapshotId = 'other'; }],
    ['wrong snapshot version', d => { d.recommendation!.snapshotVersion = '8'; }],
    ['different objective', d => { d.recommendation!.objectiveId = 'other'; }],
    ['different model', d => { d.recommendation!.modelVersion = 'other'; }],
    ['different policy', d => { d.recommendation!.constraintPolicy = 'other'; }],
    ['missing reason', d => { d.recommendation!.reason = ''; }], ['missing evidence', d => { d.recommendation!.evidence = []; }],
    ['expired recommendation', d => { d.recommendation!.expiresAt = '2026-10-24T02:30:00Z'; }],
    ['future recommendation', d => { d.recommendation!.issuedAt = '2026-10-24T03:01:00Z'; }],
    ['recommendation outlives snapshot', d => { d.recommendation!.expiresAt = '2026-10-25T00:00:00Z'; }],
    ['unvalidated scenario', d => { d.scenarios[1].validation = 'UNKNOWN'; }],
    ['infeasible evaluation', d => { d.scenarios[1].solverStatus = 'INFEASIBLE'; }],
  ])('withholds %s', (_, edit) => { const d = withRecommendation(); edit(d); expect(verifiedRecommendation(d, now)).toBeNull(); });
});
