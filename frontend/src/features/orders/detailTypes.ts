/** Local read model, not a claimed v2.2 wire contract. Decimal values retain supplied units. */
export interface Quantity { amount?: string | null; unit?: string | null }
export interface DetailEvidence { ref: string; quote?: string | null }
export interface RequestMessage { id: string; text?: string | null; channel?: string | null;
  receivedAt?: string | null; tier?: string | null }
export interface StructuredField { name: string; value?: string | null; status?: string | null; evidence?: DetailEvidence[] }
export interface MaterialAssessment {
  material: string; bom?: string | null; required?: Quantity; onHand?: Quantity;
  effective?: Quantity; shortage?: Quantity; lot?: string | null; location?: string | null;
  expiresAt?: string | null; sourceAt?: string | null; constraints?: string[];
  incoming?: { quantity: Quantity; status?: string | null; dueAt?: string | null; evidence?: string[] }[];
}
export interface ResourceReservation { id: string; orderId: string; orderStatus?: string | null;
  resource?: string | null; quantity?: Quantity; evidence?: string[]; verified?: boolean }
export interface CapacityAssessment { resource: string; workload?: Quantity; available?: Quantity;
  windowStart?: string | null; windowEnd?: string | null; conflicts?: string[];
  bottlenecks?: string[]; assumptions?: string[]; sourceAt?: string | null }
export interface OrderAssessment {
  id?: string | null; version?: string | null; orderVersion?: string | null;
  status?: string | null; snapshotId?: string | null; snapshotAt?: string | null;
  freshness: 'CURRENT' | 'STALE' | 'UNKNOWN'; sourceVerified: boolean; complete: boolean;
  recommendation?: string | null; reasons?: string[]; constraints?: string[];
  preferences?: string[]; blockers?: string[]; conditions?: string[]; assumptions?: string[];
  evidence?: string[]; missingEvidence?: string[];
}
export interface PricingAssessment {
  access: 'AUTHORIZED' | 'REDACTED' | 'UNKNOWN'; sourceVerified?: boolean;
  currency?: string | null; customerPrice?: string | null; quotedPrice?: string | null;
  priceSource?: string | null; quoteVersion?: string | null; disclosed?: string | null; agreed?: string | null;
  costs?: { component: string; amount?: string | null; source?: string | null }[];
  missingCosts?: string[]; costComplete?: boolean; profit?: string | null; costSource?: string | null;
  sourceAt?: string | null;
}
export interface OrderDetail {
  id: string; tenantId: string; customer?: string | null; channel?: string | null;
  receivedAt?: string | null; completedAt?: string | null; status?: string | null; version?: string | null;
  originalDeadline?: string | null; currentDeadline?: string | null; fulfilment?: string | null;
  location?: string | null; instructions?: string | null;
  lines?: { sku?: string | null; product?: string | null; quantity?: Quantity }[];
  messages?: RequestMessage[]; fields?: StructuredField[]; sourceWarnings?: string[];
  contextId?: string | null; contextStatus?: string | null; contextVersion?: string | null;
  contextUpdatedAt?: string | null; fieldConflicts?: string[];
  materials?: MaterialAssessment[]; reservations?: ResourceReservation[]; capacities?: CapacityAssessment[];
  assessment?: OrderAssessment | null; pricing?: PricingAssessment | null;
  /** Explicit association only. An order ID is never used as a commitment or context ID. */
  commitmentId?: string | null;
}
