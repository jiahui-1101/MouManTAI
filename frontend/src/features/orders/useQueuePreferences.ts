import { useEffect, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import type { RequestAuthHeaders } from '../../shared/api';
import { validDate } from './calendarDates';
import { initialFilters } from './queue';
import type { QueueFilters, StatusView } from './types';

const statuses: readonly StatusView[] = ['PENDING_ACCEPTANCE', 'ACCEPTED', 'REJECTED', 'OTHER', 'ALL'];
const analyses = ['QUEUE', 'FCFS', 'PROFIT', 'EXPIRY'];
const sorts = ['FCFS', 'DEADLINE'];
const feasibilities = ['', 'FEASIBLE', 'CONDITIONAL', 'INFEASIBLE', 'UNKNOWN'];
interface Preferences { filters: QueueFilters; analysis: string }
interface Snapshot extends Preferences { id: string }
interface Session { snapshots: Map<string, Snapshot>; last?: Snapshot }

// AuthProvider memoizes this object until tenant OR actor changes. Object identity
// defines an epoch, including A -> B -> A while Queue is unmounted. Never key this
// by tenant/actor strings: doing so would revive revoked history preferences.
const sessions = new WeakMap<RequestAuthHeaders, Session>();
function sessionFor(auth: RequestAuthHeaders): Session {
  let session = sessions.get(auth);
  if (!session) { session = { snapshots: new Map() }; sessions.set(auth, session); }
  return session;
}
const defaults = (): Preferences => ({ filters: { ...initialFilters }, analysis: 'QUEUE' });
// getRandomValues also works for local HTTP demos where randomUUID is unavailable.
const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
const snapshot = (value: Preferences): Snapshot => ({ ...value, id: newId() });
function single(params: URLSearchParams, key: string): string {
  const values = params.getAll(key);
  return values.length === 1 ? values[0] : '';
}
function read(search: string, session: Session): Snapshot {
  const params = new URLSearchParams(search);
  const id = single(params, 'oqState');
  // A foreign/expired/duplicated marker invalidates the WHOLE URL, even its safe
  // fields. Old browser history must not restore another identity's preferences.
  if (params.has('oqState') && !session.snapshots.has(id)) return snapshot(defaults());
  const saved = session.snapshots.get(id);
  const hasQueueParams = ['oqStatus', 'oqFrom', 'oqTo', 'oqAnalysis', 'oqSort', 'oqDueFrom', 'oqDueTo', 'oqFeasibility'].some(key => params.has(key));
  if (!saved && !hasQueueParams) return session.last ?? snapshot(defaults());
  const status = single(params, 'oqStatus');
  const analysis = single(params, 'oqAnalysis');
  const from = single(params, 'oqFrom'), to = single(params, 'oqTo');
  const sort = single(params, 'oqSort'), feasibility = single(params, 'oqFeasibility');
  const dueFrom = single(params, 'oqDueFrom'), dueTo = single(params, 'oqDueTo');
  return {
    id: saved?.id ?? newId(),
    filters: {
      ...(saved?.filters ?? initialFilters),
      status: statuses.includes(status as StatusView) ? status as StatusView : initialFilters.status,
      from: validDate(from) ? from : '', to: validDate(to) ? to : '',
      sort: sorts.includes(sort) ? sort as QueueFilters['sort'] : 'FCFS',
      deadlineFrom: validDate(dueFrom) ? dueFrom : '', deadlineTo: validDate(dueTo) ? dueTo : '',
      feasibility: feasibilities.includes(feasibility) ? feasibility : '',
    },
    analysis: analyses.includes(analysis) ? analysis : 'QUEUE',
  };
}
function searchFor(value: Snapshot): string {
  // Only this allowlist is safe to serialize. Free text and source-derived option
  // labels may contain customer/product data; keep them solely in session memory.
  // Unknown URL parameters have no established safe contract here and are dropped.
  const params = new URLSearchParams();
  params.set('oqState', value.id);
  if (value.filters.status !== initialFilters.status) params.set('oqStatus', value.filters.status);
  if (value.filters.from) params.set('oqFrom', value.filters.from);
  if (value.filters.to) params.set('oqTo', value.filters.to);
  if (value.analysis !== 'QUEUE') params.set('oqAnalysis', value.analysis);
  if (value.filters.sort !== 'FCFS') params.set('oqSort', value.filters.sort);
  if (value.filters.deadlineFrom) params.set('oqDueFrom', value.filters.deadlineFrom);
  if (value.filters.deadlineTo) params.set('oqDueTo', value.filters.deadlineTo);
  if (value.filters.feasibility) params.set('oqFeasibility', value.filters.feasibility);
  return `?${params}`;
}

/** Router entries identify immutable, identity-scoped preference snapshots, never API data. */
export function useQueuePreferences(auth: RequestAuthHeaders) {
  const location = useLocation();
  const navigate = useNavigate();
  const session = sessionFor(auth);
  const pendingRoute = location.pathname.replace(/\/+$/, '') === '/orders/pending';
  const value = useMemo(() => {
    const saved = read(location.search, session);
    // Entering Pending selects that existing filter without rewriting a previous
    // visit's immutable snapshot or losing its other preferences and Analysis.
    return pendingRoute && saved.filters.status !== 'PENDING_ACCEPTANCE'
      ? snapshot({ filters: { ...saved.filters, status: 'PENDING_ACCEPTANCE' }, analysis: saved.analysis })
      : saved;
  }, [location.search, session, pendingRoute]);
  const search = searchFor(value);
  useEffect(() => {
    session.snapshots.set(value.id, value);
    session.last = value;
    if (location.search !== search) {
      void navigate({ pathname: location.pathname, search, hash: location.hash }, { replace: true });
    }
  }, [session, value, search, location.search, location.pathname, location.hash, navigate]);

  function save(next: Preferences) {
    const saved = snapshot(next);
    session.snapshots.set(saved.id, saved);
    session.last = saved;
    // Edits replace the current Queue visit. Links still push normal navigation
    // entries, so Back/Forward restores each visit without one entry per keystroke.
    const pathname = pendingRoute && next.filters.status !== 'PENDING_ACCEPTANCE' ? '/orders' : location.pathname;
    void navigate({ pathname, search: searchFor(saved), hash: location.hash }, { replace: true });
  }
  return {
    filters: value.filters, analysis: value.analysis,
    resetFilters: () => save({ filters: { ...initialFilters }, analysis: 'QUEUE' }),
    setFilters: (update: QueueFilters | ((current: QueueFilters) => QueueFilters)) =>
      save({ filters: typeof update === 'function' ? update(value.filters) : update, analysis: value.analysis }),
    setAnalysis: (analysis: string) => save({ filters: value.filters, analysis: analyses.includes(analysis) ? analysis : 'QUEUE' }),
  };
}
