import { useId, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Button, ContentCard, StatusBadge } from '../../shared/ui';
import type { OrderDetail } from './detailTypes';
import type { OrderDecisionSource } from './decisionTypes';
import { OrderDecisionWorkspace } from './OrderDecisionWorkspace';
import { OrderProgressPanel } from './OrderProgressPanel';
import { assessmentState, quantityText } from './detailView';
import { shown, timestamp } from './queue';
import { OrderQueueIcon } from './OrderQueueIcon';
import {
  OrderSummaryPanel,
  CustomerRequestPanel,
  InventoryAssessmentPanel,
  CapacityAssessmentPanel,
  FeasibilitySummary,
  PricingProvenancePanel,
  DecisionReadinessPanel,
} from './OrderDetailPanels';

const tabs = ['Overview', 'Feasibility', 'History'] as const;

export function OrderDetailWorkspace({
  id,
  detail: d,
  now,
  busy,
  onRefresh,
  state,
  legacy,
  decisionSource,
}: {
  id: string;
  detail?: OrderDetail | null;
  now: number;
  busy: boolean;
  onRefresh: () => void;
  state: ReactNode;
  legacy: ReactNode;
  decisionSource?: OrderDecisionSource;
}) {
  const uid = useId();
  const [tab, setTab] = useState<typeof tabs[number]>('Overview');
  const feasibility = d ? assessmentState(d, now) : 'UNKNOWN';

  const choose = (next: typeof tabs[number]) => {
    setTab(next);
    document.getElementById(`${uid}-${next}`)?.focus();
  };

  const orderValue =
    d?.pricing?.access === 'AUTHORIZED' && d.pricing.customerPrice && d.pricing.currency
      ? `${d.pricing.currency} ${d.pricing.customerPrice}`
      : '—';

  return (
    <div className="order-detail od-workspace">
      {/* Top navigation - Back button above the title */}
      <div className="od-top-bar">
        <Link to="/orders" className="od-back-link" aria-label="Back to Order Queue">
          <span aria-hidden="true" className="od-back-arrow">←</span> Back
        </Link>
      </div>

      {/* Simplified, elegant SaaS header */}
      <header className="od-header">
        <div className="od-title-group">
          <div className="od-title-row">
            <h1 id="od-page-title" aria-label="Order detail & feasibility">
              Order Detail &amp; Feasibility
            </h1>
            {id && <span className="od-order-pill">Order {id}</span>}
          </div>
        </div>
        <div className="od-header-actions">
          <Link to="/orders/portfolio" className="od-header-nav-link">
            Portfolio Comparison
          </Link>
          <Link to="/orders/calendar" className="od-header-nav-link">
            Calendar &amp; Scheduling
          </Link>
          <Button
            variant="secondary"
            className="od-refresh-btn"
            disabled={!id || busy}
            onClick={onRefresh}
            aria-label="Refresh order assessment view"
          >
            <OrderQueueIcon name="refresh" className={busy ? 'od-spinning' : ''} />
            <span>Refresh</span>
          </Button>
        </div>
      </header>

      {/* Clean 4 Summary Cards */}
      <section className="od-summary-cards" aria-label="Order key facts">
        <div className="od-summary-card od-card-value">
          <div className="od-card-header">
            <span className="od-card-label">Order Value</span>
            <span className="od-card-icon" aria-hidden="true">🏷️</span>
          </div>
          <div className="od-card-value-display">
            <strong className="od-card-val-primary">{orderValue}</strong>
          </div>
        </div>

        <div className="od-summary-card od-card-qty">
          <div className="od-card-header">
            <span className="od-card-label">Quantity</span>
            <span className="od-card-icon" aria-hidden="true">📦</span>
          </div>
          <div className="od-card-value-display">
            <strong className="od-card-val-primary">
              {d?.lines?.length === 1
                ? quantityText(d.lines[0].quantity)
                : d?.lines?.length
                  ? `${d.lines.length} separate lines`
                  : '—'}
            </strong>
          </div>
        </div>

        <div className="od-summary-card od-card-deadline">
          <div className="od-card-header">
            <span className="od-card-label">Deadline</span>
            <span className="od-card-icon" aria-hidden="true">📅</span>
          </div>
          <div className="od-card-value-display">
            <strong className="od-card-val-primary">
              {timestamp(d?.currentDeadline) || '—'}
            </strong>
          </div>
        </div>

        <div className="od-summary-card od-card-feasibility">
          <div className="od-card-header">
            <span className="od-card-label">Feasibility Status</span>
            <span className="od-card-icon" aria-hidden="true">⚡</span>
          </div>
          <div className="od-card-value-display">
            <StatusBadge dimension="feasibility" state={feasibility} />
          </div>
        </div>
      </section>

      {state}

      <div className="od-workspace-grid">
        <div className="od-main">
          {/* Tab Navigation */}
          <div
            className="od-tabs"
            role="tablist"
            aria-label="Order workspace sections"
            onKeyDown={event => {
              const current = tabs.indexOf(tab);
              const next =
                event.key === 'ArrowRight'
                  ? tabs[(current + 1) % tabs.length]
                  : event.key === 'ArrowLeft'
                    ? tabs[(current + tabs.length - 1) % tabs.length]
                    : event.key === 'Home'
                      ? tabs[0]
                      : event.key === 'End'
                        ? tabs[2]
                        : null;
              if (next) {
                event.preventDefault();
                choose(next);
              }
            }}
          >
            {tabs.map(value => (
              <button
                type="button"
                key={value}
                role="tab"
                id={`${uid}-${value}`}
                aria-selected={tab === value}
                aria-controls={`${uid}-panel-${value}`}
                tabIndex={tab === value ? 0 : -1}
                onClick={() => setTab(value)}
              >
                {value}
              </button>
            ))}
          </div>

          {/* Overview Tab Panel */}
          <div
            role="tabpanel"
            id={`${uid}-panel-Overview`}
            aria-labelledby={`${uid}-Overview`}
            hidden={tab !== 'Overview'}
            onClick={event => {
              if ((event.target as HTMLElement).closest('a[href="#legacy-order-context"]')) {
                setTab('History');
                requestAnimationFrame(() =>
                  document.getElementById('legacy-order-context')?.scrollIntoView?.()
                );
              }
            }}
          >
            {d && (
              <>
                <OrderSummaryPanel detail={d} />
                <CustomerRequestPanel detail={d} />
                <PricingProvenancePanel detail={d} />
                <OrderDecisionWorkspace order={d} now={now} source={decisionSource} view="decisions" />
              </>
            )}
            {!d && (
              <ContentCard title="Order overview unavailable">
                <p>
                  The order identifier alone does not establish customer terms, value, lifecycle or
                  feasibility. Read the existing source state in History.
                </p>
              </ContentCard>
            )}
          </div>

          {/* Feasibility Tab Panel */}
          <div
            role="tabpanel"
            id={`${uid}-panel-Feasibility`}
            aria-labelledby={`${uid}-Feasibility`}
            hidden={tab !== 'Feasibility'}
          >
            {d ? (
              <>
                <FeasibilitySummary detail={d} now={now} />
                <InventoryAssessmentPanel detail={d} />
                <CapacityAssessmentPanel detail={d} />
                <DecisionReadinessPanel detail={d} now={now} />
              </>
            ) : (
              <div className="od-panel od-empty-panel">
                <h3>Assessment Not Available</h3>
                <p>No verified feasibility assessment has been provided yet.</p>
              </div>
            )}
          </div>

          {/* History Tab Panel */}
          <div
            role="tabpanel"
            id={`${uid}-panel-History`}
            aria-labelledby={`${uid}-History`}
            hidden={tab !== 'History'}
          >
            {d ? (
              <OrderDecisionWorkspace order={d} now={now} source={decisionSource} view="history" />
            ) : (
              <OrderProgressPanel />
            )}
            {legacy}
          </div>
        </div>

        {/* Decision Sidebar */}
        <aside className="od-decision-sidebar" aria-label="Decision panel">
          <div className="od-decision-card">
            <div className="od-decision-header">
              <h2>Decision Overview</h2>
              <StatusBadge dimension="feasibility" state={feasibility} />
            </div>

            <div className="od-decision-section">
              <h3>Next Steps</h3>
              <p>
                {feasibility === 'UNKNOWN'
                  ? 'Verify the order evidence and obtain a current matching assessment before deciding.'
                  : 'Review the source assessment, exact customer terms and outstanding conditions. Feasibility is not permission to accept.'}
              </p>
            </div>

            <div className="od-decision-section">
              <h3>Source-provided recommendation</h3>
              <p>
                {feasibility === 'UNKNOWN'
                  ? 'Unavailable as decision guidance: assessment is not current and verified.'
                  : shown(d?.assessment?.recommendation)}
              </p>
            </div>

            <div className="od-decision-section">
              <h3>Verified constraints</h3>
              {d?.assessment?.sourceVerified &&
              feasibility !== 'UNKNOWN' &&
              d.assessment.constraints?.length ? (
                <ul className="od-bullet-list">
                  {d.assessment.constraints.map(value => (
                    <li key={value}>Source constraint: {value}</li>
                  ))}
                </ul>
              ) : (
                <p className="od-muted">Unavailable / not verified</p>
              )}
            </div>

            <div className="od-decision-section">
              <h3>Decision availability</h3>
              <ul className="od-bullet-list od-status-list">
                <li>Acceptance unavailable · verified order command required.</li>
                <li>Proposal submission unavailable · local unsent preparation remains in Overview.</li>
                <li>Agreement: Unavailable here · inspect source records.</li>
                <li>Reservation: Not verified · no free stock or capacity inferred.</li>
              </ul>
            </div>

            <div className="od-decision-actions">
              <Button variant="secondary" disabled aria-describedby={`${uid}-reassess`}>
                Reassess feasibility
              </Button>
              <p id={`${uid}-reassess`} className="od-field-hint">
                Unavailable: no authorized pending-order reassessment API is configured. Refresh
                reads existing records only.
              </p>
            </div>
          </div>
        </aside>
      </div>

      <p className="od-notice">
        Assessment is separate from acceptance and reservation. Existing P1 review and Core
        publishing remain available in History through their original workflow.
      </p>
    </div>
  );
}
