import { formatKLTimestamp } from '../../shared/date';
import type { OrderQueueItem, QueueFilters } from './types';

export const initialFilters: QueueFilters = {
  status: 'PENDING_ACCEPTANCE', search: '', from: '', to: '', product: '',
  channel: '', priority: '', risk: '', customer: '', size: '',
};
const knownStatuses = ['PENDING_ACCEPTANCE', 'ACCEPTED', 'REJECTED'];
export const statusBucket = (status?: string | null) => knownStatuses.includes(status ?? '') ? status : 'OTHER';
export const shown = (value?: string | null) => value?.trim() || 'Not available';

/** Offset required: an ambiguous local timestamp must not be silently assigned a zone. */
export function instant(value?: string | null): number | null {
  if (!value || !/T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}
export function timestamp(value?: string | null): string {
  return instant(value) === null ? 'Not available' : formatKLTimestamp(value);
}
export function businessDate(value?: string | null): string {
  const time = instant(value);
  if (time === null) return '';
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kuala_Lumpur', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(time);
  const part = (type: string) => parts.find(p => p.type === type)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
const contains = (value: string | null | undefined, query: string) =>
  (value ?? '').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());

export function selectOrders(items: OrderQueueItem[], filters: QueueFilters): OrderQueueItem[] {
  return items.filter(order => {
    const date = businessDate(order.receivedAt);
    return (filters.status === 'ALL' || statusBucket(order.status) === filters.status) &&
      (!filters.search.trim() || [order.id, order.customer, ...(order.lines ?? []).map(l => l.product)]
        .some(value => contains(value, filters.search))) &&
      (!filters.from || (!!date && date >= filters.from)) &&
      (!filters.to || (!!date && date <= filters.to)) &&
      (!filters.product.trim() || (order.lines ?? []).some(l => contains(l.product, filters.product))) &&
      contains(order.customer, filters.customer) &&
      (['channel', 'priority', 'risk', 'size'] as const).every(key => !filters[key] || shown(order[key]) === filters[key]);
  }).sort((a, b) => {
    const left = instant(a.receivedAt) ?? Infinity;
    const right = instant(b.receivedAt) ?? Infinity;
    return (left === right ? 0 : left < right ? -1 : 1) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  });
}

export function profitText(profit: OrderQueueItem['profit']): string {
  if (profit?.costComplete === false) return 'Cost incomplete — expected profit unavailable';
  if (profit?.costComplete !== true || !profit.priceSource?.trim() || !profit.costSource?.trim())
    return 'Not verified — expected profit unavailable';
  if (!profit.amount || !/^-?\d+(?:\.\d+)?$/.test(profit.amount) || !/^[A-Z]{3}$/.test(profit.currency ?? ''))
    return 'Not available — expected profit unknown';
  // Keep decimal strings intact; do not perform business arithmetic or round into fake precision.
  return `${profit.currency} ${profit.amount}`;
}
