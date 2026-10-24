import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, useAuth } from '../../shared/auth';
import { ApiError } from '../../shared/api';
import { CalendarSchedulingPage } from './CalendarSchedulingPage';
import { calendarFixture, calendarTestNow } from './calendarTest.fixtures';
import type { ScheduleSnapshot, ScheduleSource } from './calendarTypes';

const sourceFor = (data = calendarFixture()): ScheduleSource => ({ cacheKey: 'test-only-calendar', load: vi.fn().mockResolvedValue(data) });
function ContextControls() { const auth = useAuth(); return <>
  <button onClick={() => auth.setTenantId('other-tenant')}>Switch test tenant</button>
  <button onClick={() => auth.setActorId('user_staff_01')}>Switch test actor</button>
  <button onClick={() => auth.setTenantId('test-tenant')}>Restore test tenant</button>
  <button onClick={() => auth.setActorId('user_owner_01')}>Restore test actor</button></>; }
function setup(source?: ScheduleSource, initialDate = '2026-10-24', timeZone = 'Asia/Kuala_Lumpur') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><AuthProvider initialTenantId="test-tenant" initialActorId="user_owner_01">
    <MemoryRouter><ContextControls /><CalendarSchedulingPage source={source} initialDate={initialDate} timeZone={timeZone} /></MemoryRouter></AuthProvider></QueryClientProvider>);
}
async function loaded(source = sourceFor()) {
  setup(source); await screen.findByRole('group', { name: 'Schedule filters' });
  fireEvent.click(screen.getByRole('button', { name: 'Day' }));
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  return source;
}
const inspect = (title = 'Synthetic overnight mixing') => screen.getByRole('button', { name: `Inspect ${title} on 2026-10-24` });
beforeEach(() => { vi.spyOn(Date, 'now').mockReturnValue(calendarTestNow); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('Calendar navigation and source states', () => {
  it('defaults to unavailable without speculative HTTP, jobs or free capacity', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); setup();
    expect(await screen.findByRole('heading', { name: 'Scheduling API unavailable' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Resource availability and conflicts Unknown' })).toBeInTheDocument();
    expect(screen.getAllByText('Schedule unknown')).toHaveLength(35); expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
    expect(screen.getByText('TARGET')).toBeInTheDocument();
  });
  it('supports month/year rollover, previous/next/today and leap-day selection without source', async () => {
    setup(undefined, '2026-12-31'); await screen.findByRole('heading', { name: 'Scheduling API unavailable' });
    fireEvent.click(screen.getByRole('button', { name: 'Next period' })); expect(screen.getByLabelText('Chosen date')).toHaveValue('2027-01-31');
    fireEvent.click(screen.getByRole('button', { name: 'Previous period' })); expect(screen.getByLabelText('Chosen date')).toHaveValue('2026-12-31');
    fireEvent.change(screen.getByLabelText('Chosen date'), { target: { value: '2024-02-29' } });
    fireEvent.click(screen.getByRole('button', { name: 'Day' })); expect(screen.getByRole('list', { name: 'day calendar dates' }).children).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Next period' })); expect(screen.getByLabelText('Chosen date')).toHaveValue('2024-03-01');
    fireEvent.click(screen.getByRole('button', { name: 'Today' })); expect(screen.getByLabelText('Chosen date')).toHaveValue('2026-10-24');
    await screen.findByRole('heading', { name: 'Scheduling API unavailable' });
  });
  it('shows seven dates in week view and configured Sunday/Monday boundaries', async () => {
    setup(); await screen.findByRole('heading', { name: 'Scheduling API unavailable' });
    fireEvent.click(screen.getByRole('button', { name: 'Week' }));
    expect(screen.getByRole('list', { name: 'week calendar dates' }).children).toHaveLength(7);
    expect(screen.getByRole('button', { name: 'Open day 2026-10-19' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Week begins'), { target: { value: '0' } });
    expect(screen.getByRole('button', { name: 'Open day 2026-10-18' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next period' })); expect(screen.getByLabelText('Chosen date')).toHaveValue('2026-10-31');
    await screen.findByRole('heading', { name: 'Scheduling API unavailable' });
  });
  it('can open a day from the month without making calendar cells authoritative', async () => {
    setup(); fireEvent.click(screen.getByRole('button', { name: 'Open day 2026-10-20' }));
    expect(screen.getByLabelText('Chosen date')).toHaveValue('2026-10-20');
    expect(screen.getByRole('list', { name: 'day calendar dates' }).children).toHaveLength(1);
    await screen.findByRole('heading', { name: 'Scheduling API unavailable' });
  });
  it('cancels a loading read on unmount', () => {
    let signal!: AbortSignal; const view = setup({ cacheKey: 'pending', load: (_, __, s) => { signal = s; return new Promise(() => {}); } });
    expect(screen.getByRole('status')).toHaveTextContent('Loading calendar'); view.unmount(); expect(signal.aborted).toBe(true);
  });
  it('rejects invalid zone configuration without requesting data', () => {
    const source = sourceFor(); setup(source, '2026-10-24', 'Invalid/Zone');
    expect(screen.getByRole('heading', { name: 'Unsupported calendar time zone' })).toBeInTheDocument(); expect(source.load).not.toHaveBeenCalled();
  });
  it('keeps empty source separate from unavailable and never calls empty periods free', async () => {
    const d = calendarFixture(); d.events = []; d.conflicts = []; d.resources = []; const source = sourceFor(d); setup(source);
    expect(await screen.findByRole('heading', { name: 'No loaded schedule events' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Resource schedule unavailable' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Scheduling API unavailable' })).not.toBeInTheDocument();
  });
  it.each([401, 403, 409, 422, 500])('handles HTTP %s safely without raw response details', async status => {
    const source = sourceFor(); vi.mocked(source.load).mockRejectedValue(new ApiError(status, 'TEST', 'secret-server-error')); setup(source);
    await screen.findByRole('alert'); expect(document.body).not.toHaveTextContent('secret-server-error');
    expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
  });
  it('uses explicit safe read retry with no automatic retry', async () => {
    const source = sourceFor(); vi.mocked(source.load).mockRejectedValueOnce(new TypeError('Failed to fetch')); setup(source);
    expect(await screen.findByRole('heading', { name: 'Connection problem' })).toBeInTheDocument(); expect(source.load).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' })); await screen.findByRole('group', { name: 'Schedule filters' });
    expect(source.load).toHaveBeenCalledTimes(2);
  });
  it.each(['STALE', 'UNKNOWN'] as const)('withholds %s snapshots', async freshness => {
    const d = calendarFixture(); d.freshness = freshness; setup(sourceFor(d));
    expect(await screen.findByRole('heading', { name: 'Current schedule unavailable' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
  });
  it('withholds snapshot version conflict and refreshes with shared banner', async () => {
    const d = calendarFixture(); d.currentVersion = '8'; const source = sourceFor(d); setup(source);
    await screen.findByRole('heading', { name: 'This record has changed' });
    expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh latest version' })); await screen.findByRole('heading', { name: 'This record has changed' });
    expect(source.load).toHaveBeenCalledTimes(2);
  });
  it('expires an idle schedule, including an open event inspector', async () => {
    const d = calendarFixture(); d.expiresAt = new Date(calendarTestNow + 400).toISOString(); await loaded(sourceFor(d));
    fireEvent.click(inspect()); expect(screen.getByRole('region', { name: 'Calendar event details' })).toBeInTheDocument();
    vi.spyOn(Date, 'now').mockReturnValue(calendarTestNow + 401);
    await screen.findByRole('heading', { name: 'Current schedule unavailable' });
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
  });
});

describe('Sourced events, filters, resource evidence and read-only inspector', () => {
  it('distinguishes production, requested/agreed delivery, tentative, simulation and history', async () => {
    const source = sourceFor(); const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); setup(source);
    await screen.findByRole('group', { name: 'Schedule filters' });
    expect(screen.getAllByText('Requested date · not promised').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Tentative proposal/).length).toBeGreaterThan(0); expect(screen.getAllByText(/Simulation \/ forecast/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Historical work/).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Inspect Synthetic overnight mixing on 2026-10-23' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Inspect Synthetic overnight mixing on 2026-10-24' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Inspect Synthetic overnight mixing on 2026-10-25/ })).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('opens an accessible nonmodal detail panel, preserves source times, closes on Escape and returns focus', async () => {
    const d = calendarFixture(); const before = structuredClone(d); const source = await loaded(sourceFor(d)); const button = inspect();
    button.focus(); fireEvent.click(button); const panel = screen.getByRole('region', { name: 'Calendar event details' });
    expect(within(panel).getByRole('button', { name: 'Close event details' })).toHaveFocus();
    expect(within(panel).getByRole('link', { name: 'order/one' })).toHaveAttribute('href', '/orders/order%2Fone');
    expect(panel).toHaveTextContent('2026-10-23T15:00:00Z'); expect(panel).toHaveTextContent('version 3'); expect(panel).toHaveTextContent('12.5 kg');
    expect(panel).toHaveTextContent('Rescheduling submission and impact preview are unavailable');
    fireEvent.keyDown(panel, { key: 'Escape' }); expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
    expect(button).toHaveFocus(); expect(d).toEqual(before); expect(source.load).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('button', { name: /accept|reserve|reschedule|submit|execute|save/i })).not.toBeInTheDocument();
  });
  it('supports production/delivery, resource, order, status, authority and conflict filters with reset', async () => {
    await loaded();
    fireEvent.change(screen.getByLabelText('Event type'), { target: { value: 'DELIVERY' } }); expect(inspect('Synthetic requested delivery')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Inspect Synthetic overnight/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    fireEvent.change(screen.getByLabelText('Resource / machine'), { target: { value: 'machine-A' } }); expect(inspect()).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Inspect Synthetic requested/ })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Source status'), { target: { value: 'PROPOSED' } }); expect(inspect('Synthetic tentative packing')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Order ID or keyword'), { target: { value: 'absent' } }); expect(screen.getByRole('heading', { name: 'No events match the filters' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    fireEvent.change(screen.getByLabelText('Schedule authority'), { target: { value: 'Tentative proposal' } }); expect(inspect('Synthetic tentative packing')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' })); fireEvent.click(screen.getByLabelText('Source conflicts only'));
    expect(inspect()).toBeInTheDocument(); expect(inspect('Synthetic tentative packing')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Inspect Synthetic requested/ })).not.toBeInTheDocument();
  });
  it('hides redacted event/resource identities from labels, filters and inspector', async () => {
    await loaded(); expect(document.body).not.toHaveTextContent('secret-');
    fireEvent.click(inspect('Redacted event')); const panel = screen.getByRole('region', { name: 'Calendar event details' });
    expect(panel).toHaveTextContent('Event details are Redacted'); expect(within(panel).queryByRole('link')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('secret-');
  });
  it('shows source occupancy/maintenance and fully evidenced utilization only', async () => {
    await loaded(); const resources = screen.getByRole('region', { name: 'Machine and resource occupancy' });
    expect(resources).toHaveTextContent('Source-reported utilization: 50%'); expect(resources).toHaveTextContent('60 / 120 minutes');
    for (const state of ['OCCUPIED', 'FREE', 'MAINTENANCE']) expect(within(resources).getByText(state, { exact: true })).toBeInTheDocument();
  });
  it('does not treat missing occupancy/capacity evidence as a free slot', async () => {
    const d = calendarFixture(); d.resources[0].coverage = 'PARTIAL'; d.resources[0].windows[1].evidence = [];
    await loaded(sourceFor(d)); const resources = screen.getByRole('region', { name: 'Machine and resource occupancy' });
    expect(resources).toHaveTextContent('Utilization: Unknown'); expect(within(resources).queryByText('FREE', { exact: true })).not.toBeInTheDocument();
    expect(within(resources).getByText('UNKNOWN', { exact: true })).toBeInTheDocument();
  });
  it('uses sourced conflict explanations, versions, severity and uncertainty only', async () => {
    await loaded(); const conflicts = screen.getByRole('region', { name: 'Source scheduling conflicts' });
    expect(conflicts).toHaveTextContent('Source-reported machine overlap'); expect(conflicts).toHaveTextContent('Severity: HIGH');
    expect(conflicts).toHaveTextContent('version 9'); expect(conflicts).toHaveTextContent('Source supplier window incomplete');
  });
  it('keeps partial coverage and missing conflict findings explicitly unknown', async () => {
    const d = calendarFixture(); d.coverage = 'PARTIAL'; d.conflicts = null; d.conflictCoverage = 'UNKNOWN'; await loaded(sourceFor(d));
    expect(screen.getByText(/Partial schedule. Counts and filters/)).toBeInTheDocument();
    expect(screen.getByText(/Validated conflict coverage unavailable/)).toBeInTheDocument();
    expect(screen.getByText('No loaded conflict finding · conflict status Unknown')).toBeInTheDocument();
  });
  it('hides redacted conflict payloads even when supplied in the source', async () => {
    const d = calendarFixture(); d.conflicts![0].detailAccess = 'REDACTED'; d.conflicts![0].explanation = 'secret-conflict';
    await loaded(sourceFor(d)); expect(screen.getByRole('heading', { name: 'Redacted conflict' })).toBeInTheDocument(); expect(document.body).not.toHaveTextContent('secret-');
  });
});

describe('Refresh and cross-session privacy', () => {
  it.each([new ApiError(403, 'FORBIDDEN', 'private'), new TypeError('Failed to fetch')])('hides all cached data during refresh and after failure', async error => {
    const source = await loaded(); fireEvent.click(inspect()); let reject!: (e: Error) => void;
    vi.mocked(source.load).mockImplementationOnce(() => new Promise((_, failure) => { reject = failure; }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh calendar' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument());
    expect(document.body).not.toHaveTextContent('Synthetic overnight mixing'); await act(async () => reject(error));
    await screen.findByRole('alert'); expect(document.body).not.toHaveTextContent('Synthetic overnight mixing');
  });
  it.each(['Switch test tenant', 'Switch test actor'])('rejects wrong-scoped cached responses after %s', async label => {
    const source = await loaded(); fireEvent.click(inspect()); fireEvent.click(screen.getByRole('button', { name: label }));
    await screen.findByRole('alert'); expect(document.body).not.toHaveTextContent('Synthetic overnight mixing');
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument(); expect(source.load).toHaveBeenCalledTimes(3);
  });
  it('aborts and ignores a late old-tenant read', async () => {
    let resolve!: (d: ScheduleSnapshot) => void; let signal!: AbortSignal;
    const source: ScheduleSource = { cacheKey: 'late-calendar', load: vi.fn().mockImplementationOnce((_, __, s) => {
      signal = s; return new Promise(done => { resolve = done; }); }).mockRejectedValue(new ApiError(403, 'FORBIDDEN', 'private')) };
    setup(source); fireEvent.click(screen.getByRole('button', { name: 'Switch test tenant' })); await screen.findByRole('alert');
    expect(signal.aborted).toBe(true); await act(async () => resolve(calendarFixture())); expect(document.body).not.toHaveTextContent('Synthetic overnight mixing');
  });
});

describe('Identity-scoped Calendar display preferences', () => {
  const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
  const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
  async function ready() {
    await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh calendar' })).toBeEnabled());
    await screen.findByRole('group', { name: 'Schedule filters' });
  }
  async function chooseFilters() {
    change('Week begins', '0'); await ready();
    for (const [label, value] of [['Event type', 'PRODUCTION'], ['Resource / machine', 'machine-A'],
      ['Order ID or keyword', 'overnight'], ['Source status', 'PLANNED'], ['Schedule authority', 'Confirmed schedule · source evidenced']]) change(label, value);
    fireEvent.click(screen.getByLabelText('Source conflicts only'));
  }
  function expectFilters() {
    for (const [label, value] of [['Event type', 'PRODUCTION'], ['Resource / machine', 'machine-A'],
      ['Order ID or keyword', 'overnight'], ['Source status', 'PLANNED'], ['Schedule authority', 'Confirmed schedule · source evidenced'], ['Week begins', '0']])
      expect(screen.getByLabelText(label)).toHaveValue(value);
    expect(screen.getByLabelText('Source conflicts only')).toBeChecked();
  }
  function expectDefaults() {
    for (const label of ['Event type', 'Resource / machine', 'Order ID or keyword', 'Source status', 'Schedule authority'])
      expect(screen.getByLabelText(label)).toHaveValue('');
    expect(screen.getByLabelText('Source conflicts only')).not.toBeChecked();
    expect(screen.getByLabelText('Week begins')).toHaveValue('1');
  }
  it.each(['Month', 'Week', 'Day'])('retains all filters and week start through Previous/Next in %s view', async view => {
    setup(sourceFor()); await ready(); await chooseFilters(); click(view); await ready();
    const date = (screen.getByLabelText('Chosen date') as HTMLInputElement).value;
    fireEvent.click(inspect());
    click('Next period'); await ready(); expectFilters();
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
    click('Previous period'); await ready(); expectFilters();
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Chosen date')).toHaveValue(date);
  });
  it('retains filters and Sunday week boundaries through Month/Week/Day view changes', async () => {
    setup(sourceFor()); await ready(); await chooseFilters();
    for (const view of ['Week', 'Day', 'Month']) {
      click(view); await ready(); expectFilters();
      expect(screen.getByRole('button', { name: view })).toHaveAttribute('aria-pressed', 'true');
      if (view === 'Week') expect(screen.getByRole('button', { name: 'Open day 2026-10-18' })).toBeInTheDocument();
    }
  });
  it('retains filters on Month-to-Day drill-down while discarding the selected inspector', async () => {
    setup(sourceFor()); await ready(); await chooseFilters(); fireEvent.click(inspect());
    expect(screen.getByRole('region', { name: 'Calendar event details' })).toBeInTheDocument();
    click('Open day 2026-10-24'); await ready(); expectFilters();
    expect(screen.getByRole('list', { name: 'day calendar dates' }).children).toHaveLength(1);
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
    expect(inspect()).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Inspect Synthetic requested delivery/ })).not.toBeInTheDocument();
  });
  it('preserves filters through a pending refresh and a new snapshot, without reopening old details or writing storage', async () => {
    const source = sourceFor(); setup(source); await ready(); await chooseFilters(); fireEvent.click(inspect());
    const local = vi.spyOn(Storage.prototype, 'setItem');
    let resolve!: (snapshot: ScheduleSnapshot) => void;
    vi.mocked(source.load).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    click('Refresh calendar');
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Schedule filters' })).not.toBeInTheDocument());
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('Synthetic machine A');
    const updated = calendarFixture(); updated.snapshotId = 'new-snapshot'; updated.snapshotVersion = updated.currentVersion = '8';
    updated.updatedAt = '2026-10-24T02:30:00Z'; updated.events.forEach(e => { e.snapshotVersion = '8'; });
    await act(async () => resolve(updated)); await ready(); expectFilters();
    expect(inspect()).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
    expect(local).not.toHaveBeenCalled();
  });
  it.each(['tenant', 'actor'])('resets filters and week start on %s changes and does not revive them when switching back', async identity => {
    const source: ScheduleSource = { cacheKey: 'scoped-test-only', load: vi.fn<ScheduleSource['load']>(async (_, auth) => {
      const d = calendarFixture(); d.tenantId = auth.tenantId; d.actorId = auth.actorId;
      d.events.forEach(e => { e.tenantId = auth.tenantId; }); return d;
    }) };
    setup(source); await ready(); await chooseFilters(); fireEvent.click(inspect());
    click(`Switch test ${identity}`); await ready(); expectDefaults();
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
    click(`Restore test ${identity}`); await ready(); expectDefaults();
  });
  it('resets preferences when the provider/page session is torn down and mounted again', async () => {
    const first = setup(sourceFor()); await ready(); await chooseFilters(); fireEvent.click(inspect()); first.unmount();
    setup(sourceFor()); await ready(); expectDefaults();
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
  });
  it('retains preferences across a failed refresh and safe read recovery without restoring old details', async () => {
    const source = sourceFor(); setup(source); await ready(); await chooseFilters(); fireEvent.click(inspect());
    vi.mocked(source.load).mockRejectedValueOnce(new ApiError(403, 'FORBIDDEN', 'private'));
    click('Refresh calendar'); await screen.findByRole('alert');
    expect(screen.queryByRole('group', { name: 'Schedule filters' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('Synthetic machine A');
    click('Refresh calendar'); await ready(); expectFilters();
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
  });
  it('keeps missing option preferences visibly unavailable without retaining old source labels, and restores them only from a fresh source', async () => {
    const source = sourceFor(); setup(source); await ready(); await chooseFilters(); fireEvent.click(inspect());
    const empty = calendarFixture(); empty.events = []; empty.resources = []; empty.conflicts = [];
    vi.mocked(source.load).mockResolvedValueOnce(empty); click('Refresh calendar'); await ready();
    for (const label of ['Event type', 'Resource / machine', 'Source status', 'Schedule authority']) {
      const select = screen.getByLabelText(label);
      expect(select).toHaveValue('__unavailable__');
      expect(within(select).getByRole('option', { name: 'Saved filter unavailable in this snapshot' })).toBeDisabled();
    }
    expect(screen.getByLabelText('Order ID or keyword')).toHaveValue('overnight');
    expect(screen.getByLabelText('Source conflicts only')).toBeChecked();
    expect(document.body).not.toHaveTextContent('Synthetic machine A');
    expect(screen.queryByRole('option', { name: 'PLANNED' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
    click('Refresh calendar'); await ready(); expectFilters();
    click('Reset filters');
    for (const label of ['Event type', 'Resource / machine', 'Order ID or keyword', 'Source status', 'Schedule authority'])
      expect(screen.getByLabelText(label)).toHaveValue('');
    expect(screen.getByLabelText('Source conflicts only')).not.toBeChecked();
    expect(screen.getByLabelText('Week begins')).toHaveValue('0');
  });
  it('revalidates a saved resource against fresh authorization without exposing a newly redacted resource or old inspector', async () => {
    const source = sourceFor(); setup(source); await ready(); await chooseFilters(); fireEvent.click(inspect());
    const restricted = calendarFixture(); restricted.resources[0].detailAccess = 'REDACTED';
    vi.mocked(source.load).mockResolvedValueOnce(restricted); click('Refresh calendar'); await ready();
    const resources = screen.getByLabelText('Resource / machine');
    expect(resources).toHaveValue('__unavailable__');
    expect(resources.querySelector('option[value="machine-A"]')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('Synthetic machine A');
    expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Order ID or keyword')).toHaveValue('overnight');
    expect(screen.getByLabelText('Source conflicts only')).toBeChecked();
    change('Resource / machine', '');
    expect(screen.getByLabelText('Resource / machine')).toHaveValue('');
    expect(inspect()).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Calendar event details' })).not.toBeInTheDocument();
  });
});
