// Synthetic test-only presentation models. No transport, production import or optimizer.
import type { PortfolioMetric, PortfolioSnapshot } from './portfolioTypes';
export const portfolioTestNow = Date.parse('2026-10-24T03:00:00Z');
export const knownMetric = (value = '10', unit = 'MYR'): PortfolioMetric => ({
  state: 'KNOWN', value, unit, evidence: ['synthetic-metric-evidence'], financialModelComplete: true,
});
export function portfolioFixture(): PortfolioSnapshot {
  return {
    tenantId: 'test-tenant', actorId: 'user_owner_01', readAuthorized: true, financialAccess: 'AUTHORIZED',
    source: 'Synthetic test-only source', sourceVerified: true, evidenceTier: 'DEMO-ONLY', integrationMode: 'SYNTHETIC',
    snapshotId: 'synthetic-snapshot', snapshotVersion: '7', currentVersion: '7',
    updatedAt: '2026-10-24T02:00:00Z', expiresAt: '2026-10-24T04:00:00Z', freshness: 'CURRENT',
    coverage: 'COMPLETE', evidence: ['synthetic-source-evidence'],
    orders: ['one', 'two', 'three'].map(id => ({ id, requestVersion: '2', customerReference: `Synthetic customer ${id}`,
      deadline: '2026-10-25T12:00:00Z', evidence: [`synthetic-request-${id}`] })),
    scenarios: ['FCFS', 'PROFIT'].map((strategy, i) => ({ id: `s${i}`, version: '1', label: i ? 'Profit candidate' : 'First come first served',
      strategy: strategy as 'FCFS' | 'PROFIT', snapshotId: 'synthetic-snapshot', snapshotVersion: '7',
      objectiveId: 'synthetic-objective', modelVersion: '1', constraintPolicy: 'synthetic-policy', validation: 'VALIDATED',
      solverStatus: i ? 'FEASIBLE_NOT_PROVEN_OPTIMAL' : 'NOT_APPLICABLE', evidence: ['synthetic-scenario'],
      metrics: { included: knownMetric(i ? '2' : '1', 'orders'), revenue: knownMetric('100'), cost: knownMetric('80'),
        profit: knownMetric('20'), margin: knownMetric('20', '%'), capacity: knownMetric('50', '%'), score: knownMetric('8', 'points') },
      allocations: ['one', 'two', 'three'].map((orderId, j) => ({ orderId, requestVersion: '2',
        membership: (['INCLUDED', 'EXCLUDED', 'DEFERRED'] as const)[(i + j) % 3],
        reason: j === 1 ? 'Not selected under source objective; not proof of hard infeasibility' : 'Source allocation reason',
        resources: 'Synthetic machine A', conflict: 'Source deadline uncertainty', evidence: ['synthetic-allocation'] })),
      constraints: [{ id: 'constraint1', description: 'Source-reported capacity bottleneck', severity: 'HIGH', status: 'OPEN',
        source: 'Synthetic P2 test evidence', orderIds: ['one'], resources: ['machine-A'], evidence: ['synthetic-constraint'],
        uncertainty: 'Supplier availability not independently verified' }],
    })),
    recommendation: { scenarioId: 's1', scenarioVersion: '1', snapshotId: 'synthetic-snapshot', snapshotVersion: '7',
      source: 'Synthetic recommendation test record', authority: 'BACKEND', objectiveId: 'synthetic-objective', modelVersion: '1',
      constraintPolicy: 'synthetic-policy', reason: 'Source-provided trade-off explanation', limitations: ['Source limitation'],
      evidence: ['synthetic-recommendation'], issuedAt: '2026-10-24T02:10:00Z', expiresAt: '2026-10-24T03:30:00Z' },
  };
}

/** Explicitly synthetic Expiry scenario; never imported by production or computed in the UI. */
export function portfolioWithExpiryFixture(): PortfolioSnapshot {
  const data = portfolioFixture();
  data.scenarios.push({ ...structuredClone(data.scenarios[0]), id: 's-expiry', label: 'Expiry-aware candidate', strategy: 'EXPIRY',
    solverStatus: 'FEASIBLE_NOT_PROVEN_OPTIMAL', evidence: ['synthetic-expiry-scenario'],
    allocations: data.orders.map(order => ({ orderId: order.id, requestVersion: order.requestVersion,
      membership: 'DEFERRED', reason: 'Synthetic expiry test explanation', resources: 'Synthetic lot / machine reference',
      conflict: 'Synthetic constraint finding', evidence: ['synthetic-expiry-allocation'] })),
  });
  return data;
}
