import { ContentCard } from '../../shared/ui';
import { timestamp } from './queue';
import { verifiedRecommendation } from './portfolioView';
import type { PortfolioScenario, PortfolioSnapshot } from './portfolioTypes';
const dependencies=[
 ['Inventory Constraints','Verified material availability, BOM requirements and shortage evidence require typed P2 findings.'],
 ['Capacity Constraints','Resource units, production workload and an authoritative time window are not supplied.'],
 ['Expiry Constraints','Relevant lot IDs, expiry windows and waste exposure are not supplied.'],
 ['Delivery Constraints','Requested deadlines alone do not establish source-computed deadline conflicts.'],
];
export function PortfolioSolverExplanation({data,scenario,now}:{data?:PortfolioSnapshot;scenario?:PortfolioScenario;now:number}) {
 const recommendation=data&&verifiedRecommendation(data,now);
 const explanation=recommendation&&recommendation.scenarioId===scenario?.id?recommendation:null;
 return <ContentCard title="Solver Explanation & Constraints" className="pc-explanation">
  <p>{explanation?explanation.reason:'Solver explanation is not available.'}</p>
  <p>Only source-provided explanations are shown. No text is generated to justify missing allocations.</p>
  <dl className="pc-scope-grid">{[
   ['Solver Run ID','Unavailable'],['Solver Status',scenario?.solverStatus||'Solver unavailable'],
   ['Selected Strategy',scenario?.label||'Not evaluated'],['Execution Time','Unavailable'],
   ['Input Snapshot Version',data?`${data.snapshotId} · v${data.snapshotVersion}`:'Unavailable'],
   ['Considered Order Count','Unavailable · eligibility not supplied'],
   ['Source Timestamp',data?timestamp(data.updatedAt):'Unavailable'],
   ['Validation',scenario?.validation||'Unknown'],
  ].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  {scenario&&<p>Scenario {scenario.id} · v{scenario.version} · Objective {scenario.objectiveId} · Model {scenario.modelVersion} · Policy {scenario.constraintPolicy}. Evidence: {scenario.evidence.join(', ')}</p>}
  <div className="pc-constraint-groups">{dependencies.map(([label,description])=><section key={label}><h4>{label}</h4><p>Unavailable · typed constraint category not supplied.</p><p>{description}</p></section>)}</div>
  <p>Source findings are kept in their original classification below; descriptions are not used to guess a constraint category.</p>
  {scenario?.constraints.length ? <ul aria-label="Selected scenario finding references">{scenario.constraints.map(c=><li key={c.id}>{c.id} · {c.status} · {c.source} · Evidence: {c.evidence.join(', ')}</li>)}</ul> : <p>No source finding references supplied; this is not evidence of unconstrained capacity.</p>}
  {explanation&&<p>Explanation source: {explanation.source} · Evidence: {explanation.evidence.join(', ')}</p>}
  <p className="pc-context-note">Strategy recommendations are advisory and do not accept orders or reserve resources. Changed or expired inputs require revalidation; a scenario has not been executed.</p>
 </ContentCard>;
}
