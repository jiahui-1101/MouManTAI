import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ApiError } from '../../shared/api';
import { useAuth } from '../../shared/auth';
import { EmptyState, ErrorState, EvidenceTierBadge, UncertaintyNote, VersionConflictBanner } from '../../shared/ui';
import { addDays, addMonths, calendarWindow, civilLabel, daysInWindow, localDateAt, parseScheduleInstant, scheduleTimeLabel, validDate, validZone, withinWindow } from './calendarDates';
import { ScheduleUnavailableError, ScheduleVersionError, scheduleFresh, unavailableScheduleSource, validateSchedule } from './calendarSource';
import { authorityLabel, eventLabel, eventsForDay, filterSchedule, initialCalendarFilters } from './calendarView';
import type { CalendarFilters, CalendarView, ScheduleSnapshot, ScheduleSource } from './calendarTypes';
import { demoScheduleSource, ordersDemoEnabled } from './demoSource';
import { CalendarEventPanel } from './CalendarEventPanel';
import { CalendarResources } from './CalendarResources';
import { portfolioCalendarHref } from './portfolioCalendarContext';
import redCircleImg from '../../assets/red-circle.png';
import './calendar.css';

interface CalendarPageProps { source?: ScheduleSource; timeZone?: string; initialDate?: string }
function CalendarWorkspace({ source, timeZone, initialDate }: Required<Pick<CalendarPageProps, 'source' | 'timeZone'>> & Pick<CalendarPageProps, 'initialDate'>) {
  const { authHeaders: auth } = useAuth();
  const [date, setDate] = useState(initialDate && validDate(initialDate) ? initialDate : localDateAt(Date.now(), timeZone));
  const [view, setView] = useState<CalendarView>('MONTH');
  const [weekStartsOn, setWeekStartsOn] = useState<0 | 1>(1);
  // Display preferences survive range/snapshot changes, within this identity/source/zone only.
  const [filters, setFilters] = useState<CalendarFilters>(initialCalendarFilters);
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
    <header className="cal-header">
      <div className="cal-header-left">
        <h1 id="cal-title">Production & Delivery Calendar</h1>
        <nav className="cal-nav-compact" aria-label="Calendar feature navigation">
          <Link to="/orders">Order Decision Queue</Link>
          <span className="cal-nav-sep" aria-hidden="true">·</span>
          <Link to={window ? portfolioCalendarHref(date, window) : '/orders/portfolio'}>Portfolio Comparison</Link>
        </nav>
      </div>
      <div className="cal-header-right">
        <span className="cal-tz-chip">Display time zone: <strong>{timeZone}</strong></span>
        <EvidenceTierBadge evidenceTier={data?.evidenceTier ?? 'TARGET'} {...(data ? { integrationMode: data.integrationMode } : {})} />
        <button className="foundation-button foundation-button-secondary cal-refresh-compact" type="button" onClick={refresh} disabled={query.isFetching || !window}>
          Refresh calendar
        </button>
      </div>
    </header>

    {data && (
      <div className="cal-snapshot-bar">
        <span>Source: <strong>{data.source}</strong></span>
        <span>Snapshot: {data.snapshotId} v{data.snapshotVersion}</span>
        <span>Expires: {scheduleTimeLabel({ kind: 'INSTANT', at: data.expiresAt }, timeZone)}</span>
      </div>
    )}

    <div className="cal-toolbar">
      <div className="cal-header-period-nav">
        <button
          type="button"
          className="cal-chevron-btn"
          aria-label="Previous period"
          disabled={!move(-1) || !calendarWindow(move(-1)!, view, timeZone, weekStartsOn)}
          onClick={() => changeDate(move(-1)!)}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <h2 aria-live="polite" className="cal-period-heading">
          {view === 'MONTH' ? civilLabel(date, { month: 'long', year: 'numeric' }) : view === 'DAY' ? civilLabel(date) :
            window ? `${civilLabel(window.from)} – ${civilLabel(addDays(window.toExclusive, -1)!)}` : 'Date window unavailable'}
        </h2>
        <button
          type="button"
          className="cal-chevron-btn"
          aria-label="Next period"
          disabled={!move(1) || !calendarWindow(move(1)!, view, timeZone, weekStartsOn)}
          onClick={() => changeDate(move(1)!)}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
        <button type="button" className="cal-today-sr-btn" onClick={() => changeDate(localDateAt(Date.now(), timeZone))}>
          Today
        </button>
      </div>

      <div className="cal-toolbar-controls">
        <fieldset className="cal-view-selector">
          <legend>Calendar view</legend>
          <div className="cal-view-group">
            {(['DAY', 'WEEK', 'MONTH'] as const).map(mode => (
              <button
                type="button"
                key={mode}
                className={`cal-mode-btn ${view === mode ? 'cal-mode-active' : ''}`}
                aria-pressed={view === mode}
                onClick={() => { if (calendarWindow(date, mode, timeZone, weekStartsOn)) setView(mode); }}
              >
                {mode === 'DAY' ? 'Day' : mode === 'WEEK' ? 'Week' : 'Month'}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="cal-inputs-wrap">
          <label>Chosen date<input type="date" min="0001-01-01" max="9999-12-31" value={date} onChange={e => changeDate(e.target.value)} /></label>
          <label>Week begins<select value={weekStartsOn} onChange={e => setWeekStartsOn(Number(e.target.value) as 0 | 1)}><option value="1">Monday</option><option value="0">Sunday</option></select></label>
        </div>
      </div>
    </div>

    {query.isFetching && <p role="status" className="cal-loading-status">Loading calendar… Previous sensitive results are hidden.</p>}
    {!query.isFetching && conflict && <VersionConflictBanner currentVersion={data?.currentVersion} expectedVersion={data?.snapshotVersion} onRefresh={refresh}
      message="Schedule, request, resource or snapshot versions conflict. Events and resource availability are withheld." />}
    {!query.isFetching && query.error && !conflict && (
      <div className="cal-banner-hidden">
        {query.error instanceof ScheduleUnavailableError ?
          <EmptyState kind="unavailable" title="Scheduling API unavailable" description="No verified production/delivery schedule read endpoint is connected. Calendar dates are navigable; tasks, promised delivery dates, conflicts and resource availability are unknown." /> : <ErrorState error={query.error} retrySafe onRetry={refresh} />}
      </div>
    )}
    {data && !conflict && !fresh && <EmptyState kind="unavailable" title="Current schedule unavailable" description="The snapshot is expired, stale, future-dated or unverified. Events, conflicts and resource details are withheld; refresh the source." />}
    {!window ? <EmptyState kind="unavailable" title="Date window unavailable" description="Choose a date within supported calendar boundaries." /> :
      <CalendarContents key={`${auth.tenantId}:${auth.actorId}:${window.from}:${window.toExclusive}:${data?.snapshotId}:${data?.snapshotVersion}:${data?.updatedAt}:${data?.events.map(e => `${e.id}:${e.scheduleVersion}`).join('|')}`}
        data={fresh && !conflict ? data : undefined} filters={filters} setFilters={setFilters}
        window={window} view={view} date={date} weekStartsOn={weekStartsOn} openDay={day => { setDate(day); setView('DAY'); }} />}
  </section>;
}

function CalendarContents({ data, filters, setFilters, window, view, date, weekStartsOn, openDay }: {
  data?: ScheduleSnapshot; window: NonNullable<ReturnType<typeof calendarWindow>>; view: CalendarView; date: string; weekStartsOn: 0 | 1; openDay: (day: string) => void;
  filters: CalendarFilters; setFilters: Dispatch<SetStateAction<CalendarFilters>>;
}) {
  // Keep sensitive selection inside the range/snapshot-keyed child so it still resets.
  const [selected, setSelected] = useState<{ id: string; snapshot: ScheduleSnapshot } | null>(null);
  // An immediate/batched refresh may skip the loading render and retain the child key.
  // Bind inspection to the actual validated response as well as the keyed context.
  useEffect(() => { setSelected(null); }, [data]);
  const trigger = useRef<HTMLElement | null>(null);
  const fullEvents = data?.events.filter(e => e.detailAccess === 'FULL') ?? [];
  const types: string[] = Array.from(new Set(data?.events.map(e => e.type) ?? []));
  const resources = data?.resources.filter(r => r.detailAccess === 'FULL') ?? [];
  const statuses = Array.from(new Set(fullEvents.map(e => e.status)));
  const authorities = Array.from(new Set(fullEvents.map(authorityLabel)));
  // Retain the preference without exposing an old label/ID or silently showing "All".
  const selection = (key: 'type' | 'resource' | 'status' | 'authority', options: string[]) =>
    filters[key] && !options.includes(filters[key]) ? '__unavailable__' : filters[key];
  const unavailableOption = <option value="__unavailable__" disabled>Saved filter unavailable in this snapshot</option>;
  const events = data ? filterSchedule(data, filters, window) : [];
  const loadedEvents = data?.events.filter(e => withinWindow(e.when, window)) ?? [];
  const update = <K extends keyof CalendarFilters>(key: K, value: CalendarFilters[K]) => { setSelected(null); setFilters(f => ({ ...f, [key]: value })); };
  const currentEvent = data === selected?.snapshot ? events.find(e => e.id === selected?.id) : undefined;
  const conflictRows = data?.conflicts?.filter(c => withinWindow(c.when, window) && (!filters.resource || (c.detailAccess === 'FULL' && c.resourceIds.includes(filters.resource))) &&
    (!filters.search && !filters.type && !filters.status && !filters.authority && !filters.conflictsOnly || c.eventIds.some(id => events.some(e => e.id === id && e.detailAccess === 'FULL')))) ?? [];
  
  const weekdayNames = weekStartsOn === 1 ? ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] : ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  return <>
    {data?.coverage === 'PARTIAL' && <UncertaintyNote kind="insufficient-evidence">Partial schedule. Counts and filters apply only to loaded events; gaps and missing conflicts do not prove availability.</UncertaintyNote>}
    {data && <div className="cal-filters" role="group" aria-label="Schedule filters">
      <label>Event type<select value={selection('type', types)} onChange={e => update('type', e.target.value)}><option value="">All types</option>
        {filters.type && !types.includes(filters.type) && unavailableOption}
        {types.map(type => <option key={type}>{type}</option>)}</select></label>
      <label>Resource / machine<select value={selection('resource', resources.map(r => r.id))} onChange={e => update('resource', e.target.value)}><option value="">All authorized resources</option>
        {filters.resource && !resources.some(r => r.id === filters.resource) && unavailableOption}
        {resources.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}</select></label>
      <label>Order ID or keyword<input type="search" value={filters.search} onChange={e => update('search', e.target.value)} /></label>
      <label>Source status<select value={selection('status', statuses)} onChange={e => update('status', e.target.value)}><option value="">All statuses</option>
        {filters.status && !statuses.includes(filters.status) && unavailableOption}
        {statuses.map(s => <option key={s}>{s}</option>)}</select></label>
      <label>Schedule authority<select value={selection('authority', authorities)} onChange={e => update('authority', e.target.value)}><option value="">All authority labels</option>
        {filters.authority && !authorities.includes(filters.authority) && unavailableOption}
        {authorities.map(s => <option key={s}>{s}</option>)}</select></label>
      <label className="cal-check"><input type="checkbox" checked={filters.conflictsOnly} onChange={e => update('conflictsOnly', e.target.checked)} />Source conflicts only</label>
      <button type="button" onClick={() => { setSelected(null); setFilters(initialCalendarFilters); }}>Reset filters</button>
    </div>}
    {data && !loadedEvents.length && <EmptyState kind="empty" title="No loaded schedule events" description={data.coverage === 'COMPLETE' ?
      'The source reports no events in this window. This is not evidence of free machine capacity.' : 'This partial source contains no events in the window. Missing work or capacity remains unknown.'} />}
    {data && !!loadedEvents.length && !events.length && <EmptyState kind="no-results" title="No events match the filters" description="Change or reset display filters. Filtering does not reschedule or remove work." />}
    
    <div className="cal-continuous-grid">
      {view === 'MONTH' && (
        <div className="cal-weekdays-bar" aria-hidden="true">
          {weekdayNames.map(name => (
            <div key={name} className="cal-weekday-name">{name}</div>
          ))}
        </div>
      )}

      <ol className={`cal-days cal-view-${view.toLowerCase()}`} aria-label={`${view.toLowerCase()} calendar dates`}>
        {daysInWindow(window).map(day => {
          const rows = eventsForDay(events, day, window.timeZone);
          const shown = view === 'MONTH' ? rows.slice(0, 3) : rows;
          const isCurrentMonth = day.slice(0, 7) === date.slice(0, 7);
          const hasOrders = rows.length > 0;
          return <li key={day} className={`${isCurrentMonth ? '' : 'cal-adjacent'} ${hasOrders ? 'cal-cell-has-orders' : ''}`}>
            <div className="cal-day-cell-top">
              <h3>
                <button type="button" className="cal-day-action" aria-label={`Open day ${day}`} onClick={() => openDay(day)}>
                  <span className="cal-day-number-wrap">
                    {hasOrders && (
                      <img
                        src={redCircleImg}
                        alt=""
                        aria-hidden="true"
                        className="cal-red-brush-circle"
                      />
                    )}
                    <time dateTime={day} className="cal-day-num-time">
                      <span className="cal-day-num-digit">{day.slice(8).replace(/^0/, '')}</span>
                    </time>
                  </span>
                </button>
              </h3>
              <span className={`cal-count ${hasOrders ? 'cal-count-highlight' : ''}`}>{data ? `${rows.length} loaded event${rows.length === 1 ? '' : 's'}` : 'Schedule unknown'}</span>
            </div>
            <div className="cal-day-events-container">
              {shown.map(event => <button className="cal-event" type="button" key={event.id} aria-label={`Inspect ${eventLabel(event)} on ${day}`}
                data-authority={event.detailAccess === 'FULL' && event.authority.evidence.length ? event.authority.kind : 'UNKNOWN'} onClick={e => { trigger.current = e.currentTarget; if (data) setSelected({ id: event.id, snapshot: data }); }}>
                <div className="cal-event-chips">
                  <span className="cal-chip-type">{event.type}</span>
                  {event.detailAccess === 'FULL' && event.deliveryMilestone && (
                    <span className="cal-chip-milestone">{event.deliveryMilestone}</span>
                  )}
                </div>
                <strong className="cal-event-name">{eventLabel(event)}</strong>
                <small className="cal-event-meta">{event.type}{event.detailAccess === 'FULL' && event.deliveryMilestone ? ` · ${event.deliveryMilestone}` : ''} · {authorityLabel(event)}</small>
                {view !== 'MONTH' && <small className="cal-event-time">{scheduleTimeLabel(event.when, window.timeZone)}</small>}
              </button>)}
              {rows.length > shown.length && <button type="button" className="cal-see-more-action" onClick={() => openDay(day)}>See all {rows.length} loaded events</button>}
            </div>
          </li>;
        })}
      </ol>
    </div>
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
      </section></> : <div className="cal-banner-hidden"><EmptyState kind="unavailable" title="Resource availability and conflicts Unknown" description="No current verified schedule snapshot is available. Empty dates do not mean free resources or no conflicts." /></div>}
  </>;
}

/** Route-ready; source and zone configuration must come from reviewed application integration. */
export function CalendarSchedulingPage({ source = ordersDemoEnabled() ? demoScheduleSource : unavailableScheduleSource, timeZone = 'Asia/Kuala_Lumpur', initialDate }: CalendarPageProps = {}) {
  const { tenantId, actorId } = useAuth();
  if (!validZone(timeZone)) return <ErrorState kind="validation" title="Unsupported calendar time zone" description="A valid IANA business time zone is required." />;
  return <CalendarWorkspace key={`${tenantId}:${actorId}:${source.cacheKey}:${timeZone}`} source={source} timeZone={timeZone} initialDate={initialDate} />;
}



