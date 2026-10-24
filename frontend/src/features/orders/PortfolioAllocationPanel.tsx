import { Link } from 'react-router-dom';
import { ContentCard } from '../../shared/ui';
import { timestamp } from './queue';
import type { PortfolioAllocation, PortfolioScenario, PortfolioSnapshot } from './portfolioTypes';
import { metricText, scenarioUsable } from './portfolioView';
export function supportedAllocation(s:PortfolioScenario, a?:PortfolioAllocation) {
 return scenarioUsable(s) && !!a?.evidence.length;
}
const labels={INCLUDED:'Include',DEFERRED:'Defer',EXCLUDED:'Exclude',UNKNOWN:'Unknown'};
export function PortfolioAllocationPanel({data,scenario,now}:{data?:PortfolioSnapshot;scenario?:PortfolioScenario;now:number}) {
 return <ContentCard title="Order Allocation" className="pc-allocation">
  <p>Strategy recommendations are advisory and do not accept orders or reserve resources.</p>
  {!data || !scenario ? <div className="pc-dependency"><strong>Solver allocation unavailable</strong><p>Requires source-bound order IDs, request versions, explicit membership and reasons. Queue ordering is not a portfolio allocation.</p></div> : <>
   <div className="pc-allocation-meta"><span>Selected Strategy: <strong>{scenario.label}</strong></span><span>Solver Run ID: Unavailable</span><span>Scenario: {scenario.id} · v{scenario.version}</span></div>
   <dl className="pc-allocation-counts">{([['included','Included'],['deferred','Deferred'],['excluded','Excluded']] as const).map(([key,label])=><div key={key}><dt>{label}</dt><dd>{metricText(data,scenario,key,now)}</dd></div>)}</dl>
   {!scenarioUsable(scenario) ? <p className="pc-dependency">Allocation withheld: solver status or validation is not usable. No Include, Defer or Exclude recommendation is inferred.</p> : !data.orders.length ? <p>No source-provided order identities.</p> :
    <div className="pc-scroll" tabIndex={0} role="region" aria-label="Selected strategy order allocation, scroll horizontally"><table><caption>Selected strategy proposed allocations</caption><thead><tr>{['Order','Quantity','Requested Delivery','Recommendation','Reason','Action'].map(label=><th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{data.orders.map(order=>{
     const allocation=scenario.allocations.find(a=>a.orderId===order.id);const supported=supportedAllocation(scenario,allocation);
     return <tr key={order.id}><th scope="row"><strong>{order.id}</strong><small>{order.customerReference||'Customer unavailable'} · Request v{order.requestVersion}</small></th><td>Unavailable · quantity contract missing</td><td>{timestamp(order.deadline)}</td><td><span className={`pc-membership pc-membership-${supported?allocation!.membership:'UNKNOWN'}`}>{supported?labels[allocation!.membership]:'Unknown'}</span></td><td>{supported?allocation?.reason||'Source reason unavailable':'Source allocation evidence unavailable'}<small>Evidence: {supported?allocation?.evidence.join(', '):'Unavailable'}</small></td><td><Link to={`/orders/${encodeURIComponent(order.id)}`} aria-label={`View Details for ${order.id}`}>View Details</Link></td></tr>;
    })}</tbody></table></div>}
  </>}
 </ContentCard>;
}
