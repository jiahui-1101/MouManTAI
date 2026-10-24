import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ApiError } from '../../shared/api';
import { useAuth } from '../../shared/auth';
import {
  EmptyState,
  ErrorState,
  EvidenceTierBadge,
  LastUpdated,
  StatusBadge,
  UncertaintyNote,
  VersionConflictBanner,
} from '../../shared/ui';
import { instant, timestamp } from './queue';
import { OrderQueueIcon } from './OrderQueueIcon';
import { portfolioDimensions, type PortfolioSnapshot, type PortfolioSource } from './portfolioTypes';
import {
  PortfolioUnavailableError,
  PortfolioVersionError,
  portfolioFresh,
  unavailablePortfolioSource,
  validatePortfolio,
} from './portfolioSource';
import { metricText, verifiedRecommendation } from './portfolioView';
import { PortfolioStrategyAvailability } from './PortfolioStrategyAvailability';
import { PortfolioCalendarContext } from './portfolioCalendarContext';
import { PortfolioAnalysisScope } from './PortfolioAnalysisScope';
import { PortfolioComparisonMatrix } from './PortfolioComparisonMatrix';
import { PortfolioAllocationPanel, supportedAllocation } from './PortfolioAllocationPanel';
import { PortfolioSolverExplanation } from './PortfolioSolverExplanation';
import './portfolio.css';

const executionNotice =
  'Scenario membership is a proposal only. Comparison does not accept orders, establish customer assent, reserve resources or change confirmed agreements.';

