import { describe, expect, it } from 'vitest';
import { calendarWindow } from './calendarDates';
import { scheduleFresh, validateSchedule } from './calendarSource';
import { authorityLabel, filterSchedule, initialCalendarFilters } from './calendarView';
import { calendarFixture, calendarTestNow as now } from './calendarTest.fixtures';
import type { ScheduleSnapshot } from './calendarTypes';
const window = calendarWindow('2026-10-24', 'MONTH', 'Asia/Kuala_Lumpur', 1)!;
const auth = { tenantId: 'test-tenant', actorId: 'user_owner_01' };

describe('Schedule read identity, versions, timestamps and provenance', () => {
  it('retains source objects without mutating them', () => {
    const data = calendarFixture(); const copy = structuredClone(data); expect(validateSchedule(data, window, auth)).toBe(data); expect(data).toEqual(copy);
  });
  it.each<[string, (d: ScheduleSnapshot) => void]>([
    ['wrong tenant', d => { d.tenantId = 'foreign'; }], ['wrong actor', d => { d.actorId = 'foreign'; }],
    ['read denied', d => { d.readAuthorized = false; }], ['foreign event tenant', d => { d.events[0].tenantId = 'foreign'; }],
    ['foreign order', d => { d.events[0].order.id = 'foreign'; }], ['foreign resource', d => { d.events[0].resources[0].id = 'foreign'; }],
    ['request version conflict', d => { d.events[0].order.requestVersion = '99'; }],
    ['resource version conflict', d => { d.events[0].resources[0].version = '99'; }],
    ['snapshot version conflict', d => { d.events[0].snapshotVersion = '99'; }],
    ['schedule version conflict', d => { d.events[0].currentScheduleVersion = '99'; }],
    ['duplicate events', d => { d.events.push(d.events[0]); }], ['duplicate resources', d => { d.resources.push(d.resources[0]); }],
    ['duplicate orders', d => { d.orders.push(d.orders[0]); }], ['duplicate conflicts', d => { d.conflicts!.push(d.conflicts![0]); }],
    ['invalid instant', d => { d.events[0].when = { kind: 'INTERVAL', start: '2026-02-30T00:00:00Z', end: '2026-03-01T00:00:00Z' }; }],
    ['reversed interval', d => { d.events[0].when = { kind: 'INTERVAL', start: '2026-10-24T03:00:00Z', end: '2026-10-24T02:00:00Z' }; }],
    ['naive timestamp', d => { d.updatedAt = '2026-10-24T02:00:00'; }], ['reversed expiry', d => { d.expiresAt = d.updatedAt; }],
    ['wrong time zone', d => { d.window.timeZone = 'UTC'; }], ['incomplete horizon', d => { d.window.from = '2026-10-24'; }],
    ['unknown dependency', d => { d.events[0].dependencies = ['foreign']; }], ['self dependency', d => { d.events[0].dependencies = [d.events[0].id]; }],
    ['foreign conflict event', d => { d.conflicts![0].eventIds = ['foreign']; }], ['foreign conflict resource', d => { d.conflicts![0].resourceIds = ['foreign']; }],
    ['missing event evidence', d => { d.events[0].evidence = []; }], ['missing conflict evidence', d => { d.conflicts![0].evidence = []; }],
    ['requested delivery promoted to confirmed', d => { d.events[2].authority.kind = 'CONFIRMED_SCHEDULE'; }],
    ['production without interval', d => { d.events[0].when = { kind: 'DATE', date: '2026-10-24' }; }],
    ['zero utilization denominator', d => { d.resources[0].utilization!.denominator = '0.00'; }],
  ])('rejects %s', (_, edit) => { const data = calendarFixture(); edit(data); expect(() => validateSchedule(data, window, auth)).toThrow(); });
  it.each<[string, (d: ScheduleSnapshot) => void]>([
    ['unverified', d => { d.sourceVerified = false; }], ['missing evidence', d => { d.evidence = []; }],
    ['stale', d => { d.freshness = 'STALE'; }], ['unknown', d => { d.freshness = 'UNKNOWN'; }],
    ['expired', d => { d.expiresAt = '2026-10-24T02:30:00Z'; }], ['future', d => { d.updatedAt = '2026-10-24T03:01:00Z'; }],
    ['version mismatch', d => { d.currentVersion = '8'; }],
  ])('withholds %s snapshots', (_, edit) => { const d = calendarFixture(); edit(d); expect(scheduleFresh(d, now)).toBe(false); });
});
describe('Calendar authority and privacy', () => {
  it('requires explicit authority evidence; requested date is never a promise', () => {
    const d = calendarFixture(); expect(authorityLabel(d.events[0])).toContain('Confirmed schedule');
    d.events[0].authority.evidence = []; expect(authorityLabel(d.events[0])).toBe('Unknown authority');
    expect(authorityLabel(d.events[2])).toBe('Requested date · not promised');
    expect(authorityLabel(d.events[1])).toBe('Tentative proposal'); expect(authorityLabel(d.events[4])).toBe('Simulation / forecast');
    expect(authorityLabel(d.events[5])).toContain('Historical work');
  });
  it('never reveals redacted associations through order/resource/status/conflict filters', () => {
    const d = calendarFixture();
    for (const filters of [{ search: 'secret-order' }, { resource: 'secret-resource' }, { status: 'secret-status' }, { authority: 'Confirmed schedule · source evidenced' }, { conflictsOnly: true }]) {
      expect(filterSchedule(d, { ...initialCalendarFilters, ...filters }, window).some(e => e.id === 'secret-event')).toBe(false);
    }
  });
  it('sorts sourced events chronologically, independently of display month names', () => {
    const d = calendarFixture(); const events = filterSchedule(d, initialCalendarFilters, window);
    expect(events[0].id).toBe('history'); expect(events.at(-1)?.id).toBe('simulation');
  });
});
