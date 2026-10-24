import { useLocation } from 'react-router-dom';
import { validDate, validZone } from './calendarDates';
import type { CalendarWindow } from './calendarTypes';

const keys = ['calDate', 'calFrom', 'calTo', 'calZone'] as const;
export interface PortfolioCalendarRequest { date: string; from: string; toExclusive: string; timeZone: string }
export function readPortfolioCalendarRequest(search: string): PortfolioCalendarRequest | null {
  const params = new URLSearchParams(search);
  if (!keys.every(key => params.getAll(key).length === 1)) return null;
  const [date, from, toExclusive, timeZone] = keys.map(key => params.get(key)!);
  if (!validDate(date) || !validDate(from) || !validDate(toExclusive) || !validZone(timeZone) ||
    from >= toExclusive || date < from || date >= toExclusive) return null;
  return { date, from, toExclusive, timeZone };
}
/** Navigation metadata only. Never passed to a PortfolioSource or HTTP client. */
export function portfolioCalendarHref(date: string, window: CalendarWindow): string {
  const params = new URLSearchParams({ calDate: date, calFrom: window.from, calTo: window.toExclusive, calZone: window.timeZone });
  return readPortfolioCalendarRequest(`?${params}`) ? `/orders/portfolio?${params}` : '/orders/portfolio';
}
export function PortfolioCalendarContext() {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  if (!keys.some(key => params.has(key))) return null;
  const request = readPortfolioCalendarRequest(search);
  return <section className="pc-card" aria-label="Requested Calendar comparison context"><h2>Requested comparison dates</h2>
    {request ? <>
      <p>Requested Calendar date: <time dateTime={request.date}>{request.date}</time></p>
      <p>Requested visible range: <time dateTime={request.from}>{request.from}</time> (inclusive) to <time dateTime={request.toExclusive}>{request.toExclusive}</time> (exclusive).</p>
      <p>Calendar display timezone: {request.timeZone}</p>
      <p>Request context only. Portfolio date coverage is not supplied by the current source contract. Results are not filtered by these dates, and these dates do not establish a current assessment.</p>
    </> : <p role="status">Calendar date context ignored: dates, range or timezone are incomplete, invalid or inconsistent. Choose the dates again in Calendar. No date filtering was applied.</p>}
  </section>;
}
