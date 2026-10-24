import { localDateAt, occursOn, parseScheduleInstant, withinWindow } from './calendarDates';
import type { CalendarFilters, CalendarWindow, ScheduleEvent, ScheduleSnapshot } from './calendarTypes';

export const initialCalendarFilters: CalendarFilters = { type: '', resource: '', search: '', status: '', authority: '', conflictsOnly: false };
export function authorityLabel(event: ScheduleEvent): string {
  if (event.detailAccess === 'REDACTED') return 'Authority redacted';
  if (event.deliveryMilestone === 'REQUESTED') return 'Requested date · not promised';
  if (event.authority.kind !== 'UNKNOWN' && !event.authority.evidence.length) return 'Unknown authority';
  return { CONFIRMED_SCHEDULE: 'Confirmed schedule · source evidenced', TENTATIVE: 'Tentative proposal',
    SIMULATION: 'Simulation / forecast', HISTORICAL: 'Historical work · source recorded', UNKNOWN: 'Unknown authority' }[event.authority.kind];
}
export const eventLabel = (event: ScheduleEvent) => event.detailAccess === 'REDACTED' ? 'Redacted event' : event.title;
export function filterSchedule(data: ScheduleSnapshot, filters: CalendarFilters, window: CalendarWindow): ScheduleEvent[] {
  return data.events.filter(e => {
    if (!withinWindow(e.when, window) || (filters.type && e.type !== filters.type)) return false;
    if (e.detailAccess === 'REDACTED') return !filters.resource && !filters.search && !filters.status && !filters.authority && !filters.conflictsOnly;
    const allowedResources = data.resources.filter(r => r.detailAccess === 'FULL');
    return (!filters.resource || (allowedResources.some(r => r.id === filters.resource) && e.resources.some(r => r.id === filters.resource))) &&
      (!filters.search || `${e.order.id} ${e.title} ${e.stage ?? ''}`.toLowerCase().includes(filters.search.trim().toLowerCase())) &&
      (!filters.status || e.status === filters.status) && (!filters.authority || authorityLabel(e) === filters.authority) &&
      (!filters.conflictsOnly || (data.conflicts ?? []).some(c => c.detailAccess === 'FULL' && c.eventIds.includes(e.id) && withinWindow(c.when, window)));
  }).sort((a, b) => {
    const start = (e: ScheduleEvent) => e.when.kind === 'DATE' ? null : parseScheduleInstant(e.when.kind === 'INTERVAL' ? e.when.start : e.when.at)!;
    const day = (e: ScheduleEvent) => e.when.kind === 'DATE' ? e.when.date : localDateAt(start(e)!, window.timeZone);
    return day(a).localeCompare(day(b)) || (start(a) === null && start(b) === null ? 0 : start(a) === null ? -1 : start(b) === null ? 1 : start(a)! - start(b)!) || a.id.localeCompare(b.id);
  });
}
export const eventsForDay = (events: ScheduleEvent[], date: string, zone: string) => events.filter(e => occursOn(e.when, date, zone));
