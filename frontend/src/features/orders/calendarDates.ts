import type { CalendarView, CalendarWindow, ScheduleTime } from './calendarTypes';

/** Civil dates have no implicit midnight/offset. Date arithmetic runs on a UTC-noon carrier only. */
export function validDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
export function validZone(zone: string): boolean {
  try { new Intl.DateTimeFormat('en', { timeZone: zone }).format(); return true; } catch { return false; }
}
export function parseScheduleInstant(value: unknown): number | null {
  if (typeof value !== 'string') return null;
  const parts = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$/i.exec(value);
  if (!parts || !validDate(parts[1]) || +parts[2] > 23 || +parts[3] > 59 || +parts[4] > 59) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}
// Calendar filtering visits each event/date repeatedly; reuse the formatter for each configured zone.
const localDateFormatters = new Map<string, Intl.DateTimeFormat>();
export function localDateAt(instant: number, timeZone: string): string {
  let formatter = localDateFormatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' });
    localDateFormatters.set(timeZone, formatter);
  }
  const parts = formatter.formatToParts(instant);
  const get = (key: string) => parts.find(p => p.type === key)!.value;
  return `${get('year').padStart(4, '0')}-${get('month')}-${get('day')}`;
}
export function addDays(day: string, delta: number): string | null {
  if (!validDate(day)) return null;
  const carrier = new Date(`${day}T12:00:00Z`); carrier.setUTCDate(carrier.getUTCDate() + delta);
  const result = carrier.toISOString().slice(0, 10);
  return validDate(result) ? result : null;
}
export function addMonths(day: string, delta: number): string | null {
  if (!validDate(day)) return null;
  const date = new Date(`${day.slice(0, 7)}-01T12:00:00Z`); date.setUTCMonth(date.getUTCMonth() + delta);
  const nextMonth = new Date(date); nextMonth.setUTCMonth(nextMonth.getUTCMonth() + 1);
  nextMonth.setUTCDate(0);
  date.setUTCDate(Math.min(+day.slice(8), nextMonth.getUTCDate()));
  const result = date.toISOString().slice(0, 10);
  return validDate(result) ? result : null;
}
export function weekStart(day: string, startsOn: 0 | 1): string | null {
  const weekday = new Date(`${day}T12:00:00Z`).getUTCDay();
  return addDays(day, -((weekday - startsOn + 7) % 7));
}
export function calendarWindow(day: string, view: CalendarView, timeZone: string, startsOn: 0 | 1): CalendarWindow | null {
  if (!validDate(day) || !validZone(timeZone)) return null;
  const from = view === 'MONTH' ? weekStart(`${day.slice(0, 7)}-01`, startsOn) : view === 'WEEK' ? weekStart(day, startsOn) : day;
  if (!from) return null;
  let toExclusive = addDays(from, view === 'DAY' ? 1 : 7);
  if (view === 'MONTH') {
    const nextMonth = addMonths(`${day.slice(0, 7)}-01`, 1);
    if (!nextMonth) return null;
    const nextWeek = weekStart(nextMonth, startsOn);
    toExclusive = nextWeek === nextMonth ? nextMonth : nextWeek && addDays(nextWeek, 7);
  }
  return toExclusive ? { from, toExclusive, timeZone } : null;
}
export function daysInWindow(window: CalendarWindow): string[] {
  const days: string[] = [];
  for (let d: string | null = window.from; d && d < window.toExclusive && days.length < 42; d = addDays(d, 1)) days.push(d);
  return days;
}
export function validScheduleTime(when: ScheduleTime): boolean {
  if (!when) return false;
  if (when.kind === 'DATE') return validDate(when.date);
  if (when.kind === 'INSTANT') return parseScheduleInstant(when.at) !== null;
  return when.kind === 'INTERVAL' && parseScheduleInstant(when.start) !== null && parseScheduleInstant(when.end) !== null &&
    parseScheduleInstant(when.start)! < parseScheduleInstant(when.end)!;
}
/** Intervals are [start,end); a task ending at local midnight does not occupy the next date. */
export function occursOn(when: ScheduleTime, day: string, timeZone: string): boolean {
  if (when.kind === 'DATE') return when.date === day;
  if (when.kind === 'INSTANT') return localDateAt(parseScheduleInstant(when.at)!, timeZone) === day;
  return localDateAt(parseScheduleInstant(when.start)!, timeZone) <= day &&
    localDateAt(parseScheduleInstant(when.end)! - 1, timeZone) >= day;
}
export function withinWindow(when: ScheduleTime, window: CalendarWindow): boolean {
  return daysInWindow(window).some(day => occursOn(when, day, window.timeZone));
}
export function civilLabel(day: string, options: Intl.DateTimeFormatOptions = { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }): string {
  return new Intl.DateTimeFormat('en-GB', { ...options, timeZone: 'UTC' }).format(new Date(`${day}T12:00:00Z`));
}
export function scheduleTimeLabel(when: ScheduleTime, timeZone: string): string {
  if (when.kind === 'DATE') return `${civilLabel(when.date)} · date only`;
  const display = (value: string) => `${new Intl.DateTimeFormat('en-GB', { timeZone, year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', timeZoneName: 'shortOffset', hourCycle: 'h23' }).format(parseScheduleInstant(value)!)} [${value}]`;
  return when.kind === 'INSTANT' ? display(when.at) : `${display(when.start)} → ${display(when.end)} (end exclusive)`;
}
