import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { StatusBadge, UncertaintyNote } from '../../shared/ui';
import { authorityLabel, eventLabel } from './calendarView';
import { scheduleTimeLabel } from './calendarDates';
import type { ScheduleEvent, ScheduleSnapshot } from './calendarTypes';

/** Nonmodal detail region: no dialog confirmation or command handler is appropriate for a read-only inspector. */
export function CalendarEventPanel({ event, snapshot, onClose, returnFocus }: {
  event: ScheduleEvent; snapshot: ScheduleSnapshot; onClose: () => void; returnFocus: HTMLElement | null;
}) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => { close.current?.focus(); return () => { if (returnFocus?.isConnected) returnFocus.focus(); }; }, [returnFocus]);
  const redacted = event.detailAccess === 'REDACTED';
  return <section className="cal-detail" role="region" aria-label="Calendar event details" onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } }}>
    <div className="cal-heading"><h2>{eventLabel(event)}</h2><button ref={close} type="button" onClick={onClose}>Close event details</button></div>
    <StatusBadge state="UNKNOWN" label={authorityLabel(event)} />
    <p>{event.type} · {scheduleTimeLabel(event.when, snapshot.window.timeZone)}</p>
    {redacted ? <UncertaintyNote kind="unknown">Event details are Redacted. No hidden order, resource, status or evidence fields are exposed.</UncertaintyNote> : <>
      <dl><dt>Event / job ID</dt><dd>{event.id}</dd><dt>Order request</dt><dd><Link to={`/orders/${encodeURIComponent(event.order.id)}`}>{event.order.id}</Link> · request version {event.order.requestVersion}</dd>
        <dt>Schedule identity</dt><dd>{event.scheduleId} · version {event.scheduleVersion}</dd>
        <dt>Source status</dt><dd>{event.status}</dd><dt>Production stage</dt><dd>{event.stage || 'Unknown'}</dd>
        <dt>Quantity</dt><dd>{event.quantity ? `${event.quantity.amount} ${event.quantity.unit}` : 'Unknown'}</dd>
        <dt>Delivery date meaning</dt><dd>{event.deliveryMilestone || 'Not a delivery event'}</dd>
        <dt>Resources</dt><dd>{event.resources.map(ref => { const r = snapshot.resources.find(r => r.id === ref.id)!;
          return r.detailAccess === 'REDACTED' ? 'Redacted resource' : `${r.label} (${r.id}, v${r.version})`; }).join('; ') || 'Unknown'}</dd>
        <dt>Material readiness</dt><dd>{event.materialReadiness || 'Unknown'}</dd>
        <dt>Dependencies</dt><dd>{event.dependencies.map(id => { const related = snapshot.events.find(e => e.id === id)!;
          return related.detailAccess === 'REDACTED' ? 'Redacted event' : `${related.title} (${id})`; }).join('; ') || 'Not supplied'}</dd>
        <dt>Source</dt><dd>{event.source}</dd><dt>Evidence</dt><dd>{event.evidence.join(', ')}</dd>
        <dt>Authority evidence</dt><dd>{event.authority.evidence.join(', ') || 'Unavailable'}</dd>
        <dt>Audit/history references</dt><dd>{event.historyRefs.join(', ') || 'Unavailable'}</dd></dl>
      <h3>Related source conflicts</h3>
      {(snapshot.conflicts ?? []).filter(c => c.eventIds.includes(event.id)).map(c => <p key={c.id}>
        {c.detailAccess === 'REDACTED' ? 'Redacted conflict' : `${c.id}: ${c.explanation} · severity ${c.severity || 'Unknown'} · ${c.source} v${c.sourceVersion} · evidence ${c.evidence.join(', ')}`}</p>)}
      {!snapshot.conflicts?.some(c => c.eventIds.includes(event.id)) && <p>No loaded conflict finding; this does not prove a conflict-free schedule.</p>}
    </>}
    <UncertaintyNote kind="conditional">Rescheduling submission and impact preview are unavailable. No validated schedule mutation contract is connected. This inspector cannot move work, reserve resources or change delivery agreements.</UncertaintyNote>
  </section>;
}
