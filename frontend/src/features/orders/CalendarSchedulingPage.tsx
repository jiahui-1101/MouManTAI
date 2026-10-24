import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ApiError } from '../../shared/api';
import { useAuth } from '../../shared/auth';
import { EmptyState, ErrorState, EvidenceTierBadge, LastUpdated, StatusBadge, UncertaintyNote, VersionConflictBanner } from '../../shared/ui';
import { addDays, addMonths, calendarWindow, civilLabel, daysInWindow, localDateAt, parseScheduleInstant, scheduleTimeLabel, validDate, validZone, withinWindow } from './calendarDates';
import { ScheduleUnavailableError, ScheduleVersionError, scheduleFresh, unavailableScheduleSource, validateSchedule } from './calendarSource';
import { authorityLabel, eventLabel, eventsForDay, filterSchedule, initialCalendarFilters } from './calendarView';
import type { CalendarFilters, CalendarView, ScheduleSnapshot, ScheduleSource } from './calendarTypes';
import { CalendarEventPanel } from './CalendarEventPanel';
import { CalendarResources } from './CalendarResources';
import './calendar.css';

interface CalendarPageProps { source?: ScheduleSource; timeZone?: string; initialDate?: string }
function CalendarWorkspace({ source, timeZone, initialDate }: Required<Pick<CalendarPageProps, 'source' | 'timeZone'>> & Pick<CalendarPageProps, 'initialDate'>) {
  const { authHeaders: auth } = useAuth();
  const [date, setDate] = useState(initialDate && validDate(initialDate) ? initialDate : localDateAt(Date.now(), timeZone));
  const [view, setView] = useState<CalendarView>('MONTH');
  const [weekStartsOn, setWeekStartsOn] = useState<0 | 1>(1);
  const [now, setNow] = useState(Date.now);
  const window = calendarWindow(date, view, timeZone, weekStartsOn);
  const query = useQuery({ queryKey: ['orders', 'schedule', source.cacheKey, auth.tenantId, auth.actorId, window],
    queryFn: async ({ signal }) => validateSchedule(await source.load(window!, auth, signal), window!, auth),
    enabled: !!window, retry: false, gcTime: 0, staleTime: 0, refetchOnMount: 'always', refetchOnWindowFocus: true });
  const data = !query.isFetching && !query.isError ? query.data : undefined;
  useEffect(() => {
    if (!data) return;
    let timer: ReturnType<typeof globalThis.setTimeout> | undefined;
    const tick = () => {
      const remaining = parseScheduleInstant(data.expiresAt)! - Date.now();
      if (remaining <= 0) { setNow(Date.now()); return; }
      timer = globalThis.setTimeout(tick, Math.min(remaining + 1, 2_147_483_647));
    };
    tick();
    return () => globalThis.clearTimeout(timer);
  }, [data]);
  const refresh = () => { setNow(Date.now()); void query.refetch(); };
  const fresh = data && scheduleFresh(data, Math.max(now, Date.now()));
  const conflict = query.error instanceof ScheduleVersionError || (query.error instanceof ApiError && query.error.status === 409) || (data && data.snapshotVersion !== data.currentVersion);
  const move = (delta: number) => view === 'MONTH' ? addMonths(date, delta) : addDays(date, delta * (view === 'WEEK' ? 7 : 1));
  const changeDate = (next: string) => { if (validDate(next) && calendarWindow(next, view, timeZone, weekStartsOn)) setDate(next); };
  return <section className="schedule-calendar" aria-labelledby="cal-title">
    <header className="cal-heading"><div><p className="cal-eyebrow">Orders & planning · read only</p><h1 id="cal-title">Production & Delivery Calendar</h1>
      <p>Inspect sourced work, delivery dates and resource constraints. Planning views do not authorize production or change customer agreements.</p>
      <nav aria-label="Calendar feature navigation"><Link to="/orders">Order Decision Queue</Link><Link to="/orders/portfolio">Portfolio Comparison</Link></nav></div>
      <button className="foundation-button foundation-button-secondary" type="button" onClick={refresh} disabled={query.isFetching || !window}>Refresh calendar</button></header>
    <UncertaintyNote kind="conditional">Read only. Portfolio inclusion is not a production job; a requested delivery date is not a promised date. No acceptance, reservation, drag-and-drop or rescheduling submission is connected.</UncertaintyNote>
    <div className="cal-source"><StatusBadge state="UNKNOWN" label={data ? 'Source response received · read only' : 'Schedule data unavailable'} />
      <EvidenceTierBadge evidenceTier={data?.evidenceTier ?? 'TARGET'} {...(data ? { integrationMode: data.integrationMode } : {})} />
      {timeZone === 'Asia/Kuala_Lumpur' ? <LastUpdated value={data?.updatedAt} /> : <span>Last updated: {data ? scheduleTimeLabel({ kind: 'INSTANT', at: data.updatedAt }, timeZone) : 'Unknown'}</span>}
      <p>Display time zone: <strong>{timeZone}</strong> · intervals include start and exclude end; date-only records stay dates.</p>
      {data && <><p>Source: {data.source} · Snapshot: {data.snapshotId} v{data.snapshotVersion}</p><p>Evidence: {data.evidence.join(', ') || 'Unavailable'}</p>
        <p>Expires: {scheduleTimeLabel({ kind: 'INSTANT', at: data.expiresAt }, timeZone)}</p></>}</div>
    <div className="cal-toolbar"><fieldset><legend>Calendar view</legend>{(['DAY', 'WEEK', 'MONTH'] as const).map(mode => <button type="button" key={mode} aria-pressed={view === mode}
      onClick={() => { if (calendarWindow(date, mode, timeZone, weekStartsOn)) setView(mode); }}>{mode === 'DAY' ? 'Day' : mode === 'WEEK' ? 'Week' : 'Month'}</button>)}</fieldset>
      <div className="cal-period"><button type="button" aria-label="Previous period" disabled={!move(-1) || !calendarWindow(move(-1)!, view, timeZone, weekStartsOn)} onClick={() => changeDate(move(-1)!)}>Previous</button>
        <button type="button" onClick={() => changeDate(localDateAt(Date.now(), timeZone))}>Today</button>
        <button type="button" aria-label="Next period" disabled={!move(1) || !calendarWindow(move(1)!, view, timeZone, weekStartsOn)} onClick={() => changeDate(move(1)!)}>Next</button></div>
      <label>Chosen date<input type="date" min="0001-01-01" max="9999-12-31" value={date} onChange={e => changeDate(e.target.value)} /></label>
      <label>Week begins<select value={weekStartsOn} onChange={e => setWeekStartsOn(Number(e.target.value) as 0 | 1)}><option value="1">Monday</option><option value="0">Sunday</option></select></label>
    </div>
    <h2 aria-live="polite">{view === 'MONTH' ? civilLabel(date, { month: 'long', year: 'numeric' }) : view === 'DAY' ? civilLabel(date) :
      window ? `${civilLabel(window.from)} – ${civilLabel(addDays(window.toExclusive, -1)!)}` : 'Date window unavailable'}</h2>
    {query.isFetching && <p role="status">Loading calendar… Previous sensitive results are hidden.</p>}
    {!query.isFetching && conflict && <VersionConflictBanner currentVersion={data?.currentVersion} expectedVersion={data?.snapshotVersion} onRefresh={refresh}
      message="Schedule, request, resource or snapshot versions conflict. Events and resource availability are withheld." />}
    {!query.isFetching && query.error && !conflict && (query.error instanceof ScheduleUnavailableError ?
      <EmptyState kind="unavailable" title="Scheduling API unavailable" description="No verified production/delivery schedule read endpoint is connected. Calendar dates are navigable; tasks, promised delivery dates, conflicts and resource availability are unknown." /> : <ErrorState error={query.error} retrySafe onRetry={refresh} />)}
    {data && !conflict && !fresh && <EmptyState kind="unavailable" title="Current schedule unavailable" description="The snapshot is expired, stale, future-dated or unverified. Events, conflicts and resource details are withheld; refresh the source." />}
    {!window ? <EmptyState kind="unavailable" title="Date window unavailable" description="Choose a date within supported calendar boundaries." /> :
      <CalendarContents key={`${auth.tenantId}:${auth.actorId}:${window.from}:${window.toExclusive}:${data?.snapshotId}:${data?.snapshotVersion}:${data?.updatedAt}:${data?.events.map(e => `${e.id}:${e.scheduleVersion}`).join('|')}`}
        data={fresh && !conflict ? data : undefined} window={window} view={view} date={date} openDay={day => { setDate(day); setView('DAY'); }} />}
  </section>;
}

