import { afterEach, describe, expect, it, vi } from 'vitest';
import { dbOrderDetailSource, dbOrderQueueSource, dbScheduleSource } from './dbSource';

const auth = { tenantId: 'tenant_demo_01', actorId: 'user_owner_01' };

const mockQueueDto = {
  schema_version: 'orders-demo-v1' as const,
  tenant_id: 'tenant_demo_01',
  actor_id: 'user_owner_01',
  read_authorized: true as const,
  integration_mode: 'SYNTHETIC' as const,
  evidence_tier: 'DEMO-ONLY' as const,
  source: 'persisted://postgresql/p4_orders',
  source_at: '2026-10-24T08:00:00Z',
  valid_until: '2026-11-24T08:00:00Z',
  coverage: 'partial' as const,
  orders: [
    {
      order_id: 'ord_normal_01',
      commitment_id: 'com_normal_01',
      customer_display_name: 'Classic Burger Demo Customer',
      requested_items: [{ sku: 'BURGER_CLASSIC', quantity: '50', unit: 'pcs' }],
      requested_delivery_at: '2026-10-27T08:00:00Z',
      received_at: '2026-10-23T00:00:00Z',
      lifecycle_status: 'UNKNOWN' as const,
      source_channel: 'SYNTHETIC' as const,
      evidence_refs: ['synthetic://ord_normal_01'],
    },
  ],
};

const mockDetailDto = {
  tenant_id: 'tenant_demo_01',
  actor_id: 'user_owner_01',
  integration_mode: 'SYNTHETIC' as const,
  evidence_tier: 'DEMO-ONLY' as const,
  source_at: '2026-10-24T08:00:00Z',
  source: 'persisted://postgresql/p4_orders',
  order: mockQueueDto.orders[0],
  related_commitment: {
    commitment_id: 'com_normal_01',
    order_id: 'ord_normal_01',
    tenant_id: 'tenant_demo_01',
    customer_id: 'customer_demo',
    version: 1,
    agreement_state: 'CONFIRMED',
    risk_state: 'NORMAL',
    recovery_state: 'NONE',
    evidence_refs: ['synthetic://com_normal_01'],
  },
  assessment_availability: 'UNAVAILABLE' as const,
  assessment_reason: 'No persisted P2 assessment.',
  assessments: [],
};

const mockCalendarDto = {
  ...mockQueueDto,
  valid_until: '2026-11-24T08:00:00Z',
  window: {
    from_date: '2026-10-24',
    to_exclusive: '2026-10-31',
    time_zone: 'Asia/Kuala_Lumpur',
  },
};

describe('persisted database sources', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('loads and maps orders from /v1/orders', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(mockQueueDto), { status: 200 })));
    const controller = new AbortController();
    const snapshot = await dbOrderQueueSource.load(auth, controller.signal);
    expect(snapshot.items).toHaveLength(1);
    expect(snapshot.items[0].id).toBe('ord_normal_01');
    expect(snapshot.items[0].customer).toBe('Classic Burger Demo Customer');
  });

  it('loads and maps order detail from /v1/orders/:id', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(mockDetailDto), { status: 200 })));
    const controller = new AbortController();
    const detail = await dbOrderDetailSource.load('ord_normal_01', auth, controller.signal);
    expect(detail).not.toBeNull();
    expect(detail!.id).toBe('ord_normal_01');
    expect(detail!.commitmentId).toBe('com_normal_01');
    expect(detail!.assessment?.status).toBe('UNKNOWN');
  });

  it('loads and maps calendar schedule from /v1/orders/planning/calendar', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(mockCalendarDto), { status: 200 })));
    const controller = new AbortController();
    const window = { from: '2026-10-24', toExclusive: '2026-10-31', timeZone: 'Asia/Kuala_Lumpur' };
    const schedule = await dbScheduleSource.load(window, auth, controller.signal);
    expect(schedule.events).toHaveLength(1);
    expect(schedule.events[0].id).toBe('requested:ord_normal_01');
    expect(schedule.events[0].deliveryMilestone).toBe('REQUESTED');
  });
});
