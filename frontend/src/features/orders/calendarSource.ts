import { ApiError, type RequestAuthHeaders } from '../../shared/api';
import { parseScheduleInstant, validDate, validScheduleTime, validZone } from './calendarDates';
import type { CalendarWindow, ScheduleSnapshot, ScheduleSource } from './calendarTypes';

export class ScheduleUnavailableError extends Error {}
export class ScheduleVersionError extends Error {}
export class ScheduleContractError extends Error {}
export const unavailableScheduleSource: ScheduleSource = {
  cacheKey: 'schedule-api-unavailable-v1',
  async load() { throw new ScheduleUnavailableError('No verified scheduling read endpoint'); },
};
const text = (v: unknown): v is string => typeof v === 'string' && !!v.trim();
const optionalText = (v: unknown) => v === undefined || typeof v === 'string';
const refs = (v: unknown): v is string[] => Array.isArray(v) && v.every(text) && new Set(v).size === v.length;
const unique = (rows: string[]) => rows.every(text) && new Set(rows).size === rows.length;
const access = (v: unknown) => v === 'FULL' || v === 'REDACTED';
const numeric = (v: unknown) => typeof v === 'string' && /^\d+(\.\d+)?$/.test(v);
function requireContract(value: unknown): asserts value {
  if (!value) throw new ScheduleContractError('Schedule identity or presentation contract mismatch');
}
/** This is a guarded presentation port, not a trusted wire adapter. Server auth/redaction still required. */
export function validateSchedule(data: ScheduleSnapshot, requested: CalendarWindow, auth: RequestAuthHeaders): ScheduleSnapshot {
  requireContract(data && data.tenantId === auth.tenantId && data.actorId === auth.actorId);
  if (data.readAuthorized !== true) throw new ApiError(403, 'FORBIDDEN', 'Schedule read denied');
  requireContract(text(data.source) && typeof data.sourceVerified === 'boolean' && refs(data.evidence) &&
    ['TARGET', 'DEMO-ONLY', 'VALIDATED', 'LIVE'].includes(data.evidenceTier) && ['SYNTHETIC', 'MOCK_ORBYTE', 'LIVE'].includes(data.integrationMode) &&
    [data.snapshotId, data.snapshotVersion, data.currentVersion].every(text) && ['CURRENT', 'STALE', 'UNKNOWN'].includes(data.freshness) &&
    ['COMPLETE', 'PARTIAL'].includes(data.coverage) && ['VALIDATED_COMPLETE', 'PARTIAL', 'UNKNOWN'].includes(data.conflictCoverage) &&
    parseScheduleInstant(data.updatedAt) !== null && parseScheduleInstant(data.expiresAt) !== null &&
    parseScheduleInstant(data.updatedAt)! < parseScheduleInstant(data.expiresAt)! &&
    data.window && validZone(data.window.timeZone) && data.window.timeZone === requested.timeZone &&
    validDate(data.window.from) && validDate(data.window.toExclusive) && data.window.from <= requested.from && data.window.toExclusive >= requested.toExclusive &&
    Array.isArray(data.orders) && Array.isArray(data.events) && Array.isArray(data.resources) && (data.conflicts === null || Array.isArray(data.conflicts)));
  requireContract(unique(data.orders.map(o => o.id)) && unique(data.events.map(e => e.id)) && unique(data.resources.map(r => r.id)) &&
    unique((data.conflicts ?? []).map(c => c.id)));
  const orders = new Map(data.orders.map(o => { requireContract(text(o.requestVersion)); return [o.id, o.requestVersion]; }));
  const resources = new Map(data.resources.map(r => [r.id, r.version]));
  for (const e of data.events) {
    requireContract(e.tenantId === auth.tenantId && [e.scheduleId, e.scheduleVersion, e.currentScheduleVersion, e.title, e.status, e.source].every(text) &&
      ['PRODUCTION', 'DELIVERY'].includes(e.type) && access(e.detailAccess) && validScheduleTime(e.when) &&
      e.order && orders.has(e.order.id) && Array.isArray(e.resources) && unique(e.resources.map(r => r.id)) &&
      e.resources.every(r => resources.has(r.id)) && refs(e.evidence) && e.evidence.length && refs(e.historyRefs) && refs(e.dependencies) &&
      e.authority && ['CONFIRMED_SCHEDULE', 'TENTATIVE', 'SIMULATION', 'HISTORICAL', 'UNKNOWN'].includes(e.authority.kind) && refs(e.authority.evidence) &&
      [e.stage, e.materialReadiness].every(optionalText) && (!e.quantity || (numeric(e.quantity.amount) && text(e.quantity.unit))) &&
      (e.type !== 'PRODUCTION' || e.when.kind === 'INTERVAL') &&
      (e.type !== 'DELIVERY' || ['REQUESTED', 'CUSTOMER_AGREED', 'DISPATCH_PLANNED', 'CONFIRMED_DELIVERY', 'ACTUAL_DELIVERY'].includes(e.deliveryMilestone ?? '')));
    if (e.snapshotVersion !== data.snapshotVersion || e.scheduleVersion !== e.currentScheduleVersion || orders.get(e.order.id) !== e.order.requestVersion ||
      e.resources.some(r => resources.get(r.id) !== r.version)) throw new ScheduleVersionError('Schedule/order/resource version conflict');
    requireContract(e.dependencies.every(id => data.events.some(event => event.id === id) && id !== e.id));
    // A requested delivery date cannot arrive disguised as a confirmed schedule or actual fulfilment.
    requireContract(e.deliveryMilestone !== 'REQUESTED' || ['UNKNOWN', 'TENTATIVE'].includes(e.authority.kind));
  }
  const schedules = new Map<string, string>();
  for (const e of data.events) {
    if (schedules.has(e.scheduleId) && schedules.get(e.scheduleId) !== e.scheduleVersion) throw new ScheduleVersionError('Conflicting schedule versions');
    schedules.set(e.scheduleId, e.scheduleVersion);
  }
  for (const r of data.resources) {
    requireContract(text(r.version) && text(r.label) && access(r.detailAccess) && ['VALIDATED_COMPLETE', 'PARTIAL', 'UNKNOWN'].includes(r.coverage) &&
      Array.isArray(r.windows) && unique(r.windows.map(w => w.id)));
    for (const w of r.windows) requireContract(validScheduleTime({ kind: 'INTERVAL', start: w.start, end: w.end }) &&
      ['OCCUPIED', 'FREE', 'MAINTENANCE', 'DOWNTIME', 'UNKNOWN'].includes(w.state) && refs(w.evidence));
    if (r.utilization) { const u = r.utilization; requireContract([u.percentage, u.numerator, u.denominator].every(numeric) &&
      /[1-9]/.test(u.denominator) && text(u.unit) && text(u.basis) && refs(u.evidence) && validScheduleTime({ kind: 'INTERVAL', start: u.start, end: u.end })); }
  }
  for (const c of data.conflicts ?? []) requireContract(access(c.detailAccess) && validScheduleTime(c.when) &&
    refs(c.eventIds) && c.eventIds.every(id => data.events.some(e => e.id === id)) && refs(c.resourceIds) && c.resourceIds.every(id => resources.has(id)) &&
    [c.explanation, c.source, c.sourceVersion].every(text) && [c.severity, c.uncertainty].every(optionalText) && refs(c.evidence) && c.evidence.length);
  return data;
}
export function scheduleFresh(data: ScheduleSnapshot, now: number): boolean {
  return data.sourceVerified && data.evidence.length > 0 && data.freshness === 'CURRENT' && data.snapshotVersion === data.currentVersion &&
    parseScheduleInstant(data.updatedAt)! <= now && parseScheduleInstant(data.expiresAt)! > now;
}
