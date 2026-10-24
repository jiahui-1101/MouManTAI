import type { RequestAuthHeaders } from '../../shared/api';
import type { EvidenceTier, IntegrationMode } from '../../shared/ui';

/** Feature-local presentation models; no scheduling wire API is assumed. */
export type CalendarView = 'DAY' | 'WEEK' | 'MONTH';
export type ScheduleTime = { kind: 'INTERVAL'; start: string; end: string } |
  { kind: 'INSTANT'; at: string } | { kind: 'DATE'; date: string };
export interface CalendarWindow { from: string; toExclusive: string; timeZone: string }
export interface ScheduleAuthority {
  kind: 'CONFIRMED_SCHEDULE' | 'TENTATIVE' | 'SIMULATION' | 'HISTORICAL' | 'UNKNOWN';
  evidence: string[];
}
export interface ScheduleEvent {
  id: string; tenantId: string; snapshotVersion: string;
  scheduleId: string; scheduleVersion: string; currentScheduleVersion: string;
  type: 'PRODUCTION' | 'DELIVERY'; title: string; status: string; authority: ScheduleAuthority;
  detailAccess: 'FULL' | 'REDACTED'; when: ScheduleTime;
  order: { id: string; requestVersion: string };
  resources: { id: string; version: string }[];
  stage?: string; quantity?: { amount: string; unit: string }; materialReadiness?: string;
  deliveryMilestone?: 'REQUESTED' | 'CUSTOMER_AGREED' | 'DISPATCH_PLANNED' | 'CONFIRMED_DELIVERY' | 'ACTUAL_DELIVERY';
  dependencies: string[]; evidence: string[]; source: string; historyRefs: string[];
}
export interface SchedulingConflict {
  id: string; detailAccess: 'FULL' | 'REDACTED'; when: ScheduleTime;
  eventIds: string[]; resourceIds: string[]; severity?: string; explanation: string; uncertainty?: string;
  source: string; sourceVersion: string; evidence: string[];
}
export interface ResourceSchedule {
  id: string; version: string; label: string; detailAccess: 'FULL' | 'REDACTED';
  coverage: 'VALIDATED_COMPLETE' | 'PARTIAL' | 'UNKNOWN';
  windows: { id: string; start: string; end: string; state: 'OCCUPIED' | 'FREE' | 'MAINTENANCE' | 'DOWNTIME' | 'UNKNOWN'; evidence: string[] }[];
  utilization?: { percentage: string; numerator: string; denominator: string; unit: string; basis: string;
    start: string; end: string; evidence: string[] };
}
export interface ScheduleSnapshot {
  tenantId: string; actorId: string; readAuthorized: boolean; source: string; sourceVerified: boolean;
  evidenceTier: EvidenceTier; integrationMode: IntegrationMode; evidence: string[];
  snapshotId: string; snapshotVersion: string; currentVersion: string;
  updatedAt: string; expiresAt: string; freshness: 'CURRENT' | 'STALE' | 'UNKNOWN';
  window: CalendarWindow; coverage: 'COMPLETE' | 'PARTIAL';
  orders: { id: string; requestVersion: string }[];
  events: ScheduleEvent[]; resources: ResourceSchedule[];
  conflicts: SchedulingConflict[] | null; conflictCoverage: 'VALIDATED_COMPLETE' | 'PARTIAL' | 'UNKNOWN';
}
export interface ScheduleSource {
  cacheKey: string;
  load(window: CalendarWindow, auth: RequestAuthHeaders, signal: AbortSignal): Promise<ScheduleSnapshot>;
}
export interface CalendarFilters { type: string; resource: string; search: string; status: string; authority: string; conflictsOnly: boolean }
