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
import { OrderSummaryPanel, CustomerRequestPanel, InventoryAssessmentPanel, CapacityAssessmentPanel,
  FeasibilitySummary, PricingProvenancePanel, DecisionReadinessPanel } from './OrderDetailPanels';

const tabs = ['Overview', 'Feasibility', 'History'] as const;
export function OrderDetailWorkspace({ id, detail: d, now, busy, onRefresh, state, legacy, decisionSource }: {
  id: string; detail?: OrderDetail | null; now: number; busy: boolean; onRefresh: () => void;
  state: ReactNode; legacy: ReactNode; decisionSource?: OrderDecisionSource;
}) {
  const uid = useId();
  const [tab, setTab] = useState<typeof tabs[number]>('Overview');
  const feasibility = d ? assessmentState(d, now) : 'UNKNOWN';
  const choose = (next: typeof tabs[number]) => { setTab(next); document.getElementById(`${uid}-${next}`)?.focus(); };
  return <div className="order-detail">
    <nav aria-label="Order breadcrumb" className="od-breadcrumb"><Link to="/orders">Orders</Link><span aria-hidden="true">/</span><span aria-current="page">{id || 'Unavailable'}</span></nav>
    <header className="od-heading"><div><p className="od-eyebrow">Order review &amp; decision workspace</p><h1>Order detail &amp; feasibility</h1>
      <p className="od-current-order">Order <strong>{id || 'Not available'}</strong></p>
      <p>Customer: {shown(d?.customer)} · Products: {d?.lines?.map(line => line.product || line.sku).filter(Boolean).join(', ') || 'Unavailable'}</p>
      <p>Created date: Unavailable · Priority: Unavailable · Lifecycle: {d?.status?.trim() || 'UNKNOWN'}</p>
    </div><Button variant="secondary" disabled={!id || busy} onClick={onRefresh}><OrderQueueIcon name="refresh" />Refresh order assessment view</Button></header>
    <nav aria-label="Order detail navigation" className="od-navigation"><Link to="/orders">Back to Order Queue</Link><Link to="/orders/portfolio">Portfolio Comparison</Link><Link to="/orders/calendar">Calendar &amp; Scheduling</Link></nav>
    <section className="od-summary-cards" aria-label="Order key facts">
      <ContentCard><span>Order Value</span><strong>Unavailable</strong><small>No authoritative order total supplied</small></ContentCard>
      <ContentCard><span>Quantity</span><strong>{d?.lines?.length === 1 ? quantityText(d.lines[0].quantity) : d?.lines?.length ? `${d.lines.length} separate lines` : 'Unavailable'}</strong><small>Source units preserved · no cross-unit total</small></ContentCard>
      <ContentCard><span>Deadline</span><strong>{timestamp(d?.currentDeadline)}</strong><small>Current captured deadline · MYT</small></ContentCard>
      <ContentCard><span>Feasibility Status</span><StatusBadge dimension="feasibility" state={feasibility} /><small>Assessment only · no acceptance or reservation</small></ContentCard>
    </section>
    {state}
    <div className="od-workspace-grid"><div className="od-main">
      <div className="od-tabs" role="tablist" aria-label="Order workspace sections" onKeyDown={event => {
        const current = tabs.indexOf(tab);
        const next = event.key === 'ArrowRight' ? tabs[(current + 1) % tabs.length] : event.key === 'ArrowLeft' ? tabs[(current + tabs.length - 1) % tabs.length] : event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[2] : null;
        if (next) { event.preventDefault(); choose(next); }
      }}>{tabs.map(value => <button type="button" key={value} role="tab" id={`${uid}-${value}`} aria-selected={tab === value} aria-controls={`${uid}-panel-${value}`} tabIndex={tab === value ? 0 : -1} onClick={() => setTab(value)}>{value}</button>)}</div>
      <div role="tabpanel" id={`${uid}-panel-Overview`} aria-labelledby={`${uid}-Overview`} hidden={tab !== 'Overview'} onClick={event => {
        if ((event.target as HTMLElement).closest('a[href="#legacy-order-context"]')) {
          setTab('History'); requestAnimationFrame(() => document.getElementById('legacy-order-context')?.scrollIntoView?.());
        }
      }}>{d && <><OrderSummaryPanel detail={d} /><CustomerRequestPanel detail={d} /><PricingProvenancePanel detail={d} />
        <OrderDecisionWorkspace order={d} now={now} source={decisionSource} view="decisions" /></>}
        {!d && <ContentCard title="Order overview unavailable"><p>The order identifier alone does not establish customer terms, value, lifecycle or feasibility. Read the existing source state in History.</p></ContentCard>}
      </div>
      <div role="tabpanel" id={`${uid}-panel-Feasibility`} aria-labelledby={`${uid}-Feasibility`} hidden={tab !== 'Feasibility'}>{d ? <><FeasibilitySummary detail={d} now={now} /><InventoryAssessmentPanel detail={d} /><CapacityAssessmentPanel detail={d} /><DecisionReadinessPanel detail={d} now={now} /></> : <ContentCard title="Feasibility unavailable"><p>No verified order detail or matching assessment is available. No material, capacity or scheduling result has been calculated locally.</p></ContentCard>}</div>
      <div role="tabpanel" id={`${uid}-panel-History`} aria-labelledby={`${uid}-History`} hidden={tab !== 'History'}>{d ? <OrderDecisionWorkspace order={d} now={now} source={decisionSource} view="history" /> : <OrderProgressPanel />}{legacy}</div>
    </div>
    <aside className="od-decision-sidebar" aria-label="Decision panel"><ContentCard title="Decision overview"><StatusBadge dimension="feasibility" state={feasibility} />
      <h3>What should we do next?</h3><p>{feasibility === 'UNKNOWN' ? 'Verify the order evidence and obtain a current matching assessment before deciding.' : 'Review the source assessment, exact customer terms and outstanding conditions. Feasibility is not permission to accept.'}</p>
      <h3>Source-provided recommendation</h3><p>{feasibility === 'UNKNOWN' ? 'Unavailable as decision guidance: assessment is not current and verified.' : shown(d?.assessment?.recommendation)}</p>
      <h3>Verified constraints</h3>{d?.assessment?.sourceVerified && feasibility !== 'UNKNOWN' && d.assessment.constraints?.length ? <ul>{d.assessment.constraints.map(value => <li key={value}>Source constraint: {value}</li>)}</ul> : <p>Unavailable / not verified</p>}
      <h3>Decision availability</h3><p>Acceptance unavailable · verified order command required.</p><p>Proposal submission unavailable · local unsent preparation remains in Overview.</p><p>Agreement: Unavailable here · inspect source records.</p><p>Reservation: Not verified · no free stock or capacity inferred.</p>
      <Button variant="secondary" disabled aria-describedby={`${uid}-reassess`}>Reassess feasibility</Button><p id={`${uid}-reassess`}>Unavailable: no authorized pending-order reassessment API is configured. Refresh reads existing records only.</p>
    </ContentCard></aside></div>
    <p className="od-notice">Assessment is separate from acceptance and reservation. Existing P1 review and Core publishing remain available in History through their original workflow.</p>
  </div>;
}
