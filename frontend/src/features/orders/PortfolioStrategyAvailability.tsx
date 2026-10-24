import type { PortfolioSnapshot } from './portfolioTypes';

const strategies = [['FCFS', 'FCFS'], ['PROFIT', 'Profit'], ['EXPIRY', 'Expiry-aware']] as const;

/** Presence in a current authorized response is not feasibility or execution permission. */
export function PortfolioStrategyAvailability({ data }: { data?: PortfolioSnapshot }) {
  return <section aria-label="Strategy availability"><h2>Strategy availability</h2>
    <p>Returned scenarios may still contain unknown or redacted metrics. Strategy presence does not establish feasibility or authorize execution.</p>
    <div className="pc-cards">{strategies.map(([strategy, label]) => {
      const returned = data?.scenarios.filter(s => s.strategy === strategy);
      return <article className="pc-card" key={strategy} aria-label={`Availability: ${label}`}><h3>{label}</h3>
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
