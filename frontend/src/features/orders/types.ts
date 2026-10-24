/** Presentation boundary only: NOT a frozen backend DTO or canonical enum. */
export interface OrderQueueItem {
  id: string;
  status?: string | null;
  customer?: string | null;
  receivedAt?: string | null;
  completedAt?: string | null;
  channel?: string | null;
  lines?: { product?: string | null; quantity?: string | null; unit?: string | null }[];
  deadline?: string | null;
  fulfilment?: string | null;
  feasibility?: string | null;
  profit?: { amount?: string | null; currency?: string | null; priceSource?: string | null;
    costSource?: string | null; costComplete?: boolean | null };
  stockReason?: string | null;
  expiryReason?: string | null;
  capacityReason?: string | null;
  recommendation?: string | null;
  priority?: string | null;
  risk?: string | null;
  /** Backend-supplied business size category; never summed across incompatible units. */
  size?: string | null;
  evidenceTier: 'VERIFIED_FACT' | 'CLAIM' | 'COMPUTED_ASSESSMENT' | 'SCENARIO' | 'SYNTHETIC' | 'UNKNOWN';
}

export interface OrderQueueSnapshot {
  items: OrderQueueItem[];
  coverage: 'complete' | 'partial';
  /** Source timestamp, not browser fetch time. */
  asOf?: string | null;
}

export type StatusView = 'PENDING_ACCEPTANCE' | 'ACCEPTED' | 'REJECTED' | 'OTHER' | 'ALL';
export type QueueSort = 'FCFS' | 'DEADLINE';
export interface QueueFilters {
  status: StatusView;
  search: string;
  from: string;
  to: string;
  product: string;
  channel: string;
  priority: string;
  risk: string;
  customer: string;
  size: string;
  sort: QueueSort;
  deadlineFrom: string;
  deadlineTo: string;
  feasibility: string;
}
