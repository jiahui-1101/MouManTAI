import { describe, expect, it } from 'vitest';
import { addDays, addMonths, calendarWindow, daysInWindow, localDateAt, occursOn, parseScheduleInstant, scheduleTimeLabel, validDate, validScheduleTime, weekStart } from './calendarDates';

describe('Civil calendar arithmetic independent of browser timezone', () => {
  it.each(['2026-02-29', '2024-02-30', '2026-13-01', '2026-04-31', '2026-1-01', '0000-01-01', '', 'not-a-date'])('rejects invalid date %s', value => expect(validDate(value)).toBe(false));
  it('handles leap days and month/year rollover', () => {
    expect(addDays('2024-02-28', 1)).toBe('2024-02-29'); expect(addDays('2024-02-29', 1)).toBe('2024-03-01');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01'); expect(addDays('2027-01-01', -1)).toBe('2026-12-31');
    expect(addMonths('2024-01-31', 1)).toBe('2024-02-29'); expect(addMonths('2026-03-31', -1)).toBe('2026-02-28');
    expect(addMonths('2026-12-31', 1)).toBe('2027-01-31'); expect(addDays('9999-12-31', 1)).toBeNull();
  });
  it('uses configurable Monday/Sunday week starts', () => {
    expect(weekStart('2026-10-25', 1)).toBe('2026-10-19'); expect(weekStart('2026-10-25', 0)).toBe('2026-10-25');
    expect(calendarWindow('2027-01-01', 'WEEK', 'Asia/Kuala_Lumpur', 1)).toEqual({ from: '2026-12-28', toExclusive: '2027-01-04', timeZone: 'Asia/Kuala_Lumpur' });
  });
  it('returns correct 28/35/42-cell months without assuming 30 days', () => {
    expect(daysInWindow(calendarWindow('2021-02-10', 'MONTH', 'UTC', 1)!)).toHaveLength(28);
    expect(daysInWindow(calendarWindow('2026-10-24', 'MONTH', 'UTC', 1)!)).toHaveLength(35);
    expect(daysInWindow(calendarWindow('2026-08-24', 'MONTH', 'UTC', 1)!)).toHaveLength(42);
    expect(calendarWindow('2026-10-24', 'DAY', 'UTC', 1)?.toExclusive).toBe('2026-10-25');
  });
  it('does not convert a date-only delivery into midnight UTC', () => {
    const when = { kind: 'DATE' as const, date: '2026-10-24' };
    for (const zone of ['UTC', 'Asia/Kuala_Lumpur', 'America/New_York']) {
      expect(occursOn(when, '2026-10-24', zone)).toBe(true); expect(occursOn(when, '2026-10-23', zone)).toBe(false);
      expect(scheduleTimeLabel(when, zone)).toContain('date only'); expect(scheduleTimeLabel(when, zone)).not.toContain('00:00');
    }
  });
});
describe('Offset-aware schedule intervals', () => {
  it.each(['2026-02-30T12:00:00Z', '2026-10-24T24:00:00Z', '2026-10-24T12:60:00Z', '2026-10-24T12:00:60Z',
    '2026-10-24T12:00:00', '2026-10-24', '2026-10-24T12:00:00+24:00', 'invalid'])('rejects %s', value => expect(parseScheduleInstant(value)).toBeNull());
  it('accepts UTC, offsets and microseconds preserving original timestamps in display', () => {
    expect(parseScheduleInstant('2026-10-24T12:00:00+08:00')).toBe(parseScheduleInstant('2026-10-24T04:00:00Z'));
    expect(parseScheduleInstant('2026-10-24T12:00:00.123456+08:00')).not.toBeNull();
    expect(scheduleTimeLabel({ kind: 'INSTANT', at: '2026-10-24T12:00:00+08:00' }, 'UTC')).toContain('[2026-10-24T12:00:00+08:00]');
  });
  it('rejects reversed/zero intervals including offsets', () => {
    expect(validScheduleTime({ kind: 'INTERVAL', start: '2026-10-24T12:00:00+08:00', end: '2026-10-24T04:00:00Z' })).toBe(false);
    expect(validScheduleTime({ kind: 'INTERVAL', start: '2026-10-24T12:00:00Z', end: '2026-10-24T11:00:00Z' })).toBe(false);
  });
  it('renders cross-midnight and multi-day tasks on each intersecting date, excluding midnight end', () => {
    const when = { kind: 'INTERVAL' as const, start: '2026-10-23T15:00:00Z', end: '2026-10-25T16:00:00Z' };
    for (const day of ['2026-10-23', '2026-10-24', '2026-10-25']) expect(occursOn(when, day, 'Asia/Kuala_Lumpur')).toBe(true);
    expect(occursOn(when, '2026-10-26', 'Asia/Kuala_Lumpur')).toBe(false);
  });
  it('handles spring-forward DST using actual offsets without assuming 24-hour days', () => {
    const when = { kind: 'INTERVAL' as const, start: '2026-03-08T00:00:00-05:00', end: '2026-03-09T00:00:00-04:00' };
    expect((parseScheduleInstant(when.end)! - parseScheduleInstant(when.start)!) / 3_600_000).toBe(23);
    expect(occursOn(when, '2026-03-08', 'America/New_York')).toBe(true); expect(occursOn(when, '2026-03-09', 'America/New_York')).toBe(false);
  });
  it('handles repeated fall-back hours and 25-hour days', () => {
    const when = { kind: 'INTERVAL' as const, start: '2026-11-01T00:00:00-04:00', end: '2026-11-02T00:00:00-05:00' };
    expect((parseScheduleInstant(when.end)! - parseScheduleInstant(when.start)!) / 3_600_000).toBe(25);
    expect(localDateAt(parseScheduleInstant('2026-11-01T01:30:00-04:00')!, 'America/New_York')).toBe('2026-11-01');
    expect(localDateAt(parseScheduleInstant('2026-11-01T01:30:00-05:00')!, 'America/New_York')).toBe('2026-11-01');
    expect(occursOn(when, '2026-11-02', 'America/New_York')).toBe(false);
  });
});