function CalendarContents({ data, window, view, date, openDay }: {
  data?: ScheduleSnapshot; window: NonNullable<ReturnType<typeof calendarWindow>>; view: CalendarView; date: string; openDay: (day: string) => void;
}) {
  const [filters, setFilters] = useState<CalendarFilters>(initialCalendarFilters);
  const [selected, setSelected] = useState<string | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const fullEvents = data?.events.filter(e => e.detailAccess === 'FULL') ?? [];
  const events = data ? filterSchedule(data, filters, window) : [];
  const loadedEvents = data?.events.filter(e => withinWindow(e.when, window)) ?? [];
  const update = <K extends keyof CalendarFilters>(key: K, value: CalendarFilters[K]) => { setSelected(null); setFilters(f => ({ ...f, [key]: value })); };
  const currentEvent = data?.events.find(e => e.id === selected);
  const conflictRows = data?.conflicts?.filter(c => withinWindow(c.when, window) && (!filters.resource || (c.detailAccess === 'FULL' && c.resourceIds.includes(filters.resource))) &&
    (!filters.search && !filters.type && !filters.status && !filters.authority && !filters.conflictsOnly || c.eventIds.some(id => events.some(e => e.id === id && e.detailAccess === 'FULL')))) ?? [];
  return <>
    {data?.coverage === 'PARTIAL' && <UncertaintyNote kind="insufficient-evidence">Partial schedule. Counts and filters apply only to loaded events; gaps and missing conflicts do not prove availability.</UncertaintyNote>}
    {data && <div className="cal-filters" role="group" aria-label="Schedule filters">
      <label>Event type<select value={filters.type} onChange={e => update('type', e.target.value)}><option value="">All types</option>
        {Array.from(new Set(data.events.map(e => e.type))).map(type => <option key={type}>{type}</option>)}</select></label>
      <label>Resource / machine<select value={filters.resource} onChange={e => update('resource', e.target.value)}><option value="">All authorized resources</option>
        {data.resources.filter(r => r.detailAccess === 'FULL').map(r => <option key={r.id} value={r.id}>{r.label}</option>)}</select></label>
      <label>Order ID or keyword<input type="search" value={filters.search} onChange={e => update('search', e.target.value)} /></label>
      <label>Source status<select value={filters.status} onChange={e => update('status', e.target.value)}><option value="">All statuses</option>
        {Array.from(new Set(fullEvents.map(e => e.status))).map(s => <option key={s}>{s}</option>)}</select></label>
      <label>Schedule authority<select value={filters.authority} onChange={e => update('authority', e.target.value)}><option value="">All authority labels</option>
        {Array.from(new Set(fullEvents.map(authorityLabel))).map(s => <option key={s}>{s}</option>)}</select></label>
      <label className="cal-check"><input type="checkbox" checked={filters.conflictsOnly} onChange={e => update('conflictsOnly', e.target.checked)} />Source conflicts only</label>
      <button type="button" onClick={() => { setSelected(null); setFilters(initialCalendarFilters); }}>Reset filters</button>
    </div>}
    <p className="cal-legend">Authority legend: confirmed source schedule · tentative proposal · simulation/forecast · historical record · unknown. Requested delivery dates remain requests. Color does not establish authority.</p>
    {data && !loadedEvents.length && <EmptyState kind="empty" title="No loaded schedule events" description={data.coverage === 'COMPLETE' ?
      'The source reports no events in this window. This is not evidence of free machine capacity.' : 'This partial source contains no events in the window. Missing work or capacity remains unknown.'} />}
    {data && !!loadedEvents.length && !events.length && <EmptyState kind="no-results" title="No events match the filters" description="Change or reset display filters. Filtering does not reschedule or remove work." />}
    <ol className={`cal-days cal-view-${view.toLowerCase()}`} aria-label={`${view.toLowerCase()} calendar dates`}>
      {daysInWindow(window).map(day => { const rows = eventsForDay(events, day, window.timeZone); const shown = view === 'MONTH' ? rows.slice(0, 3) : rows;
        return <li key={day} className={day.slice(0, 7) === date.slice(0, 7) ? '' : 'cal-adjacent'}>
          <h3><button type="button" aria-label={`Open day ${day}`} onClick={() => openDay(day)}><time dateTime={day}>{civilLabel(day, { weekday: 'short', day: 'numeric', month: 'short' })}</time></button></h3>
          <span className="cal-count">{data ? `${rows.length} loaded event${rows.length === 1 ? '' : 's'}` : 'Schedule unknown'}</span>
          {shown.map(event => <button className="cal-event" type="button" key={event.id} aria-label={`Inspect ${eventLabel(event)} on ${day}`}
            data-authority={event.detailAccess === 'FULL' && event.authority.evidence.length ? event.authority.kind : 'UNKNOWN'} onClick={e => { trigger.current = e.currentTarget; setSelected(event.id); }}>
            <strong>{eventLabel(event)}</strong><small>{event.type}{event.detailAccess === 'FULL' && event.deliveryMilestone ? ` · ${event.deliveryMilestone}` : ''} · {authorityLabel(event)}</small>
            {view !== 'MONTH' && <small>{scheduleTimeLabel(event.when, window.timeZone)}</small>}
          </button>)}
          {rows.length > shown.length && <button type="button" onClick={() => openDay(day)}>See all {rows.length} loaded events</button>}
        </li>; })}
    </ol>
    {data && currentEvent && <CalendarEventPanel key={`${currentEvent.id}:${currentEvent.scheduleVersion}`} event={currentEvent} snapshot={data} returnFocus={trigger.current} onClose={() => setSelected(null)} />}
    {data ? <><CalendarResources data={data} window={window} resource={filters.resource} />
      <section aria-label="Source scheduling conflicts"><h2>Scheduling conflicts</h2>
        {(data.conflicts === null || data.conflictCoverage !== 'VALIDATED_COMPLETE') && <UncertaintyNote kind="insufficient-evidence">Validated conflict coverage unavailable or partial. A missing finding is not zero conflicts.</UncertaintyNote>}
        {!conflictRows.length && <p>{data.conflicts !== null && data.conflictCoverage === 'VALIDATED_COMPLETE' && data.coverage === 'COMPLETE' ?
          'No source-reported conflicts match this window and filter. No future availability guarantee.' : 'No loaded conflict finding · conflict status Unknown'}</p>}
        {conflictRows.map(c => <article className="cal-card" key={c.id}>{c.detailAccess === 'REDACTED' ? <h3>Redacted conflict</h3> : <>
          <h3>{c.id} · {c.explanation}</h3><p>Severity: {c.severity || 'Unknown'}</p><p>{scheduleTimeLabel(c.when, window.timeZone)}</p>
          <p>Tasks: {c.eventIds.map(id => eventLabel(data.events.find(e => e.id === id)!)).join(', ') || 'Not supplied'}</p>
          <p>Resources: {c.resourceIds.map(id => { const r = data.resources.find(r => r.id === id)!; return r.detailAccess === 'FULL' ? r.label : 'Redacted resource'; }).join(', ') || 'Not supplied'}</p>
          <p>Source: {c.source} · version {c.sourceVersion} · Evidence: {c.evidence.join(', ')}</p>
          <UncertaintyNote kind="conditional">{c.uncertainty || 'No additional uncertainty statement supplied.'}</UncertaintyNote>
        </>}</article>)}
      </section></> : <EmptyState kind="unavailable" title="Resource availability and conflicts Unknown" description="No current verified schedule snapshot is available. Empty dates do not mean free resources or no conflicts." />}
  </>;
}

/** Route-ready; source and zone configuration must come from reviewed application integration. */
export function CalendarSchedulingPage({ source = unavailableScheduleSource, timeZone = 'Asia/Kuala_Lumpur', initialDate }: CalendarPageProps = {}) {
  const { tenantId, actorId } = useAuth();
  if (!validZone(timeZone)) return <ErrorState kind="validation" title="Unsupported calendar time zone" description="A valid IANA business time zone is required." />;
  return <CalendarWorkspace key={`${tenantId}:${actorId}:${source.cacheKey}:${timeZone}`} source={source} timeZone={timeZone} initialDate={initialDate} />;
}
