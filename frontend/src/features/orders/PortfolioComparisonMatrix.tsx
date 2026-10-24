import { ContentCard } from '../../shared/ui';
import type { PortfolioDimension, PortfolioScenario, PortfolioSnapshot } from './portfolioTypes';
import { metricText } from './portfolioView';
const columns = [['FCFS','FCFS'],['PROFIT','Profit-first'],['EXPIRY','Expiry-aware']] as const;
const groups: { name: string; rows: { label: string; key?: PortfolioDimension }[] }[] = [
 {name:'Financial',rows:[{label:'Estimated Revenue',key:'revenue'},{label:'Estimated Profit',key:'profit'},{label:'Profit Difference'}]},
 {name:'Operational',rows:[{label:'Selected Orders',key:'included'},{label:'Deferred Orders',key:'deferred'},{label:'Capacity Utilization',key:'capacity'},{label:'Remaining Capacity'}]},
 {name:'Inventory',rows:[{label:'Material Usage'},{label:'Expiry Exposure'},{label:'Potential Waste'}]},
 {name:'Delivery',rows:[{label:'Delivery Risk',key:'risk'},{label:'Deadline Conflicts'},{label:'Late Order Count'}]},
];
export function PortfolioComparisonMatrix({data, scenarios=[], now}: {data?:PortfolioSnapshot;scenarios?:PortfolioScenario[];now:number}) {
 return <ContentCard title="Strategy Comparison Matrix" className="pc-matrix">
  <p>Compare source values, not local rankings. Different currencies, objectives, models, policies or analysis scopes are not directly comparable. No profit difference is calculated here.</p>
  {!data || !scenarios.length ? <div className="pc-dependency"><strong>Comparison unavailable</strong><p>Verified strategy results, financial permission and matching analysis scope are required. Missing is not zero.</p></div> : <>
   <p className="pc-context-note">Analysis windows and resource scope are not supplied by the current presentation contract. Matching snapshot versions alone do not prove comparable analysis scope. Capacity values below have an unavailable resource/window basis.</p>
   <div className="pc-scroll" role="region" tabIndex={0} aria-label="Scenario comparison, scroll horizontally"><table>
    <caption>Scenario metrics and comparability</caption><thead><tr><th scope="col">Metric</th>{columns.map(([key,label])=><th scope="col" key={key}>{label}</th>)}</tr></thead>
    {groups.map(group=><tbody key={group.name}><tr className="pc-metric-group"><th colSpan={4} scope="colgroup">{group.name}</th></tr>{group.rows.map(row=><tr key={row.label}><th scope="row">{row.label}</th>{columns.map(([strategy])=>{
     const matches=scenarios.filter(s=>s.strategy===strategy); const scenario=matches[0];
     const value=matches.length>1?'Multiple scenarios · select one for comparison':!scenario?'Not provided':row.key?metricText(data,scenario,row.key,now):'Unavailable · field not supplied';
     return <td key={strategy}>{value}{row.key==='capacity' && scenario && <small>Resource / analysis window unavailable · not comparable</small>}{row.key && scenario && <small>Evidence: {scenario.metrics[row.key]?.evidence.join(', ')||'Unavailable'}</small>}</td>;
    })}</tr>)}</tbody>)}
   </table></div></>}
 </ContentCard>;
}
