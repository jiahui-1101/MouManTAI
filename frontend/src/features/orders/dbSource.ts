import { apiRequest, authHeaders } from '../../shared/api';
import type { OrderQueueSource } from './api';
import type { OrderDetailSource } from './detailApi';
import type { CalendarWindow, ScheduleSnapshot, ScheduleSource } from './calendarTypes';
import {
  type DemoCalendarDto,
  type DemoDetailDto,
  type DemoQueueDto,
  mapDemoCalendar,
  mapDemoDetail,
  mapDemoQueue,
} from './demoSource';

export const ordersPersistedEnabled = () =>
  import.meta.env.MODE !== 'test' || import.meta.env.VITE_ORDERS_PERSISTED === '1';

export const dbOrderQueueSource: OrderQueueSource = {
  cacheKey: 'persisted-orders-db-v1',
  async load(auth, signal) {
    const dto = await apiRequest<DemoQueueDto>('/v1/orders', {
      headers: authHeaders(auth),
      signal,
    });
    return mapDemoQueue(dto, auth);
  },
};

export const dbOrderDetailSource: OrderDetailSource = {
  cacheKey: 'persisted-order-detail-db-v1',
  async load(id, auth, signal) {
    const dto = await apiRequest<DemoDetailDto>(`/v1/orders/${encodeURIComponent(id)}`, {
      headers: authHeaders(auth),
      signal,
    });
    return mapDemoDetail(dto, id, auth);
  },
};

export const dbScheduleSource: ScheduleSource = {
  cacheKey: 'persisted-requested-delivery-db-v1',
  async load(window: CalendarWindow, auth, signal): Promise<ScheduleSnapshot> {
    const params = new URLSearchParams({
      from_date: window.from,
      to_exclusive: window.toExclusive,
      time_zone: window.timeZone,
    });
    const dto = await apiRequest<DemoCalendarDto>(
      `/v1/orders/planning/calendar?${params.toString()}`,
      { headers: authHeaders(auth), signal },
    );
    return mapDemoCalendar(dto, window, auth);
  },
};
