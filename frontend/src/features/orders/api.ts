import { apiRequest, authHeaders, type RequestAuthHeaders } from '../../shared/api';
import type { OrderQueueSnapshot } from './types';

export class OrderQueueUnavailableError extends Error {
  constructor() {
    super('The order queue API contract is not yet verified. Backend order status, assessment and provenance data are required.');
    this.name = 'OrderQueueUnavailableError';
  }
}

export interface OrderQueueSource {
  /** Unique adapter/version cache namespace; do not reuse across different data sources. */
  cacheKey: string;
  load: (auth: RequestAuthHeaders, signal: AbortSignal) => Promise<OrderQueueSnapshot>;
}

/** Honest production default. No speculative request, commitment substitution or demo fallback. */
export const unavailableOrderQueueSource: OrderQueueSource = {
  cacheKey: 'order-queue-unavailable-v1',
  async load() { throw new OrderQueueUnavailableError(); },
};

/** Future integration seam: owner must first verify path + DTO and supply its mapper.
 * Reuses the existing HTTP layer and actor/tenant headers. No endpoint is assumed here.
 */
export function createOrderQueueHttpSource<Dto>(
  cacheKey: string,
  verifiedPath: string,
  map: (dto: Dto) => OrderQueueSnapshot,
): OrderQueueSource {
  return {
    cacheKey,
    async load(auth, signal) {
      const dto = await apiRequest<Dto>(verifiedPath, { headers: authHeaders(auth), signal });
      const snapshot = map(dto);
      const ids = snapshot.items.map(item => item.id);
      if (ids.some(id => !id.trim()) || new Set(ids).size !== ids.length ||
          !['complete', 'partial'].includes(snapshot.coverage)) {
        throw new Error('Invalid order queue mapping: unique stable IDs and explicit coverage required.');
      }
      return snapshot;
    },
  };
}
