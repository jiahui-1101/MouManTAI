import { ContentCard } from '../../shared/ui';
import { timestamp } from './queue';
import type { PortfolioSnapshot } from './portfolioTypes';

/** Only an authorized current snapshot may reach this presentation component. */
export function PortfolioAnalysisScope({ data }: { data?: PortfolioSnapshot }) {
  const rows = [
    ['Planning Period', 'Unavailable · no authoritative analysis window supplied'],
    ['Order Scope', data ? `${data.coverage === 'COMPLETE' ? 'Complete' : 'Partial'} returned snapshot · eligibility not inferred` : 'Unavailable · no authorized solver scope'],
    ['Considered Orders', 'Unavailable · solver eligibility not supplied'],
    ['Available Strategies', data ? [...new Set(data.scenarios.map(s => s.strategy))].join(' / ') || 'None returned' : 'Not evaluated'],
    ['Solver Status', data?.scenarios.length ? [...new Set(data.scenarios.map(s => s.solverStatus))].join(' / ') : 'Solver unavailable'],
    ['Source Timestamp', data ? timestamp(data.updatedAt) : 'Unavailable'],
    ['Data Freshness', data ? 'Current verified snapshot' : 'Unknown · revalidation required'],
  ];
  return <ContentCard title="Analysis Scope" className="pc-scope">
    <p>Read-only source scope. Calendar dates are requested context, not a solver query. Queue totals do not establish solver eligibility.</p>
    <dl className="pc-scope-grid">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  </ContentCard>;
}