function PortfolioResults({ data, now }: { data: PortfolioSnapshot; now: number }) {
  const [activeId, setActiveId] = useState(() => data.scenarios[0]?.id ?? '');
  const active = data.scenarios.find(s => s.id === activeId);
  const [selected, setSelected] = useState(() => data.scenarios.map(s => s.id));
  const scenarios = data.scenarios.filter(s => selected.includes(s.id));
  const recommendation = verifiedRecommendation(data, now);

  return (
    <>
      <PortfolioStrategyAvailability
        data={data}
        now={now}
        selectedId={activeId}
        onSelect={setActiveId}
      />

      <section className="pc-active-scenario" aria-label="Selected strategy detail">
        <label>
          Selected scenario
          <select value={activeId} onChange={e => setActiveId(e.target.value)}>
            {data.scenarios.map(s => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <h2>Selected Strategy: {active?.label}</h2>
        <p>
          Scenario {active?.id} · version {active?.version} · {active?.solverStatus}
        </p>
        <p>Selection changes this display only. Comparison checkboxes below remain independent.</p>
      </section>

      {data.coverage === 'PARTIAL' && (
        <UncertaintyNote kind="insufficient-evidence">
          Partial source coverage. Missing metrics remain Unknown; no whole-portfolio
          recommendation is available.
        </UncertaintyNote>
      )}

      <fieldset className="pc-selection">
        <legend>Scenarios to compare</legend>
        {data.scenarios.map(s => (
          <label key={s.id}>
            <input
              type="checkbox"
              checked={selected.includes(s.id)}
              onChange={() =>
                setSelected(ids =>
                  ids.includes(s.id) ? ids.filter(id => id !== s.id) : [...ids, s.id]
                )
              }
            />
            {s.label}
            <span>
              {s.strategy} · version {s.version}
            </span>
          </label>
        ))}
      </fieldset>

      <p className="pc-note">
        FCFS describes source-supplied ordering. A strategy name or a higher score does not confer
        scheduling or execution authority.
      </p>

      {!scenarios.length && (
        <EmptyState
          kind="no-results"
          title="Select a scenario"
          description="Selection changes this display only; nothing is saved or submitted."
        />
      )}

      <div className="pc-cards">
        {scenarios.map(s => (
          <article key={s.id} aria-label={`Summary: ${s.label}`} className="pc-card">
            <h2>{s.label}</h2>
            <p>
              {s.strategy} · {s.id} · version {s.version}
            </p>
            <StatusBadge
              state={s.validation === 'VALIDATED' ? 'UNKNOWN' : s.validation}
              label={`Validation: ${s.validation}`}
            />
            <p>Evaluation: {s.solverStatus}</p>
            <p>
              Objective: {s.objectiveId} · model {s.modelVersion}
            </p>
            <p>Constraint policy: {s.constraintPolicy}</p>
            {s.validation !== 'VALIDATED' && (
              <UncertaintyNote kind="insufficient-evidence">
                Scenario validation is incomplete or mismatched. Positive metric claims are
                withheld; use the order detail for individual review.
              </UncertaintyNote>
            )}
            <dl>
              {portfolioDimensions.map(([key, label]) => (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd>{metricText(data, s, key, now)}</dd>
                </div>
              ))}
            </dl>
            <p>
              Resource units / analysis window for capacity: Unavailable · no comparable scope
              supplied.
            </p>
            <p>Evidence: {s.evidence.join(', ')}</p>
          </article>
        ))}
      </div>

      <PortfolioComparisonMatrix data={data} scenarios={scenarios} now={now} />
      <PortfolioAllocationPanel data={data} scenario={active} now={now} />

      {!!scenarios.length && (
        <>
          <h2>Order allocation breakdown</h2>
          <p className="pc-section-subtitle">{executionNotice}</p>
          {!data.orders.length ? (
            <EmptyState
              kind="unavailable"
              title="Order breakdown unavailable"
              description="No source-provided order identities and request versions."
            />
          ) : (
            <div
              className="pc-scroll"
              tabIndex={0}
              role="region"
              aria-label="Order allocations, scroll horizontally"
            >
              <table>
                <caption>Proposed scenario membership, not order lifecycle status</caption>
                <thead>
                  <tr>
                    <th scope="col">Requested order</th>
                    {scenarios.map(s => (
                      <th scope="col" key={s.id}>
                        {s.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.orders.map(o => (
                    <tr key={o.id}>
                      <th scope="row">
                        <Link to={`/orders/${encodeURIComponent(o.id)}`}>{o.id}</Link>
                        <small>Request version: {o.requestVersion}</small>
                        <small>Customer / reference: {o.customerReference || 'Unknown'}</small>
                        <small>Requested delivery: {timestamp(o.deadline)}</small>
                        <small>Evidence: {o.evidence.join(', ') || 'Unavailable'}</small>
                      </th>
                      {scenarios.map(s => {
                        const a = s.allocations.find(a => a.orderId === o.id);
                        const supported = supportedAllocation(s, a);
                        return (
                          <td key={s.id}>
                            <strong>{supported ? a!.membership : 'UNKNOWN'}</strong>
                            <small>
                              {supported
                                ? a!.reason || 'Reason unavailable'
                                : 'Allocation evidence unavailable'}
                            </small>
                            <small>
                              Resource requirements:{' '}
                              {supported ? a!.resources || 'Unknown' : 'Unknown'}
                            </small>
                            <small>
                              Conflicts: {supported ? a!.conflict || 'Unknown' : 'Unknown'}
                            </small>
                            <small>Evidence: {a?.evidence.join(', ') || 'Unavailable'}</small>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2>Constraints and trade-offs</h2>
          {scenarios.map(s => (
            <section key={s.id} className="pc-card" aria-label={`Constraints: ${s.label}`}>
              <h3>{s.label}</h3>
              {!s.constraints.length ? (
                <p>
                  Constraint findings unavailable; an empty list does not prove unconstrained
                  capacity.
                </p>
              ) : (
                s.constraints.map(c => (
                  <article key={c.id} className="pc-constraint-card">
                    <h4>{c.description}</h4>
                    <p>
                      Severity: {c.severity || 'Unknown'} · Status: {c.status}
                    </p>
                    <p>
                      Orders: {c.orderIds.join(', ') || 'Unknown'} · Resources:{' '}
                      {c.resources.join(', ') || 'Unknown'}
                    </p>
                    <p>
                      Source: {c.source} · Evidence: {c.evidence.join(', ')}
                    </p>
                    {c.uncertainty && <p className="pc-constraint-note">{c.uncertainty}</p>}
                  </article>
                ))
              )}
            </section>
          ))}
        </>
      )}

      <PortfolioSolverExplanation data={data} scenario={active} now={now} />

      <section className="pc-card" aria-label="Recommendation explanation">
        <h2>Recommendation explanation</h2>
        {recommendation ? (
          <>
            <h3>Backend recommendation: {recommendation.label}</h3>
            <p>{recommendation.reason}</p>
            <p>
              Source: {recommendation.source} · Evidence: {recommendation.evidence.join(', ')}
            </p>
            <p>
              Objective: {recommendation.objectiveId} · Model: {recommendation.modelVersion} ·
              Policy: {recommendation.constraintPolicy}
            </p>
            <p>
              Snapshot: {recommendation.snapshotId} v{recommendation.snapshotVersion} · Scenario
              version: {recommendation.scenarioVersion}
            </p>
            <LastUpdated label="Recommendation issued" value={recommendation.issuedAt} />
            <LastUpdated label="Recommendation expires" value={recommendation.expiresAt} />
            <p>
              Limitations:{' '}
              {recommendation.limitations.join('; ') ||
                'No limitations statement supplied; review before any separate decision.'}
            </p>
          </>
        ) : (
          <UncertaintyNote kind="unknown">
            An authoritative portfolio recommendation is not currently available. Scenario
            comparison does not authorize order acceptance or resource reservation.
          </UncertaintyNote>
        )}
      </section>
    </>
  );
}

/** Route-ready page; requires existing AuthProvider, QueryClientProvider and Router. */
export function PortfolioComparisonPage({
  source = unavailablePortfolioSource,
}: { source?: PortfolioSource } = {}) {
  const { authHeaders: auth } = useAuth();
  const [now, setNow] = useState(Date.now);
  const query = useQuery({
    queryKey: ['orders', 'portfolio', source.cacheKey, auth.tenantId, auth.actorId],
    queryFn: async ({ signal }) => validatePortfolio(await source.load(auth, signal), auth),
    retry: false,
    gcTime: 0,
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  });

  const data = !query.isFetching && !query.isError ? query.data : undefined;

  useEffect(() => {
    if (!data) return;
    let timer: number | undefined;
    const scheduleExpiry = () => {
      const clock = Date.now();
      const expiry = Math.min(
        ...[instant(data.expiresAt), instant(data.recommendation?.expiresAt)].filter(
          (at): at is number => at !== null && at > clock
        )
      );
      if (!Number.isFinite(expiry)) return;
      timer = window.setTimeout(
        () => {
          setNow(Date.now());
          scheduleExpiry();
        },
        Math.min(expiry - clock + 1, 2_147_483_647)
      );
    };
    scheduleExpiry();
    return () => window.clearTimeout(timer);
  }, [data]);

  const refresh = () => {
    setNow(Date.now());
    void query.refetch();
  };

  const conflict =
    query.error instanceof PortfolioVersionError ||
    (query.error instanceof ApiError && query.error.status === 409) ||
    (data && data.snapshotVersion !== data.currentVersion);
  const observedNow = Math.max(now, Date.now());
  const available = data && portfolioFresh(data, observedNow);

  return (
    <section className="portfolio-comparison pc-workspace" aria-labelledby="pc-title">
      {/* Top navigation - Back button above the title */}
      <div className="pc-top-bar">
        <Link to="/orders" className="pc-back-link" aria-label="Back to Order Decision Queue">
          <span aria-hidden="true" className="pc-back-arrow">←</span> Back
        </Link>
      </div>

      {/* Clean modern SaaS header */}
      <header className="pc-header">
        <div className="pc-title-row">
          <h1 id="pc-title">Portfolio Comparison</h1>
        </div>
        <div className="pc-header-actions">
          <button
            className="btn btn-secondary pc-refresh-btn"
            type="button"
            disabled={query.isFetching}
            onClick={refresh}
            aria-label="Refresh portfolio"
          >
            <OrderQueueIcon name="refresh" className={query.isFetching ? 'pc-spinning' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </header>

      {/* Accessible planning shortcut */}
      <Link to="/orders/calendar" className="sr-only">
        Production &amp; Delivery Calendar
      </Link>

      <PortfolioCalendarContext />

      <div className="pc-source">
        <StatusBadge
          state="UNKNOWN"
          label={data ? 'Source response received · read only' : 'Backend data unavailable'}
        />
        <EvidenceTierBadge
          evidenceTier={data?.evidenceTier ?? 'TARGET'}
          {...(data ? { integrationMode: data.integrationMode } : {})}
        />
        <LastUpdated value={data?.updatedAt} />
        {data && (
          <>
            <p>Source: {data.source}</p>
            <p>
              Snapshot: {data.snapshotId} · version {data.snapshotVersion}
            </p>
            <p>Evidence: {data.evidence.join(', ') || 'Unavailable'}</p>
            <LastUpdated label="Snapshot expires" value={data.expiresAt} />
          </>
        )}
      </div>

      {query.isFetching && (
        <p role="status">Loading portfolio comparison… Previous sensitive results are hidden.</p>
      )}

      {!query.isFetching && conflict && (
        <VersionConflictBanner
          onRefresh={refresh}
          currentVersion={data?.currentVersion}
          expectedVersion={data?.snapshotVersion}
          message="Scenario, request or snapshot versions conflict. Comparison and recommendation are withheld."
        />
      )}

      {!query.isFetching &&
        query.error &&
        !conflict &&
        (query.error instanceof PortfolioUnavailableError ? (
          <EmptyState
            kind="unavailable"
            title="Portfolio API unavailable"
            description="No verified portfolio read endpoint is available. FCFS, profit and expiry-aware scenarios require Backend-owned assessment, resource snapshots and authorized financial evidence. No scenario has been generated."
          />
        ) : (
          <ErrorState error={query.error} retrySafe onRetry={refresh} />
        ))}

      {data && !conflict && !available && (
        <EmptyState
          kind="unavailable"
          title="Current verified snapshot unavailable"
          description="Source evidence is unverified, stale, expired, future-dated or of unknown freshness. Metrics, allocations and recommendations are withheld. Refresh or review individual orders."
        />
      )}

      <PortfolioAnalysisScope data={available && !conflict ? data : undefined} />
      {(!available || conflict || !data.scenarios.length) && (
        <PortfolioStrategyAvailability data={available && !conflict ? data : undefined} />
      )}
      {(!available || conflict || !data.scenarios.length) && (
        <PortfolioComparisonMatrix now={observedNow} />
      )}
      {(!available || conflict || !data.scenarios.length) && (
        <PortfolioAllocationPanel now={observedNow} />
      )}
      {(!available || conflict || !data.scenarios.length) && (
        <PortfolioSolverExplanation now={observedNow} />
      )}

      {available &&
        !conflict &&
        (data.scenarios.length ? (
          <PortfolioResults
            key={`${auth.tenantId}:${auth.actorId}:${data.snapshotId}:${data.snapshotVersion}:${data.updatedAt}:${data.scenarios.map(s => `${s.id}:${s.version}`).join('|')}`}
            data={data}
            now={observedNow}
          />
        ) : (
          <EmptyState
            kind="empty"
            title="No source scenarios"
            description="The source returned no scenarios. Continue with individual order assessments; no local portfolio is invented."
          />
        ))}
    </section>
  );
}
