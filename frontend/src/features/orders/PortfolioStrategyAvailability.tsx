import { OrderQueueIcon } from './OrderQueueIcon';
import { metricText, verifiedRecommendation } from './portfolioView';
import type { PortfolioSnapshot } from './portfolioTypes';

const strategies = [['FCFS', 'FCFS'], ['PROFIT', 'Profit'], ['EXPIRY', 'Expiry-aware']] as const;

/** Presence in a current authorized response is not feasibility or execution permission. */
export function PortfolioStrategyAvailability({ data, selectedId, onSelect, now = Date.now() }: { data?: PortfolioSnapshot; selectedId?: string; onSelect?: (id: string) => void; now?: number }) {
  return <section aria-label="Strategy availability"><h2>Strategy availability</h2>
    <p>Returned scenarios may still contain unknown or redacted metrics. Strategy presence does not establish feasibility or authorize execution.</p>
    <div className="pc-cards">{strategies.map(([strategy, label]) => {
      const returned = data?.scenarios.filter(s => s.strategy === strategy);
      const active = returned?.find(s => s.id === selectedId) ?? returned?.[0];
      const descriptions = { FCFS: 'Prioritize eligible orders by verified received time.', PROFIT: 'Compare eligible portfolios using authorized estimated profit.', EXPIRY: 'Consider verified material expiry exposure and waste constraints.' };
      const recommended = data && verifiedRecommendation(data, now);
      return <article className={`pc-card pc-strategy-card ${!!active && active.id === selectedId ? 'pc-strategy-selected' : ''}`} key={strategy} aria-label={`Availability: ${label}`}><span className="pc-strategy-icon"><OrderQueueIcon name={strategy === 'FCFS' ? 'pending' : strategy === 'PROFIT' ? 'orders' : 'risk'} /></span><p className="pc-eyebrow">{strategy === 'FCFS' ? 'First Come, First Served' : 'Advisory strategy'}</p><h3>{strategy === 'PROFIT' ? 'Profit-first' : label}</h3>
        <p>{descriptions[strategy]}</p>
        {recommended && active?.id === recommended.scenarioId && <span className="pc-recommended">Recommended · source-backed</span>}
        <dl className="pc-strategy-metrics">{([['profit','Estimated Profit'],['included','Selected Order Count'],['capacity','Capacity Utilization']] as const).map(([key,name]) => <div key={key}><dt>{name}</dt><dd>{data && active ? metricText(data,active,key,now) : 'Unavailable'}{key === 'capacity' && <small>Resource / analysis window unavailable</small>}</dd></div>)}
          <div><dt>Waste / Expiry Risk</dt><dd>Unavailable · no metric contract</dd></div><div><dt>Solver Status</dt><dd>{active?.solverStatus ?? 'Not evaluated'}</dd></div></dl>
        {!!active && active.id === selectedId && <span className="pc-selected-label">Selected strategy</span>}
        <button type="button" className="foundation-button foundation-button-secondary" aria-pressed={!!active && active.id === selectedId} disabled={!active || !onSelect} onClick={() => active && onSelect?.(active.id)}>Select {label} strategy</button>
        {!returned ? <p>Not verified · no current authorized snapshot is available.</p> : returned.length ? <>
          <p>Returned by source · {returned.length} scenario{returned.length === 1 ? '' : 's'}.</p>
          {returned.some(s => s.validation !== 'VALIDATED') && <p>Validation is incomplete or mismatched for one or more returned scenarios. Positive metrics remain withheld for those scenarios.</p>}
          {strategy === 'PROFIT' && <p>{data?.financialAccess === 'REDACTED' ? 'Financial values are redacted by source authorization.' :
            data?.financialAccess !== 'AUTHORIZED' ? 'Financial authorization is unknown; profit values are unavailable.' :
              returned.some(s => s.metrics.profit?.state === 'REDACTED') ? 'One or more profit metrics are redacted; returned does not mean usable profit.' :
                'Profit values require complete authorized price/cost evidence; missing or incomplete values remain Unknown.'}</p>}
        </> : <p>Not provided in this snapshot. The source supplied no reason; this does not establish that the strategy is unsupported.</p>}
      </article>;
    })}</div>
    {data?.coverage === 'PARTIAL' && <p>This response has partial coverage: strategies absent here may exist outside the loaded snapshot.</p>}
  </section>;
}
