import { instant } from './queue';
import type { OrderDetail, Quantity } from './detailTypes';

export const quantityText = (q?: Quantity) => q?.amount && q.unit ? `${q.amount} ${q.unit}` : 'Not available / unit not verified';
export function assessmentState(detail: OrderDetail, now: number): string {
  const a = detail.assessment; const time = instant(a?.snapshotAt);
  if (!a || !a.sourceVerified || !a.complete || a.freshness !== 'CURRENT' || time === null || time > now ||
      !a.snapshotId || !detail.version || a.orderVersion !== detail.version) return 'UNKNOWN';
  return ['FEASIBLE', 'CONDITIONAL', 'INFEASIBLE', 'UNKNOWN'].includes(a.status ?? '') ? a.status! : 'UNKNOWN';
}
export function snapshotAge(value: string | null | undefined, now: number): string {
  const time = instant(value);
  if (time === null) return 'Unknown';
  if (time > now) return 'Future timestamp — not verified';
  const minutes = Math.floor((now - time) / 60000);
  return `${minutes} minute(s) at last display refresh`;
}
export const evidenceAnchor = (id: string) => `order-message-${encodeURIComponent(id)}`;
export function moneyText(value?: string | null, currency?: string | null): string {
  return value && /^-?\d+(?:\.\d+)?$/.test(value) && /^[A-Z]{3}$/.test(currency ?? '') ? `${currency} ${value}` : 'Not available';
}
