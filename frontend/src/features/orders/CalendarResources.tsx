import { EmptyState, UncertaintyNote } from '../../shared/ui';
import { scheduleTimeLabel, withinWindow } from './calendarDates';
import type { CalendarWindow, ScheduleSnapshot } from './calendarTypes';

export function CalendarResources({ data, window, resource }: { data: ScheduleSnapshot; window: CalendarWindow; resource: string }) {
  const resources = data.resources.filter(r => !resource || (r.detailAccess === 'FULL' && r.id === resource));
  return <section aria-label="Machine and resource occupancy"><h2>Machine & resource occupancy</h2>
    <UncertaintyNote kind="unknown">Unlisted periods and empty calendar cells mean availability Unknown. Free windows and utilization are shown only when explicitly evidenced by the source; no capacity is calculated from event gaps.</UncertaintyNote>
    {!resources.length && <EmptyState kind="unavailable" title="Resource schedule unavailable" description="No authorized resource calendar or capacity basis was supplied." />}
    {resources.map(r => <article className="cal-card" key={r.id}>
      {r.detailAccess === 'REDACTED' ? <h3>Redacted resource schedule</h3> : <>
        <h3>{r.label}</h3><p>Resource {r.id} · version {r.version} · coverage {r.coverage}</p>
        {r.utilization && r.utilization.evidence.length && r.coverage === 'VALIDATED_COMPLETE' && withinWindow({ kind: 'INTERVAL', start: r.utilization.start, end: r.utilization.end }, window) ?
          <p>Source-reported utilization: {r.utilization.percentage}% · {r.utilization.numerator} / {r.utilization.denominator} {r.utilization.unit}
            {' · '}{r.utilization.basis}<br />{scheduleTimeLabel({ kind: 'INTERVAL', start: r.utilization.start, end: r.utilization.end }, window.timeZone)}
            <br />Evidence: {r.utilization.evidence.join(', ')}</p> : <p>Utilization: Unknown · no complete evidenced capacity basis for this window</p>}
        <ul className="cal-windows">{r.windows.filter(w => withinWindow({ kind: 'INTERVAL', start: w.start, end: w.end }, window)).map(w => <li key={w.id}>
          <strong>{w.evidence.length && (w.state !== 'FREE' || r.coverage === 'VALIDATED_COMPLETE') ? w.state : 'UNKNOWN'}</strong>
          <span>{scheduleTimeLabel({ kind: 'INTERVAL', start: w.start, end: w.end }, window.timeZone)}</span>
          <small>Source window {w.id} · Evidence: {w.evidence.join(', ') || 'Unavailable'}</small>
        </li>)}</ul>
        {!r.windows.some(w => withinWindow({ kind: 'INTERVAL', start: w.start, end: w.end }, window)) && <p>No loaded occupancy windows · availability Unknown</p>}
      </>}
    </article>)}
  </section>;
}
